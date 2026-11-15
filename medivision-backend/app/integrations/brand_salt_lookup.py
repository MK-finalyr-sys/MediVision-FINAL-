"""
Indian brand → salt lookup, sourced from indiser/Rxcheck's brand_hints.json.

This expands our medicine lexicon from 80 brands (curated) to 323,711 brands
(real Indian market) — used by:
  - /candidates  (Feature 1: damaged-strip probability analysis)
  - /identify    (existing pipeline, when no model salt is recognised)
  - /recommend   (Feature 2: maps patient-supplied brand names to canonical salts)

The file is 13 MB raw JSON; we load it lazily on first use, then cache the dict
in-process. Subsequent lookups are O(1) dict lookups.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ..model_ner import is_insufficient_salt

HERE = Path(__file__).parent
HINTS_PATH = HERE / "indian_pricing" / "brand_hints.json"

_cache: dict[str, str] | None = None
_tried_load = False


def available() -> bool:
    return HINTS_PATH.exists()


def _ensure_loaded() -> bool:
    global _cache, _tried_load
    if _cache is not None:
        return True
    if _tried_load:
        return False
    _tried_load = True
    if not HINTS_PATH.exists():
        return False
    try:
        with open(HINTS_PATH, encoding="utf-8") as f:
            raw = json.load(f)
        # Normalise keys to lowercase for case-insensitive lookup.
        _cache = {str(k).strip().lower(): str(v).strip() for k, v in raw.items() if v}
        return True
    except Exception:
        _cache = None
        return False


def count() -> int:
    if not _ensure_loaded():
        return 0
    return len(_cache or {})


BRAND_SYNONYMS: dict[str, str] = {
    "a-trip": "amitriptyline",
    "a-trip 10": "amitriptyline",
    "a-trip-10": "amitriptyline",
    "atrip": "amitriptyline",
    "atrip 10": "amitriptyline",
    "atrip-10": "amitriptyline",
    "p.ntopra": "pantoprazole",
    "p.ntopra 40": "pantoprazole",
    "pantopra": "pantoprazole",
    "glycomet-gp": "metformin + glimepiride",
    "glycomet-gp 1": "metformin + glimepiride",
    "telma-h": "telmisartan + hydrochlorothiazide",
    "augmentin 625": "amoxicillin + clavulanic acid",
    "augmentin 625 duo": "amoxicillin + clavulanic acid",
    "shelcal 500": "calcium + vitamin d3",
    "pan-d": "pantoprazole + domperidone",
}

KNOWN_BRAND_METADATA: dict[str, dict[str, Any]] = {
    "a-trip-10": {
        "brand": "A-TRIP-10",
        "salt": "Amitriptyline Hydrochloride",
        "canonicalSalt": "Amitriptyline",
        "strength": "10 mg",
        "form": "Tablet",
        "manufacturer": "Marc Cure",
        "url": "https://marccure.in/products/a-trip-10-amitriptyline-tablet",
    },
    "a-trip 10": {
        "brand": "A-TRIP-10",
        "salt": "Amitriptyline Hydrochloride",
        "canonicalSalt": "Amitriptyline",
        "strength": "10 mg",
        "form": "Tablet",
        "manufacturer": "Marc Cure",
        "url": "https://marccure.in/products/a-trip-10-amitriptyline-tablet",
    },
    "a-trip": {
        "brand": "A-TRIP-10",
        "salt": "Amitriptyline Hydrochloride",
        "canonicalSalt": "Amitriptyline",
        "strength": "10 mg",
        "form": "Tablet",
        "manufacturer": "Marc Cure",
        "url": "https://marccure.in/products/a-trip-10-amitriptyline-tablet",
    },
    "atrip-10": {
        "brand": "A-TRIP-10",
        "salt": "Amitriptyline Hydrochloride",
        "canonicalSalt": "Amitriptyline",
        "strength": "10 mg",
        "form": "Tablet",
        "manufacturer": "Marc Cure",
        "url": "https://marccure.in/products/a-trip-10-amitriptyline-tablet",
    },
    "dolo 650": {
        "brand": "Dolo 650",
        "salt": "Paracetamol",
        "canonicalSalt": "Paracetamol",
        "strength": "650 mg",
        "form": "Tablet",
        "manufacturer": "Micro Labs Ltd.",
    },
    "pan 40": {
        "brand": "Pan 40",
        "salt": "Pantoprazole Sodium",
        "canonicalSalt": "Pantoprazole",
        "strength": "40 mg",
        "form": "Tablet",
        "manufacturer": "Alkem Laboratories Ltd.",
    },
    "p.ntopra 40": {
        "brand": "Pantop 40",
        "salt": "Pantoprazole Sodium",
        "canonicalSalt": "Pantoprazole",
        "strength": "40 mg",
        "form": "Tablet",
        "manufacturer": "Aristo Pharmaceuticals",
    },
    "glycomet-gp 1": {
        "brand": "Glycomet-GP 1",
        "salt": "Metformin + Glimepiride",
        "canonicalSalt": "Metformin + Glimepiride",
        "strength": "500 mg / 1 mg",
        "form": "Tablet",
        "manufacturer": "USV Pvt Ltd",
    },
    "augmentin 625 duo": {
        "brand": "Augmentin 625 Duo",
        "salt": "Amoxicillin + Clavulanic Acid",
        "canonicalSalt": "Amoxicillin + Clavulanic Acid",
        "strength": "625 mg",
        "form": "Tablet",
        "manufacturer": "GlaxoSmithKline Pharmaceuticals",
    },
    "ecosprin 75": {
        "brand": "Ecosprin 75",
        "salt": "Aspirin",
        "canonicalSalt": "Aspirin",
        "strength": "75 mg",
        "form": "Tablet",
        "manufacturer": "USV Pvt Ltd",
    },
}


def lookup_brand_details(brand: str) -> dict[str, Any] | None:
    """Return enriched product details (brand, salt, manufacturer, URL) if known."""
    if not brand:
        return None
    b = brand.strip().lower()
    if b in KNOWN_BRAND_METADATA:
        cand = dict(KNOWN_BRAND_METADATA[b])
        if not is_insufficient_salt(cand.get("canonicalSalt") or cand.get("salt")):
            return cand
    b_var = b.replace("-", " ")
    if b_var in KNOWN_BRAND_METADATA:
        cand = dict(KNOWN_BRAND_METADATA[b_var])
        if not is_insufficient_salt(cand.get("canonicalSalt") or cand.get("salt")):
            return cand
    s = lookup_salt(brand)
    if s and not is_insufficient_salt(s):
        return {
            "brand": brand.strip(),
            "salt": s.title(),
            "canonicalSalt": s.title(),
        }
    return None


def lookup_salt(brand: str) -> str | None:
    """Return the canonical salt for an Indian brand name, or None."""
    if not brand:
        return None
    b = brand.strip().lower()
    if b in BRAND_SYNONYMS:
        s = BRAND_SYNONYMS[b]
        return None if is_insufficient_salt(s) else s
    # Check hyphens and variations in synonyms
    b_var = b.replace("-", " ")
    if b_var in BRAND_SYNONYMS:
        s = BRAND_SYNONYMS[b_var]
        return None if is_insufficient_salt(s) else s

    if not _ensure_loaded():
        return None
    if b in _cache:
        s = _cache[b]
        return None if is_insufficient_salt(s) else s
    if b_var in _cache:
        s = _cache[b_var]
        return None if is_insufficient_salt(s) else s
    # Try progressively shorter prefixes (handles 'Brand 500 mg', 'Brand 500', 'Brand')
    parts = b.split()
    for n in range(len(parts) - 1, 0, -1):
        prefix = " ".join(parts[:n])
        if len(prefix) >= 3:
            if prefix in BRAND_SYNONYMS:
                s = BRAND_SYNONYMS[prefix]
                if not is_insufficient_salt(s):
                    return s
            if prefix in _cache:
                s = _cache[prefix]
                if not is_insufficient_salt(s):
                    return s
    return None


def all_brands_for_salt(salt: str) -> list[str]:
    """Return all known Indian brand names that map to a given salt."""
    if not _ensure_loaded():
        return []
    s = (salt or "").strip().lower()
    return [b for b, v in _cache.items() if v.lower() == s]


def search_brands(query: str, limit: int = 10) -> list[dict[str, str]]:
    """Substring search over the brand index — for the manual-search UI path."""
    if not _ensure_loaded():
        return []
    q = (query or "").strip().lower()
    if not q:
        return []
    out = []
    for brand, salt in _cache.items():
        if q in brand:
            out.append({"brand": brand, "salt": salt})
            if len(out) >= limit:
                break
    return out
