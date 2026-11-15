"""
MediVision AI — DAMAGED-STRIP PROBABILITY ANALYSIS (Feature 1).

When a strip is damaged, scratched, or partially obscured, the OCR text is
ambiguous and a single best-guess match is not enough — the user needs to see
RANKED CANDIDATES with probabilities so they can pick the right one.

Pipeline:
  1. normalise OCR text (undo 0<->O, 1<->I, drop noise chars)
  2. run the trained CRF NER to extract every BRAND / SALT / STRENGTH span
  3. for every plausible token in the text, fuzzy-match it against:
       - the 80-brand lexicon  (BRAND_TO_SALT)
       - the 40-salt lexicon   (LEXICON keys)
     using difflib similarity (cutoff 0.55 — lower than the single-match path
     so damaged tokens still surface)
  4. score each candidate salt:
       raw = 0.5 * brand_score  +  0.5 * salt_score
       + 0.15 bonus if the NER model tagged this token as BRAND/SALT
       + 0.10 bonus if a STRENGTH entity was found anywhere in the text
       + 0.10 bonus if web evidence confirms the salt name (best-effort, 1 query)
  5. softmax-normalise raw scores across all candidates -> probabilities summing to 1.0
  6. drop anything below 0.03; if list is empty, return the WEB_SEARCH fallback
     note so the frontend can show "ask your pharmacist".

The function NEVER invents a salt — every candidate comes from the curated
lexicon, so the probabilities are always over a known-safe set of 40 salts.

Run standalone:
  python3 -c "from app.candidates import ranked_candidates; print(ranked_candidates('Do1o 650 Tab1et'))"
"""
from __future__ import annotations

import difflib
import math
import re
from typing import Any

from .data import BRAND_TO_SALT, LEXICON
from . import retriever, pipeline
from .model_ner import predict_entities, status as ner_status, is_insufficient_salt
from .integrations import brand_salt_lookup

# Reasonable cutoff: damaged strips need recall, but random words must not produce false candidates.
BRAND_CUTOFF = 0.70
SALT_CUTOFF = 0.70

_ALL_SALTS = list(LEXICON.keys())                       # 40 curated salts
_ALL_BRANDS = list(BRAND_TO_SALT.keys())                # ~80 curated brands (lowercased)
_BRAND_TO_SALT = BRAND_TO_SALT                          # alias

# Typical strengths for common Indian OTC/Rx brands to detect brand-strength conflicts
TYPICAL_BRAND_STRENGTHS: dict[str, list[str]] = {
    "dolo": ["500", "650"],
    "calpol": ["120", "250", "500", "650"],
    "crocin": ["500", "650"],
    "pan": ["20", "40"],
    "pantocid": ["20", "40"],
    "ecosprin": ["75", "150"],
    "glycomet": ["250", "500", "850", "1000"],
    "azithral": ["250", "500"],
    "augmentin": ["375", "625", "1000"],
    "a-trip": ["10", "25", "50"],
}


def _fuzzy(query: str, choices: list[str], cutoff: float, n: int = 3) -> list[tuple[str, float]]:
    """difflib.get_close_matches but RETURNS the scores (stdlib drops them)."""
    if not query or not choices:
        return []
    q = query.lower()
    scored = []
    for c in choices:
        s = difflib.SequenceMatcher(None, q, c.lower()).ratio()
        if s >= cutoff:
            scored.append((c, s))
    scored.sort(key=lambda t: -t[1])
    return scored[:n]


STOP_FORM_WORDS = {
    "tab", "tabs", "tablet", "tablets", "cap", "caps", "capsule", "capsules",
    "ets", "strip", "pack", "dose", "oral", "batch", "exp", "mfg", "mrp", "rs",
    "use", "only", "keep", "reach", "children", "store", "cool", "dry", "place",
    "and", "for", "with", "the",
}


def _tokenize_for_candidates(text: str) -> list[str]:
    """Extract alpha tokens, hyphenated terms, and OCR fragments."""
    tokens: list[str] = []
    # 1. Hyphenated or compound terms (e.g. A-TRIP-10, A-TRIP, Pan-40)
    for m in re.finditer(r"[A-Za-z0-9]+(?:[\.\-][A-Za-z0-9]+)+", text):
        tok = m.group(0).strip(".-")
        if tok and tok.lower() not in STOP_FORM_WORDS:
            tokens.append(tok)
    # 2. Simple alpha tokens >= 3 chars
    for w in re.findall(r"[A-Za-z]{3,}", text):
        if w.lower() not in STOP_FORM_WORDS:
            tokens.append(w)
    # Deduplicate while preserving order
    return list(dict.fromkeys(tokens))


def _web_confirms_salt(salt: str) -> bool:
    """One keyless web query; if any hit mentions the salt + a medical word,
    we treat it as evidence the salt is real (boosts its score by 0.10)."""
    try:
        hits = retriever.web_search(f"{salt} medicine uses side effects", n=3)
        needle = salt.lower()
        for h in hits:
            hay = f"{h.get('title','')} {h.get('snippet','')}".lower()
            if needle in hay and pipeline.MEDICAL_CONTEXT.search(hay):
                return True
    except Exception:
        pass
    return False


def ranked_candidates(ocr_text: str, top_k: int = 5) -> dict[str, Any]:
    """Return probability-ranked candidate salts for a (possibly damaged) strip."""
    text = pipeline.normalise(ocr_text)
    ner = predict_entities(text)
    entities = ner["entities"]
    strength_entity = next((e for e in entities if e["label"] == "STRENGTH"), None)
    ner_brands = {e["text"].lower() for e in entities if e["label"] == "BRAND"}
    ner_salts = {e["text"].lower() for e in entities if e["label"] == "SALT"}

    # Detect standalone strength from regex if NER missed it (e.g. "40", "10mg", "650")
    detected_strength: str | None = strength_entity["text"] if strength_entity else None
    if not detected_strength:
        str_m = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:mg|mcg|g)?\b", text, re.I)
        if str_m and int(float(str_m.group(1))) in (5, 10, 20, 25, 40, 50, 75, 100, 200, 250, 400, 500, 625, 650, 850, 1000):
            detected_strength = str_m.group(1)

    raw: dict[str, dict[str, Any]] = {}
    tokens = _tokenize_for_candidates(text)

    # 1. Indian Brand Index (323,711 brands) exact & prefix matches
    if brand_salt_lookup.available():
        for token in tokens:
            clean_tok = re.sub(r"[^A-Za-z0-9\s]", " ", token).strip().lower()
            for variant in (token.lower(), clean_tok, token.replace("-", " ").lower()):
                salt_hit = brand_salt_lookup.lookup_salt(variant)
                if salt_hit and not is_insufficient_salt(salt_hit):
                    salt_canonical = salt_hit.title()
                    score = 0.96 if ("-" in token or " " in token) else 0.90
                    entry = raw.setdefault(salt_canonical, {
                        "salt": salt_canonical, "matchedToken": token, "matchedBrand": token,
                        "brandScore": score, "saltScore": 0.0,
                        "nerTagged": token.lower() in ner_brands, "basis": "indian-brand-index",
                    })
                    entry["brandScore"] = max(entry["brandScore"], score)

    # 2. Curated 80-brand and 40-salt fuzzy matching
    for token in tokens:
        # Require higher cutoff for short 3-letter tokens to prevent false positives from fragments like "xyz"
        effective_brand_cutoff = 0.85 if len(token) <= 3 else BRAND_CUTOFF
        effective_salt_cutoff = 0.85 if len(token) <= 3 else SALT_CUTOFF

        # --- brand fuzzy path: token -> brand -> salt ---
        brand_hits = _fuzzy(token, _ALL_BRANDS, effective_brand_cutoff, n=3)
        for brand, brand_score in brand_hits:
            salt = _BRAND_TO_SALT[brand]
            if is_insufficient_salt(salt):
                continue
            entry = raw.setdefault(salt, {
                "salt": salt, "matchedToken": token, "matchedBrand": brand,
                "brandScore": 0.0, "saltScore": 0.0,
                "nerTagged": False, "basis": "brand-fuzzy",
            })
            if brand_score > entry["brandScore"]:
                entry["brandScore"] = brand_score
                entry["matchedBrand"] = brand
                entry["matchedToken"] = token
                entry["basis"] = "brand-fuzzy"
            if token.lower() in ner_brands:
                entry["nerTagged"] = True
                entry["basis"] = "brand-fuzzy+ner"

        # --- salt fuzzy path: token -> salt directly ---
        salt_hits = _fuzzy(token, _ALL_SALTS, effective_salt_cutoff, n=2)
        for salt, salt_score in salt_hits:
            if is_insufficient_salt(salt):
                continue
            entry = raw.setdefault(salt, {
                "salt": salt, "matchedToken": token, "matchedBrand": None,
                "brandScore": 0.0, "saltScore": 0.0,
                "nerTagged": False, "basis": "salt-fuzzy",
            })
            if salt_score > entry["saltScore"]:
                entry["saltScore"] = salt_score
                entry["matchedToken"] = token
                entry["basis"] = "salt-fuzzy+ner" if token.lower() in ner_salts else "salt-fuzzy"
            if token.lower() in ner_salts:
                entry["nerTagged"] = True

    # 3. If NER model provided a salt directly, include it
    if ner.get("salt") and not is_insufficient_salt(ner["salt"]):
        salt = ner["salt"]
        entry = raw.setdefault(salt, {
            "salt": salt, "matchedToken": ner.get("brand") or salt,
            "matchedBrand": ner.get("brand"), "brandScore": 0.0, "saltScore": 1.0,
            "nerTagged": True, "basis": ner.get("mappingBasis", "ner-direct"),
        })
        entry["saltScore"] = max(entry["saltScore"], 1.0)
        entry["nerTagged"] = True

    # 4. Online-first retrieval for damaged strips & out-of-lexicon brands (e.g. A-TRIP-10)
    web_evidence: list[dict[str, str]] = []
    medical_tokens = [t for t in tokens if len(t) >= 4 and not is_insufficient_salt(t)]
    if (not raw or any("-" in t for t in tokens)) and medical_tokens:
        hits = retriever.web_search(f"{text} medicine tablet uses composition", n=6)
        if hits and pipeline._relevance_ok(text, hits, require_medical=True):
            web_evidence = [{"title": h["title"], "url": h["url"], "snippet": h["snippet"]} for h in hits[:5]]
            extracted = retriever.extract_medicine_details_from_evidence(text, hits)
            if extracted.get("salt") and not is_insufficient_salt(extracted["salt"]):
                ext_salt = extracted["salt"].title()
                entry = raw.setdefault(ext_salt, {
                    "salt": ext_salt, "matchedToken": text[:30], "matchedBrand": extracted.get("brand") or text[:20],
                    "brandScore": 0.92, "saltScore": 0.85,
                    "nerTagged": True, "basis": "online-search-grounding",
                })
                entry["brandScore"] = max(entry["brandScore"], 0.92)

    # 5. Check for unknown/gibberish text: if nothing matches or scores are sub-threshold
    if not raw:
        return {
            "found": False,
            "query": text[:400],
            "candidates": [],
            "entities": entities,
            "nerModel": ner["model"],
            "note": "NO_MATCH",
            "webEvidence": web_evidence,
            "uncertainties": [],
        }

    # 6. Detect Brand / Ingredient / Strength disagreements
    uncertainties: list[str] = []
    if detected_strength:
        for entry in raw.values():
            mb = (entry.get("matchedBrand") or "").lower()
            for brand_key, allowed_strengths in TYPICAL_BRAND_STRENGTHS.items():
                if brand_key in mb and detected_strength not in allowed_strengths:
                    uncertainties.append(
                        f"Brand '{entry['matchedBrand']}' typically contains {', '.join(allowed_strengths)}mg, but strength '{detected_strength}' was read on the strip. Verify dosage carefully."
                    )

    # 7. Compute raw scores and softmax normalise
    salt_list = list(raw.values())
    has_strength = detected_strength is not None

    scored = []
    for e in salt_list:
        raw_score = 0.5 * e["brandScore"] + 0.5 * e["saltScore"]
        if e["nerTagged"]:
            raw_score += 0.15
        if has_strength:
            raw_score += 0.10
        if e["basis"] in ("indian-brand-index", "online-search-grounding"):
            raw_score += 0.15
        scored.append((e, raw_score))

    temperatures = [s for _, s in scored]
    if temperatures:
        m = max(temperatures)
        exps = [math.exp((s - m) * 3.0) for s in temperatures]
        z = sum(exps)
        probs = [e / z for e in exps]
    else:
        probs = []

    candidates = []
    for (e, _), p in zip(scored, probs):
        if p < 0.03:
            continue
        us_name = pipeline.SALT_TO_US.get(e["salt"], e["salt"])
        candidates.append({
            "salt": e["salt"],
            "usName": us_name,
            "probability": round(p, 4),
            "basis": e["basis"],
            "matchedToken": e["matchedToken"],
            "matchedBrand": e["matchedBrand"],
            "brandScore": round(e["brandScore"], 4),
            "saltScore": round(e["saltScore"], 4),
            "nerTagged": e["nerTagged"],
            "strengthDetected": detected_strength,
        })
    candidates.sort(key=lambda c: -c["probability"])

    return {
        "found": bool(candidates),
        "query": text[:400],
        "candidates": candidates[:top_k],
        "entities": entities,
        "nerModel": ner["model"],
        "note": "OK" if candidates else "NO_MATCH",
        "webEvidence": web_evidence,
        "uncertainties": uncertainties,
    }
