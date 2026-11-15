"""
MediVision AI — Phase 4 RETRIEVAL STACK (all free, no paid APIs).

Keyless, always on:
  - RxNorm (NIH)     verify the salt exists
  - openFDA (FDA)    structured label extracts (uses / warnings / side effects)
  - DailyMed (NIH)   human leaflet URL
  - Web fallback     DuckDuckGo HTML -> Wikipedia API -> real sources for
                     medicines the US databases do not carry (Indian brands)

Keyed (optional, free tier): Gemini — composes the EN/TA/HI easy-read card
ONLY from the retrieved evidence (same grounding rules as the app).
"""
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote

import httpx
from dotenv import load_dotenv

from .model_ner import is_insufficient_salt

# Load .env from backend directory and workspace root
load_dotenv()
load_dotenv(Path(__file__).parent.parent / ".env")
load_dotenv(Path(__file__).parent.parent.parent / ".env.local")

HTTP_TIMEOUT = 12.0
GEMINI_TIMEOUT = 30.0
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")


def get_gemini_key() -> str:
    return os.environ.get("GEMINI_API_KEY", "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()


GEMINI_KEY = get_gemini_key()

_UA = {"User-Agent": "MediVisionAI-FYP/1.0 (student project)"}


def _get_json(url: str):
    try:
        r = httpx.get(url, timeout=HTTP_TIMEOUT, headers=_UA, follow_redirects=True)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def summarise(raw, max_chars=320):
    first = raw[0] if isinstance(raw, list) and raw and isinstance(raw[0], str) else None
    if not first:
        return None
    clean = re.sub(r"\s+", " ", first).strip()
    if len(clean) <= max_chars:
        return clean
    cut = clean[:max_chars]
    stop = max(cut.rfind(". "), cut.rfind("; "))
    return cut[: stop + 1] if stop > 80 else cut + "…"


# ---------------- keyless tier ----------------

def rxnorm_verify(us_name: str):
    if not us_name or is_insufficient_salt(us_name):
        return None
    d = _get_json(f"https://rxnav.nlm.nih.gov/REST/rxcui.json?name={quote(us_name)}")
    ids = ((d or {}).get("idGroup") or {}).get("rxnormId") or []
    return ids[0] if ids else None


def openfda_label(us_name: str, expected_form: str | None = None):
    if not us_name or is_insufficient_salt(us_name):
        return None
    us_clean = us_name.strip()
    root = us_clean.lower().split()[0]
    if len(root) < 4 or is_insufficient_salt(root):
        return None

    for search in (
        f'active_ingredient:"{quote(us_clean)}"',
        f'openfda.generic_name:"{quote(us_clean)}"',
        f'openfda.brand_name:"{quote(us_clean)}"',
    ):
        d = _get_json(f"https://api.fda.gov/drug/label.json?search={search}&limit=1")
        results = (d or {}).get("results") or []
        if not results:
            continue
        r = results[0]
        of = r.get("openfda") or {}

        # 1. Reject homeopathic products (Requirement 6)
        if of.get("is_homeopathic") is True:
            continue
        prod_types = [str(pt).lower() for pt in of.get("product_type", [])]
        if any("homeopathic" in pt for pt in prod_types):
            continue
        indications = " ".join(r.get("indications_and_usage") or []).lower()
        if "homeopathic" in indications:
            continue

        # 2. Strict active ingredient agreement check
        generics = [g.lower() for g in of.get("generic_name", [])]
        substances = [s.lower() for s in of.get("substance_name", [])]
        brands = [b.lower() for b in of.get("brand_name", [])]
        actives = [a.lower() for a in r.get("active_ingredient", [])]
        all_name_fields = generics + substances + brands + actives
        if all_name_fields and not any(root in name for name in all_name_fields):
            continue

        # 3. Dosage form agreement check if form specified
        if expected_form:
            ef_low = expected_form.lower()
            dosage_forms = [str(df).lower() for df in of.get("dosage_form", [])]
            routes = [str(rt).lower() for rt in of.get("route", [])]
            if "tablet" in ef_low or "capsule" in ef_low:
                if any("injection" in df for df in dosage_forms) and not any("tablet" in df or "capsule" in df for df in dosage_forms):
                    continue
                if any("injectable" in rt for rt in routes) and not any("oral" in rt for rt in routes):
                    continue

        return {
            "uses": summarise(r.get("indications_and_usage")),
            "warnings": summarise(r.get("warnings")),
            "sideEffects": summarise(r.get("adverse_reactions")) or summarise(r.get("drug_interactions")),
            "brandExamples": (of.get("brand_name") or [None])[0],
            "manufacturer": (of.get("manufacturer_name") or [None])[0],
            "sourceUrl": f"https://api.fda.gov/drug/label.json?search={search}&limit=1",
        }
    return None


def dailymed_url(us_name: str) -> str | None:
    if not us_name or is_insufficient_salt(us_name):
        return None
    d = _get_json(f"https://dailymed.nlm.nih.gov/dailymed/services/v2/spls.json?drug_name={quote(us_name)}")
    items = (d or {}).get("data") or []
    if not items:
        return None
    pref = next((i for i in items if re.search(r"tablet|capsule|oral", i.get("title") or "", re.I)), items[0])
    if pref and pref.get("setid"):
        return f"https://dailymed.nlm.nih.gov/dailymed/drugInfo.cfm?setid={pref['setid']}"
    return None


# ---------------- web fallback tier (free, no key) ----------------

def duckduckgo_search(query: str, n=5):
    """Scrape DDG HTML results (no API key needed). Returns title/url/snippet."""
    try:
        r = httpx.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            timeout=HTTP_TIMEOUT,
            headers=_UA,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return []
        html = r.text
        out = []
        for m in re.finditer(r'class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', html, re.S):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            uq = re.search(r"uddg=([^&]+)", href)
            url = unquote(uq.group(1)) if uq else href
            if url.startswith("//"):
                url = "https:" + url
            out.append({"title": title[:120], "url": url, "snippet": ""})
            if len(out) >= n:
                break
        for i, m in enumerate(re.finditer(r'class="result__snippet"[^>]*>(.*?)</a>', html, re.S)):
            if i < len(out):
                out[i]["snippet"] = re.sub(r"<[^>]+>", "", m.group(1)).strip()[:400]
        return out
    except Exception:
        return []


def wikipedia_search(query: str, n=3):
    """Keyless fallback evidence source (reliable, real URLs)."""
    d = _get_json(
        "https://en.wikipedia.org/w/api.php?action=query&list=search&format=json&srlimit="
        f"{n}&srsearch={quote(query)}"
    )
    out = []
    for hit in ((d or {}).get("query") or {}).get("search") or []:
        out.append(
            {
                "title": hit.get("title", "")[:120],
                "url": f"https://en.wikipedia.org/wiki/{quote(hit.get('title', '').replace(' ', '_'))}",
                "snippet": re.sub(r"<[^>]+>", "", hit.get("snippet", ""))[:400],
            }
        )
    return out


def duckduckgo_lite_search(query: str, n=5):
    """Second DDG endpoint (lite) — the html endpoint is sometimes flaky."""
    try:
        r = httpx.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            timeout=HTTP_TIMEOUT,
            headers=_UA,
            follow_redirects=True,
        )
        if r.status_code != 200:
            return []
        out = []
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*class=.result-link.[^>]*>(.*?)</a>', r.text, re.S):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            uq = re.search(r"uddg=([^&]+)", href)
            url = unquote(uq.group(1)) if uq else href
            if url.startswith("//"):
                url = "https:" + url
            out.append({"title": title[:120], "url": url, "snippet": ""})
            if len(out) >= n:
                break
        return out
    except Exception:
        return []


def web_search(query: str, n=6):
    """Resilient keyless search: DDG html -> DDG lite -> Wikipedia."""
    hits = duckduckgo_search(query, n=n)
    if len(hits) < 3:
        hits += duckduckgo_lite_search(query, n=n)
    if len(hits) < 3:
        hits += wikipedia_search(query, n=3)
    # dedupe by URL
    seen, out = set(), []
    for h in hits:
        if h["url"] not in seen:
            seen.add(h["url"])
            out.append(h)
    return out[:n]


# ---------------- keyed tier: Gemini easy-read card ----------------

CARD_SCHEMA = (
    '{"found": boolean, "salt": string, "en": {"uses": string, "beforeYouTake": string[], '
    '"sideEffects": string, "stopAndGetHelp": string[]}, "ta": {same as en}, '
    '"hi": {same as en}, "caveats": string[]}'
)


def grounding_prompt(salt: str, mapping_basis: str, evidence_json: str) -> str:
    return (
        "You are a pharmacy-label assistant for an app that shows elderly users "
        "medicine safety information in English, Tamil and Hindi.\n"
        "HARD RULES (violating any one is a total failure):\n"
        "1. Use ONLY the EVIDENCE JSON. Never add facts from your own knowledge.\n"
        "2. If the evidence contains no usable label facts, output {\"found\": false} and nothing else.\n"
        "3. Never state any dose amount. Never diagnose. Never tell the user to start or stop a medicine.\n"
        "4. Short, simple sentences (max ~12 words) for elderly readers.\n"
        "5. beforeYouTake and stopAndGetHelp: 2-4 short items each, derived ONLY from the warnings in EVIDENCE.\n"
        '6. Translate the SAME content faithfully into Tamil ("ta") and Hindi ("hi").\n'
        f"7. Output strict JSON exactly in this schema: {CARD_SCHEMA}\n\n"
        f"SALT: {salt}\nMAPPING_BASIS: {mapping_basis} (if brand-hint, add a caveat that the brand-salt mapping needs confirmation)\n"
        f"EVIDENCE: {evidence_json}"
    )


def extract_medicine_details_from_evidence(query: str, hits: list[dict[str, str]]) -> dict[str, Any]:
    """Extract brand, active ingredient, strength, form, and manufacturer from retrieved snippets."""
    combined_texts = [f"{h.get('title', '')}. {h.get('snippet', '')}" for h in hits]
    full_blob = " \n ".join(combined_texts)

    # Strength extraction (e.g., "10 mg", "650mg", "40 mg", "0.5 mg")
    strength = None
    str_m = re.search(r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|g|iu|ml)\b", full_blob, re.I)
    if str_m:
        strength = f"{str_m.group(1)} {str_m.group(2).lower()}"
    else:
        # Check trailing number in brand (e.g. A-Trip 10, Pan 40, Dolo 650)
        num_m = re.search(r"\b[A-Za-z\-]+[\s\-]+(5|10|20|25|40|50|75|100|200|250|400|500|625|650|850|1000)\b", query, re.I)
        if num_m:
            strength = f"{num_m.group(1)} mg"

    # Form extraction
    form = "Tablet"
    form_m = re.search(r"\b(tablet|tablets|capsule|capsules|syrup|injection|gel|drops|suspension|ointment)\b", full_blob, re.I)
    if form_m:
        form = form_m.group(1).capitalize()
        if form.endswith("s") and not form.endswith("ss"):
            form = form[:-1]

    # Manufacturer extraction
    mfr = None
    mfr_m = (
        re.search(r"(?:by|manufactured by|marketed by|from)\s+([A-Z][A-Za-z0-9\s\.\&]+?(?:Ltd|Limited|Pharma|Laboratories|Healthcare|Pvt))", full_blob, re.I) or
        re.search(r"(Marc\s*Cure|Micro\s*Labs|Sun\s*Pharma|Cipla|Torrent|Abbott|Lupin|Dr\.?\s*Reddy|Alkem|Mankind|Zydus|Intas)", full_blob, re.I)
    )
    if mfr_m:
        mfr = mfr_m.group(1).strip()

    # Active ingredient salt extraction from snippets
    salt = None
    salt_m = (
        re.search(r"containing\s+([A-Za-z\s\-]+?(?:Hydrochloride|Hcl|Maleate|Phosphate|Sulfate|Sodium|Potassium|Tartrate)?)(?:,|\.|\bused\b|\ba\b|\btablet|\bfor\b)", full_blob, re.I) or
        re.search(r"(?:active ingredient|composition)[:\s]+([A-Za-z0-9\s\+\(\)\-]+?)(?:,|\.|\bprice\b|\buses\b|\btablet)", full_blob, re.I) or
        re.search(r"\b([A-Za-z]{4,}(?:\s+[A-Za-z]{4,})?)\s+Hydrochloride\b", full_blob, re.I)
    )
    if salt_m:
        candidate_salt = salt_m.group(1).strip()
        if len(candidate_salt) >= 4 and not re.search(r"\b(medicine|tablet|prescription|capsule|drugs?)\b", candidate_salt, re.I):
            salt = candidate_salt.title()

    # Medical uses extraction
    uses = None
    uses_m = re.search(r"(?:used (?:in|for)|prescribed for|treatment of)\s+([^\.\;]{10,140})", full_blob, re.I)
    if uses_m:
        uses = uses_m.group(1).strip()

    return {
        "salt": salt,
        "strength": strength,
        "form": form,
        "manufacturer": mfr,
        "uses": uses,
    }


def gemini_compose(salt: str, mapping_basis: str, evidence: dict):
    """Returns the parsed card dict, or None (no key / geo-block / refusal)."""
    key = get_gemini_key()
    if len(key) <= 10:
        return None
    try:
        r = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            timeout=GEMINI_TIMEOUT,
            json={
                "contents": [{"role": "user", "parts": [{"text": grounding_prompt(salt, mapping_basis, json.dumps(evidence))}]}],
                "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
            },
        )
        if r.status_code != 200:
            return None
        parts = ((r.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or []
        text = "".join(p.get("text", "") for p in parts).strip()
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        parsed = json.loads(text)
        if parsed.get("found") is True and isinstance(parsed.get("en"), dict):
            card = {"en": parsed["en"], "model": GEMINI_MODEL, "caveats": parsed.get("caveats", [])[:4]}
            if isinstance(parsed.get("ta"), dict):
                card["ta"] = parsed["ta"]
            if isinstance(parsed.get("hi"), dict):
                card["hi"] = parsed["hi"]
            return card
    except Exception:
        return None
    return None


def corroborate_product(brand, salt, strength, form):
    """Require a fetched structured product record supporting every identity field.

    Exact comparisons deliberately leave synonyms and incomplete records unverified.
    NDC listing corroboration does not imply FDA approval or suitability for a patient.
    """
    from datetime import datetime, timezone

    if not all((brand, salt, strength, form)):
        return []
    url = (
        "https://api.fda.gov/drug/ndc.json?search="
        + quote('brand_name.exact:"' + brand + '"', safe="")
        + "&limit=10"
    )
    data = _get_json(url)
    if not isinstance(data, dict):
        return []

    def normalized(value):
        return re.sub(r"\s+", " ", str(value or "").strip()).casefold()

    expected = {
        "brand": brand, "salt": salt, "strength": strength, "form": form,
    }
    records = data.get("results")
    if not isinstance(records, list):
        return []
    for record in records:
        if not isinstance(record, dict):
            continue
        ingredients = record.get("active_ingredients") or []
        if not isinstance(ingredients, list) or len(ingredients) != 1 or not isinstance(ingredients[0], dict) or not record.get("product_ndc"):
            continue
        actual = {
            "brand": record.get("brand_name"),
            "salt": ingredients[0].get("name"),
            "strength": re.sub(r"\s*/\s*1\s*$", "", str(ingredients[0].get("strength") or "")),
            "form": record.get("dosage_form"),
        }
        if any(normalized(actual[k]) != normalized(v) for k, v in expected.items()):
            continue
        return [{
            "url": url,
            "sourceType": "government",
            "recordId": record["product_ndc"],
            "retrievedAt": datetime.now(timezone.utc).isoformat(),
            "supportedFields": actual,
            "validation": "exact-product-fields",
        }]
    return []
