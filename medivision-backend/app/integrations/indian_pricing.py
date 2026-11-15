"""
Pradhan Mantri Bhartiya Janaushadhi Pariyojana (PMBJP) pricing lookup.

Sourced from indiser/Rxcheck's jan_aushadhi_catalog.json + price_catalog.json.

Catalog shape (jan_aushadhi_catalog.json):
  { "<salt_name>": [ {"drug_code": "...", "display": "...", "price": 4.69, "unit": "14's"}, ... ] }

Returns the government-capped price of a Janaushadhi (generic) medicine for a
given salt — useful in the medicine card UI to show users that a low-cost
generic equivalent exists for the branded medicine they just scanned.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
JAN_AUSHADHI_PATH = HERE / "indian_pricing" / "jan_aushadhi_catalog.json"
PRICE_CATALOG_PATH = HERE / "indian_pricing" / "price_catalog.json"

_jan_cache: dict[str, list[dict[str, Any]]] | None = None
_price_cache: dict[str, Any] | None = None


def available() -> bool:
    return JAN_AUSHADHI_PATH.exists() or PRICE_CATALOG_PATH.exists()


def _ensure_loaded() -> bool:
    global _jan_cache, _price_cache
    if _jan_cache is not None and _price_cache is not None:
        return True
    try:
        if JAN_AUSHADHI_PATH.exists() and _jan_cache is None:
            raw = json.loads(JAN_AUSHADHI_PATH.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                _jan_cache = {str(k): v for k, v in raw.items() if isinstance(v, list)}
            elif isinstance(raw, list):
                # Fallback: list of dicts — group by salt
                _jan_cache = {}
                for item in raw:
                    if isinstance(item, dict):
                        salt = str(item.get("salt") or item.get("generic") or "").lower()
                        if salt:
                            _jan_cache.setdefault(salt, []).append(item)
            else:
                _jan_cache = {}
        if PRICE_CATALOG_PATH.exists() and _price_cache is None:
            _price_cache = json.loads(PRICE_CATALOG_PATH.read_text(encoding="utf-8"))
        if _jan_cache is None:
            _jan_cache = {}
        if _price_cache is None:
            _price_cache = {}
        return True
    except Exception:
        _jan_cache, _price_cache = {}, {}
        return False


def count() -> int:
    if not _ensure_loaded():
        return 0
    return len(_jan_cache or {}) + (len(_price_cache or {}) if isinstance(_price_cache, dict) else 0)


def _normalise(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


from ..model_ner import is_insufficient_salt


def _extract_primary_drug_root(salt: str) -> str | None:
    if not salt or is_insufficient_salt(salt):
        return None
    clean = re.sub(r"[^a-zA-Z\s]", " ", salt).lower()
    stop = {
        "hydrochloride", "hcl", "sodium", "potassium", "maleate", "tartrate",
        "succinate", "mesylate", "phosphate", "sulfate", "sulphate", "acetate",
        "citrate", "tablets", "tablet", "capsules", "capsule", "injection", "syrup",
    }
    words = [w for w in clean.split() if len(w) >= 4 and w not in stop]
    return words[0] if words else None


def lookup_generic_price(salt: str, strength: str | None = None, form: str | None = None) -> dict[str, Any] | None:
    """Return the cheapest Janaushadhi generic price for a salt.

    Strict clinical safety rules:
      - Suffixes like 'hydrochloride' are rejected.
      - Matches must contain the primary active substance.
      - Form match (tablets never match injections).
      - Strength match (10mg never returns 25mg or 100mg). If unavailable, returns None.
    """
    if not _ensure_loaded() or not salt or is_insufficient_salt(salt):
        return None
    root = _extract_primary_drug_root(salt)
    if not root:
        return None

    # Gather matching candidate products from PMBJP
    candidates: list[dict[str, Any]] = []
    for k, v in _jan_cache.items():
        if not v:
            continue
        kn = k.lower()
        if re.search(rf"\b{re.escape(root)}\b", kn):
            candidates.extend(v)

    if not candidates:
        return None

    # Form filtering: Oral solid (Tablet/Capsule) must not match Injection or Syrup
    form_clean = (form or "Tablet").lower()
    if any(f in form_clean for f in ("tablet", "capsule", "pill", "oral")):
        candidates = [
            c for c in candidates
            if not any(
                bad in (c.get("display") or "").lower()
                for bad in ("injection", "ampoule", "vial", "syrup", "suspension", "ointment", "cream", "drops", "gel")
            )
        ]

    # Strength filtering: Never return a different strength
    if strength:
        str_m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mg|mcg|g)?\b", strength, re.I)
        if str_m:
            num = str_m.group(1)
            candidates = [
                c for c in candidates
                if re.search(rf"\b{re.escape(num)}\s*mg\b", (c.get("display") or "") + " " + (c.get("unit") or ""), re.I)
            ]
            if not candidates:
                return None

    if not candidates:
        return None

    def _price_num(item):
        v = item.get("price")
        try:
            return float(v) if v is not None and float(v) > 0 else 9999.0
        except Exception:
            return 9999.0

    candidates.sort(key=_price_num)
    best = candidates[0]
    best_price = best.get("price")
    return {
        "salt": salt,
        "brand": str(best.get("display") or "Janaushadhi generic"),
        "strength": str(best.get("unit") or strength or ""),
        "mrp": f"Rs. {best_price}" if best_price is not None and float(best_price) > 0 else "Price on packet",
        "unit": str(best.get("unit") or ""),
        "source": "PMBJP (Pradhan Mantri Bhartiya Janaushadhi Pariyojana)",
    }


def lookup_all_generics(salt: str, limit: int = 5, strength: str | None = None, form: str | None = None) -> list[dict[str, Any]]:
    """Return up to N Janaushadhi generics for a salt (for a 'compare prices' UI)."""
    if not _ensure_loaded() or not salt or is_insufficient_salt(salt):
        return []
    root = _extract_primary_drug_root(salt)
    if not root:
        return []

    candidates: list[dict[str, Any]] = []
    for k, v in _jan_cache.items():
        if not v:
            continue
        kn = k.lower()
        if re.search(rf"\b{re.escape(root)}\b", kn):
            candidates.extend(v)

    form_clean = (form or "Tablet").lower()
    if any(f in form_clean for f in ("tablet", "capsule", "pill", "oral")):
        candidates = [
            c for c in candidates
            if not any(
                bad in (c.get("display") or "").lower()
                for bad in ("injection", "ampoule", "vial", "syrup", "suspension", "ointment", "cream", "drops", "gel")
            )
        ]

    out = []
    for item in candidates[:limit]:
        out.append({
            "brand": str(item.get("display") or "Janaushadhi generic"),
            "strength": str(item.get("unit") or ""),
            "mrp": f"Rs. {item.get('price')}" if item.get("price") is not None else "",
            "unit": str(item.get("unit") or ""),
        })
    return out
