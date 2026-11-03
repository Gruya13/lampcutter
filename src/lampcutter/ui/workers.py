"""Background workers for the GUI (specification, 12.2).

The UI thread never touches the model. Long calls (model load, set_image,
predict, export) run in a `QThreadPool`; results carry a generation number, so
a result that arrives after a newer request is dropped instead of repainting
the canvas with stale data.
"""

from __future__ import annotations

import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, QTimer, Signal, Slot

from lampcutter.ui.tools import GenerationCounter


class WorkerSignals(QObject):
    """Signals emitted by one background task."""

    progress = Signal(str, float)
    finished = Signal(int, object)  # generation, result
    failed = Signal(int, str)  # generation, message


class Task(QRunnable):
    """Runs one callable in the thread pool and emits its result."""

    def __init__(
        self,
        generation: int,
        function: Callable[..., Any],
        args: tuple[Any, ...] = (),
        kwargs: dict[str, Any] | None = None,
    ) -> None:
        super().__init__()
        self.generation = generation
        self.function = function
        self.args = args
        self.kwargs = kwargs or {}
        self.signals = WorkerSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as error:  # reported to the UI thread
            detail = f"{type(error).__name__}: {error}"
            traceback.print_exc()
            self.signals.failed.emit(self.generation, detail)
            return
        self.signals.finished.emit(self.generation, result)


class TaskRunner(QObject):
    """Owns the thread pool and drops results that belong to older generations."""

    def __init__(self, parent: QObject | None = None, max_threads: int | None = None) -> None:
        super().__init__(parent)
        self.pool = QThreadPool(self)
        if max_threads is not None:
            self.pool.setMaxThreadCount(max_threads)
        self.generations = GenerationCounter()
        self.last_result: Any = None
        self.last_error: str | None = None
        self._on_finished: Callable[[Any], None] | None = None
        self._on_failed: Callable[[str], None] | None = None
        self._on_progress: Callable[[str, float], None] | None = None

    def run(
        self,
        function: Callable[..., Any],
        *args: Any,
        on_finished: Callable[[Any], None] | None = None,
        on_failed: Callable[[str], None] | None = None,
        on_progress: Callable[[str, float], None] | None = None,
        **kwargs: Any,
    ) -> int:
        """Start `function` in the pool; returns the request generation."""
        generation = self.generations.next()
        self._on_finished = on_finished
        self._on_failed = on_failed
        self._on_progress = on_progress
        task = Task(generation, function, args, kwargs)
        task.signals.finished.connect(self._handle_finished)
        task.signals.failed.connect(self._handle_failed)
        task.signals.progress.connect(self._handle_progress)
        self.pool.start(task)
        return generation

    @Slot(int, object)
    def _handle_finished(self, generation: int, result: Any) -> None:
        if not self.generations.is_current(generation):
            return  # stale result: a newer request superseded this one
        self.last_result = result
        if self._on_finished is not None:
            self._on_finished(result)

    @Slot(int, str)
    def _handle_failed(self, generation: int, message: str) -> None:
        if not self.generations.is_current(generation):
            return
        self.last_error = message
        if self._on_failed is not None:
            self._on_failed(message)

    @Slot(str, float)
    def _handle_progress(self, stage: str, fraction: float) -> None:
        if self._on_progress is not None:
            self._on_progress(stage, fraction)

    def cancel(self) -> None:
        """Invalidate every in-flight request (its result will be dropped)."""
        self.generations.next()

    def wait(self, timeout_ms: int = 5000) -> bool:
        """Block until the pool is idle (used by tests and shutdown)."""
        return self.pool.waitForDone(timeout_ms)


class Debouncer(QObject):
    """Delays a call by `interval_ms`; only the last request of a burst runs (spec 12.2)."""

    def __init__(self, interval_ms: int = 150, parent: QObject | None = None) -> None:
        super().__init__(parent)
        if interval_ms < 0:
            raise ValueError("interval_ms must be non-negative")
        self.interval_ms = interval_ms
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._fire)
        self._callback: Callable[[], None] | None = None

    def schedule(self, callback: Callable[[], None]) -> None:
        self._callback = callback
        self._timer.start(self.interval_ms)

    def cancel(self) -> None:
        self._timer.stop()
        self._callback = None

    @Slot()
    def _fire(self) -> None:
        callback = self._callback
        self._callback = None
        if callback is not None:
            callback()
