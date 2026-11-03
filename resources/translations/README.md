# Prevodi

Srpski (latinica) je izvorni jezik — GUI radi bez ijednog fajla ovde.
Za novi jezik:

1. dodaj `lampcutter_<lang>.ts` (npr. `lampcutter_en.ts`) i prevedi stringove;
2. kompajliraj u `.qm` sa `pyside6-lrelease`;
3. pokreni GUI sa `--language <lang>` (hook u `ui/i18n.py`).

Ako fajl ne postoji, koriste se izvorni stringovi (bez greške).
