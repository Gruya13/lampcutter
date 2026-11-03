"""Device selection and the out-of-memory fallback chain (specification, 7.2, 11.1).

Nothing in this module imports torch at module level: the core pipeline must stay
usable (and testable) on machines where the ML stack is not installed.
"""

from __future__ import annotations

import os
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path

# Specification, 11.1 (PROVISIONAL until the benchmark in phase 0b).
VARIANT_ORDER: tuple[str, ...] = ("tiny", "small", "base_plus", "large")


class ModelUnavailableError(RuntimeError):
    """The SAM 2 stack (torch + sam2) is not installed or no checkpoint is present."""


def torch_available() -> bool:
    """True when torch can be imported (the ML extra is installed)."""
    try:
        import torch  # noqa: F401
    except ImportError:
        return False
    return True


def cuda_available() -> bool:
    if not torch_available():
        return False
    import torch

    return bool(torch.cuda.is_available())


def mps_available() -> bool:
    if not torch_available():
        return False
    import torch

    backend = getattr(torch.backends, "mps", None)
    return bool(backend is not None and backend.is_available())


def pick_device(preference: str = "auto") -> str:
    """Choose `cuda` -> `mps` -> `cpu`, honouring an explicit preference (7.2)."""
    if preference == "auto":
        if cuda_available():
            return "cuda"
        if mps_available():
            return "mps"
        return "cpu"
    if preference == "cuda":
        return "cuda" if cuda_available() else "cpu"
    if preference == "mps":
        return "mps" if mps_available() else "cpu"
    if preference == "cpu":
        return "cpu"
    raise ValueError(f"unknown device preference {preference!r}")


def cuda_vram_gb() -> float | None:
    """Total VRAM of device 0 in GiB, if CUDA is available."""
    if not cuda_available():
        return None
    import torch

    props = torch.cuda.get_device_properties(0)
    return props.total_memory / (1024**3)


def system_ram_gb() -> float | None:
    """Total system RAM in GiB, best effort across Linux and macOS."""
    try:
        if Path("/proc/meminfo").exists():
            for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) / (1024**2)
        if os.uname().sysname == "Darwin":
            import subprocess

            output = subprocess.check_output(["sysctl", "-n", "hw.memsize"], text=True)
            return int(output.strip()) / (1024**3)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return None


def pick_variant(
    device: str,
    vram_gb: float | None = None,
    ram_gb: float | None = None,
) -> str:
    """Default SAM 2 variant for the device (specification, 11.1, PROVISIONAL)."""
    if device == "cuda":
        total = vram_gb if vram_gb is not None else cuda_vram_gb()
        if total is None:
            return "small"
        if total < 6.0:
            return "small"
        if total < 8.0:
            return "base_plus"
        return "large"
    if device == "mps":
        total = ram_gb if ram_gb is not None else system_ram_gb()
        if total is not None and total < 8.0:
            return "tiny"
        return "base_plus"
    if device == "cpu":
        return "tiny"
    raise ValueError(f"unknown device {device!r}")


def fallback_variants(variant: str) -> list[str]:
    """The OOM fallback chain: `base_plus -> small -> tiny` (specification, 7.2)."""
    if variant not in VARIANT_ORDER:
        raise ValueError(f"unknown SAM 2 variant {variant!r}")
    start = VARIANT_ORDER.index(variant)
    return list(VARIANT_ORDER[: start + 1])[::-1]


def empty_cache(device: str) -> None:
    """Release cached GPU memory after an OOM (specification, 7.2)."""
    if not torch_available():
        return
    import torch

    if device == "cuda" and torch.cuda.is_available():
        torch.cuda.empty_cache()
    elif device == "mps" and mps_available():
        torch.mps.empty_cache()


def is_out_of_memory(error: BaseException) -> bool:
    """True for torch out-of-memory errors, including the MPS variant."""
    if not torch_available():
        return False
    import torch

    cuda_oom = getattr(torch.cuda, "OutOfMemoryError", None)
    if cuda_oom is not None and isinstance(error, cuda_oom):
        return True
    message = str(error).lower()
    return "out of memory" in message


def load_with_fallback[T](
    loader: Callable[[str, str], T],
    variants: Sequence[str],
    device: str,
    on_fallback: Callable[[str, str, BaseException], None] | None = None,
) -> tuple[T, str, str]:
    """Load a model, stepping down through variants on OOM and finally to CPU.

    `loader(variant, device)` returns the loaded model. Returns
    `(model, variant, device)`.
    """
    chain = list(variants)
    if not chain:
        raise ValueError("variants must not be empty")
    for index, variant in enumerate(chain):
        try:
            return loader(variant, device), variant, device
        except BaseException as error:
            if not is_out_of_memory(error):
                raise
            empty_cache(device)
            if on_fallback is not None:
                on_fallback(variant, device, error)
            if index == len(chain) - 1 and device != "cpu":
                break
    if device != "cpu":
        warnings.warn(
            "Nema dovoljno memorije za izabranu varijantu modela; prelazim na CPU.",
            RuntimeWarning,
            stacklevel=2,
        )
        try:
            return loader(chain[-1], "cpu"), chain[-1], "cpu"
        except BaseException as error:
            if not is_out_of_memory(error):
                raise
            raise ModelUnavailableError(
                "Model ne može da se učita ni na CPU (nedovoljno memorije)."
            ) from error
    raise ModelUnavailableError("Model ne može da se učini u memoriju.")
