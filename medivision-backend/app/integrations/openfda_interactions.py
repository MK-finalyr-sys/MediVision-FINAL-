"""
OpenFDA drug-interactions fallback — synchronous port of pillchecker-api's
openfda_client.py (MIT). Used when DDInter has no row for a drug pair, OR when
the DDInter SQLite DB has not been built yet.

No API key required. FDA rate limit: 240 req/min. We cache responses for 4
hours to stay well under that limit and to keep /recommend fast.
"""
from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import quote

import httpx

OPENFDA_BASE = "https://api.fda.gov/drug/label.json"
HTTP_TIMEOUT = 12.0
_CACHE_TTL = 14400   # 4 hours

_cache: dict[str, tuple[str | None, float]] = {}


def _cache_get(key: str) -> str | None:
    entry = _cache.get(key)
    if entry and time.time() < entry[1]:
        return entry[0]
    return None


def _cache_set(key: str, value: str | None) -> None:
    _cache[key] = (value, time.time() + _CACHE_TTL)


def available() -> bool:
    return True   # always available — it's a keyless public API


def _fetch_label_text(drug_name: str) -> str | None:
    """Fetch and cache the drug_interactions text from an FDA label."""
    cached = _cache_get(drug_name)
    if cached is not None:
        return cached
    try:
        for search in (
            f'active_ingredient:"{quote(drug_name)}"',
            f'openfda.generic_name:"{quote(drug_name)}"',
            f'openfda.brand_name:"{quote(drug_name)}"',
        ):
            url = f"{OPENFDA_BASE}?search={search}&limit=1"
            r = httpx.get(url, timeout=HTTP_TIMEOUT,
                          headers={"User-Agent": "MediVisionAI-FYP/1.0"},
                          follow_redirects=True)
            if r.status_code != 200:
                continue
            results = (r.json() or {}).get("results") or []
            if not results:
                continue
            text = " ".join(results[0].get("drug_interactions") or [])
            _cache_set(drug_name, text)
            return text
        _cache_set(drug_name, "")
        return ""
    except Exception:
        return None


def check_pair(drug_a: str, drug_b: str) -> dict[str, Any] | None:
    """Returns an interaction entry if drug_a's FDA label mentions drug_b."""
    if not drug_a or not drug_b:
        return None
    text = _fetch_label_text(drug_a)
    if not text:
        return None
    # Look for the other drug's name (case-insensitive, word boundary).
    # Match either the full name or the salt stem (e.g. 'warfarin' vs 'warfarin sodium').
    pattern = r"\b" + re.escape(drug_b.lower()) + r"\b"
    if re.search(pattern, text.lower()):
        # Try to extract the surrounding sentence as 'effect'
        m = re.search(r"[^.]*\b" + re.escape(drug_b.lower()) + r"\b[^.]*\.", text.lower())
        effect = m.group(0).strip().capitalize() if m else "Mentioned in the drug_interactions section of the FDA label."
        return {
            "drugA": drug_a,
            "drugB": drug_b,
            "level": "Moderate",   # FDA labels don't tag severity — be conservative
            "effect": effect[:300],
            "mechanism": "Mentioned in FDA drug_interactions label text.",
            "source": "openFDA (U.S. FDA drug label)",
            "url": f"https://api.fda.gov/drug/label.json?search=active_ingredient:%22{quote(drug_a)}%22&limit=1",
        }
    return None


def check_drug(drug_name: str, others: list[str]) -> list[dict[str, Any]]:
    """For a single drug, check it against a list of others. One HTTP call
    (cached) per drug, so cost is bounded by len(others) cache lookups."""
    out = []
    if not drug_name or not others:
        return out
    text = _fetch_label_text(drug_name)
    if not text:
        return out
    text_low = text.lower()
    for other in others:
        if other and re.search(r"\b" + re.escape(other.lower()) + r"\b", text_low):
            m = re.search(r"[^.]*\b" + re.escape(other.lower()) + r"\b[^.]*\.", text_low)
            out.append({
                "drug": drug_name,
                "otherDrug": other,
                "level": "Moderate",
                "effect": (m.group(0).strip().capitalize() if m else "Mentioned in the FDA drug_interactions section.")[:300],
                "source": "openFDA (U.S. FDA drug label)",
            })
    return out
