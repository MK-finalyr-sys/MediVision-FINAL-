"""Conservative online discovery of unknown medicine brands.

Search snippets are *discovery hints*, not independently verified medical labels.
Require the same search result to contain a product token, full recognizable
ingredient name, and matching package strength when printed. Never combine
fields across unrelated hits. Returns a candidate only, never "verified-online".
"""
from __future__ import annotations

import re
from .identity_guard import ingredient_roots, visible_ingredients

STOP = {
    "tablet", "tablets", "capsule", "capsules", "medicine", "strip",
    "pack", "photo", "read", "name", "brand", "label", "dosage",
    "oral", "mg", "mcg", "ip", "usp", "bp", "information",
    "syrup", "injection", "gel", "drops", "pill", "as",
}
STRENGTH = re.compile(r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|g|iu|ml)\b", re.I)


def _strengths(text: str) -> set[str]:
    return {f"{m.group(1)} {m.group(2).lower()}" for m in STRENGTH.finditer(text or "")}


def discover(ocr_text: str, hits: list[dict]) -> dict | None:
    tokens = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9-]{3,}", ocr_text or ""):
        if token.casefold() not in STOP and not any(ch.isdigit() for ch in token):
            tokens.append(token)
    if not tokens:
        return None
    requested_strengths = _strengths(ocr_text)
    results: list[dict] = []
    for h in hits[:8]:
        url = h.get("url") or ""
        if not url.startswith("https://"):
            continue
        blob = f"{h.get('title') or ''} {h.get('snippet') or ''}"
        # A source must mention a substantial product token from the user's
        # OCR. Generic dosage words are not sufficient for medicine identity.
        matches = [
            t for t in tokens
            if re.search(r"(?<![A-Za-z0-9])" + re.escape(t) + r"(?![A-Za-z0-9])", blob, re.I)
        ]
        if not matches:
            continue
        names = visible_ingredients(blob)
        roots = set().union(*(ingredient_roots(n) for n in names))
        if len(roots) != 1:
            continue
        source_strengths = _strengths(blob)
        if requested_strengths and (not requested_strengths.intersection(source_strengths)):
            continue
        if requested_strengths and any(x != next(iter(requested_strengths)) for x in source_strengths):
            # Ambiguous doses in one result aren't a sufficient formulation match.
            continue
        # Never reuse a source referencing only the ingredient as a brand match
        # when the user's text also includes a distinct name.
        distinct = [t for t in matches if t.casefold() not in roots]
        if len(tokens) > 1 and not distinct:
            continue
        results.append({
            "brand": distinct[0] if distinct else None,
            "salt": names[0],
            "strength": next(iter(requested_strengths)) if len(requested_strengths) == 1 else None,
            "url": url,
            "title": h.get("title") or "Online search result",
        })
    if not results:
        return None
    # The same single source must be self-consistent; conflicting search
    # results cannot be resolved into a single proposed formulation.
    if len({tuple(ingredient_roots(r["salt"])) for r in results}) > 1:
        return None
    return results[0]
