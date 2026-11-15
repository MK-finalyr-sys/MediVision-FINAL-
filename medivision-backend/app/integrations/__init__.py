"""
MediVision AI — Integrations layer.

Optional adapters that pull in external repos / models when available, and
fall back to the built-in pipeline when they are not. Every adapter exposes:

  - status() -> str         : human-readable readiness line for /health
  - available() -> bool     : True if the integration is installed and ready

The backend's main.py calls these to populate the /health `integrations` map,
and each endpoint (candidates, recommend, chat) calls the matching adapter
behind a try/except so the API never hard-fails when an integration is absent.
"""
from __future__ import annotations

import os
from pathlib import Path

HERE = Path(__file__).parent
INTEGRATIONS_DIR = HERE


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


# --- integration feature flags (default: try to use, but never crash) ---
ENABLE_PILL_CLASSIFIER = not _env_truthy("MV_DISABLE_PILL_CLASSIFIER")
ENABLE_DDINTER = not _env_truthy("MV_DISABLE_DDINTER")
ENABLE_OPENFDA_INTERACTIONS = not _env_truthy("MV_DISABLE_OPENFDA_INTERACTIONS")
ENABLE_BRAND_LOOKUP = not _env_truthy("MV_DISABLE_BRAND_LOOKUP")
ENABLE_PMJP_PRICING = not _env_truthy("MV_DISABLE_PMJP_PRICING")
ENABLE_INDIC_STT = _env_truthy("MV_ENABLE_INDIC_STT")   # heavy — opt-in
ENABLE_MEDITRON = _env_truthy("MV_ENABLE_MEDITRON")      # needs Ollama — opt-in


def status_map() -> dict[str, dict[str, object]]:
    """Returns one entry per integration for /health."""
    out: dict[str, dict[str, object]] = {}

    try:
        from . import pill_classifier
        out["pillClassifier"] = {
            "available": ENABLE_PILL_CLASSIFIER and pill_classifier.available(),
            "model": pill_classifier.MODEL_NAME,
            "classes": pill_classifier.num_classes(),
        }
    except Exception as e:
        out["pillClassifier"] = {"available": False, "error": str(e)[:80]}

    try:
        from . import brand_salt_lookup
        out["brandLookup"] = {
            "available": ENABLE_BRAND_LOOKUP and brand_salt_lookup.available(),
            "brands": brand_salt_lookup.count(),
        }
    except Exception as e:
        out["brandLookup"] = {"available": False, "error": str(e)[:80]}

    try:
        from . import indian_pricing
        out["pmjpPricing"] = {
            "available": ENABLE_PMJP_PRICING and indian_pricing.available(),
            "entries": indian_pricing.count(),
        }
    except Exception as e:
        out["pmjpPricing"] = {"available": False, "error": str(e)[:80]}

    try:
        from . import ddinter
        out["ddInter"] = {
            "available": ENABLE_DDINTER and ddinter.available(),
            "dbPath": ddinter.DB_PATH,
            "rows": ddinter.row_count() if ddinter.available() else 0,
        }
    except Exception as e:
        out["ddInter"] = {"available": False, "error": str(e)[:80]}

    try:
        from . import openfda_interactions
        out["openfdaInteractions"] = {
            "available": ENABLE_OPENFDA_INTERACTIONS,
        }
    except Exception as e:
        out["openfdaInteractions"] = {"available": False, "error": str(e)[:80]}

    try:
        from . import indic_stt
        out["indicSTT"] = {
            "available": ENABLE_INDIC_STT and indic_stt.available(),
            "model": indic_stt.MODEL_ID if ENABLE_INDIC_STT else None,
        }
    except Exception as e:
        out["indicSTT"] = {"available": False, "error": str(e)[:80]}

    try:
        from . import meditron_chat
        out["meditron"] = {
            "available": ENABLE_MEDITRON and meditron_chat.available(),
            "model": meditron_chat.MODEL_NAME if ENABLE_MEDITRON else None,
        }
    except Exception as e:
        out["meditron"] = {"available": False, "error": str(e)[:80]}

    return out


def integration_summary() -> str:
    """One-line summary for logs."""
    parts = []
    m = status_map()
    for name, info in m.items():
        if info.get("available"):
            extra = ""
            if "classes" in info:
                extra = f" ({info['classes']} classes)"
            elif "brands" in info:
                extra = f" ({info['brands']} brands)"
            elif "rows" in info and info["rows"]:
                extra = f" ({info['rows']} rows)"
            elif "entries" in info:
                extra = f" ({info['entries']} entries)"
            parts.append(f"{name}✓{extra}")
        else:
            parts.append(f"{name}✗")
    return " · ".join(parts)
