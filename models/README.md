# Modeli

Checkpointi SAM 2 i `manifest.json` sa SHA256 sumama. Checkpointi se ne
commit-uju (vidi `.gitignore`); `manifest.json` ostaje u git-u.

Preuzimanje je build-time: `scripts/fetch_models.py` (Faza E/0a).
Runtime aplikacija ništa ne preuzima — radi offline (specifikacija, 11.3).
