"""
MediVision AI — Phase 4 PIPELINE (the brain).
OCR text in -> fully sourced medicine information out.

  1. normalise the OCR text
  2. NER model extracts BRAND / SALT / STRENGTH / FORM / MFR
  3. map to the canonical salt (INN) and US name (USAN)
  4. RxNorm verify + openFDA label + DailyMed leaflet  (keyless)
  5. no US label? -> live web search fallback (DDG/Wikipedia, keyless)
  6. Gemini composes the EN/TA/HI easy-read card from the evidence (optional)

Response JSON mirrors the app's OnlineResult contract, so the existing
frontend panel renders it without changes.
"""
import json
import re
from typing import Any
from urllib.parse import quote

from . import retriever
from .data import SALT_TO_US
from .model_ner import predict_entities, is_insufficient_salt
from .identity_guard import ingredient_roots, visible_ingredients, credible_brand_in_ocr
from .search_candidate import discover as discover_search_candidate
from .integrations import brand_salt_lookup, indian_pricing, ddinter

SALT_TOKEN = re.compile(r"[a-z]{5,}")  # for the web-search relevance gate

# A source only counts as evidence if it is also about medicine. Without this,
# gibberish strip text like "blorp" matches random YouTube channels that
# genuinely contain that word — real medical pages mention drugs/doses/uses.
MEDICAL_CONTEXT = re.compile(
    r"medicine|drugs?|tablets?|capsules?|dos(e|age)|side.?effects?|pharma(cy|ceutical)?|"
    r"syrup|injection|prescription|treatment|patient|clinical",
    re.I,
)


def normalise(text: str) -> str:
    """Undo common OCR damage before matching (0->O inside words, 1->I, |->I)."""
    t = re.sub(r"\s+", " ", text).strip()
    t = re.sub(r"(\w)[0](?=\w)", lambda m: m.group(1) + "O", t)  # D0lo -> DOlo
    t = re.sub(r"(\w)1(?=\w)", lambda m: m.group(1) + "I", t)    # Do1o -> DoIo
    return t.replace("|", "I").replace("•", " ")


def _relevance_ok(query: str, hits, require_medical: bool = False) -> bool:
    """Anti-hallucination gate: >=1 source must contain a >=5-letter strip token;
    for the no-salt web path the source must ALSO be medical in nature."""
    tokens = SALT_TOKEN.findall(query.lower())
    if not tokens:
        return False
    for h in hits:
        hay = f"{h.get('title','')} {h.get('url','')} {h.get('snippet','')}".lower()
        if not any(t in hay for t in tokens):
            continue
        if not require_medical or MEDICAL_CONTEXT.search(hay):
            return True
    return False


def identify(ocr_text: str) -> dict:
    text = normalise(ocr_text)
    ner = predict_entities(text)
    entities = ner["entities"]

    # Detect standalone strength (e.g., "10 mg", "650 mg", "40 mg")
    detected_strength = None
    str_m = re.search(r"\b(\d+(?:\.\d+)?)\s*(mg|mcg|g|iu|ml)\b", text, re.I)
    if str_m:
        detected_strength = f"{str_m.group(1)} {str_m.group(2).lower()}"
    else:
        raw_s = ner.get("strength")
        if not raw_s:
            num_m = re.search(r"\b(5|10|20|25|40|50|75|100|200|250|400|500|625|650|850|1000)\b", text)
            if num_m:
                raw_s = num_m.group(1)
        if raw_s:
            clean_s = raw_s.strip()
            if clean_s.isdigit() and int(clean_s) in (5, 10, 20, 25, 40, 50, 75, 100, 200, 250, 400, 500, 625, 650, 850, 1000):
                detected_strength = f"{clean_s} mg"
            else:
                detected_strength = clean_s

    # Detect dosage form
    detected_form = "Tablet"
    form_m = re.search(r"\b(tablet|tablets|capsule|capsules|syrup|injection|gel|drops|suspension|ointment)\b", text, re.I)
    if form_m:
        detected_form = form_m.group(1).capitalize()
        if detected_form.endswith("s") and not detected_form.endswith("ss"):
            detected_form = detected_form[:-1]

    brand_candidate = None
    salt = None
    canonical_salt = None
    strength = detected_strength
    form = detected_form
    manufacturer = None
    official_url = None
    basis = "none"
    web_evidence = []
    sources = []

    observed_ingredients = visible_ingredients(text)

    # Priority 1: Check recognizable Indian product brands in OCR text FIRST
    # (Exact brand names e.g. A-TRIP-10, Dolo 650, Pan 40 take priority over raw CRF token tags)
    if brand_salt_lookup.available():
        clean_text = re.sub(r"[^A-Za-z0-9\s.\-]", " ", text)
        words = clean_text.split()
        candidate_phrases = []
        # Hyphenated tokens first (e.g. A-TRIP-10, PAN-D, GLYCOMET-GP)
        for tok in words:
            if "-" in tok:
                candidate_phrases.append(tok)
        # N-grams from 3 words down to 1
        for n in range(3, 0, -1):
            for i in range(len(words) - n + 1):
                candidate_phrases.append(" ".join(words[i:i + n]))

        for phrase in candidate_phrases:
            phrase_str = phrase.strip()
            if len(phrase_str) < 3 or is_insufficient_salt(phrase_str):
                continue
            details = brand_salt_lookup.lookup_brand_details_exact(phrase_str)
            if (details and credible_brand_in_ocr(phrase_str, text, bool(observed_ingredients))
                    and not is_insufficient_salt(details.get("canonicalSalt") or details.get("salt"))):
                brand_candidate = details.get("brand") or phrase_str
                salt = details.get("salt")
                canonical_salt = details.get("canonicalSalt") or salt
                if details.get("strength"):
                    strength = details["strength"]
                if details.get("form"):
                    form = details["form"]
                if details.get("manufacturer"):
                    manufacturer = details["manufacturer"]
                if details.get("url"):
                    official_url = details["url"]
                basis = "indian-brand-index"
                break

    # Priority 2: If no product brand hit, check NER entities
    if not salt:
        ner_salt = ner.get("salt")
        if ner_salt and not is_insufficient_salt(ner_salt):
            salt = ner_salt
            canonical_salt = ner_salt
            brand_candidate = ner.get("brand")
            basis = ner.get("mappingBasis", "salt-in-text")
        elif ner.get("brand") and not is_insufficient_salt(ner["brand"]):
            b_details = brand_salt_lookup.lookup_brand_details_exact(ner["brand"])
            if b_details and not is_insufficient_salt(b_details.get("canonicalSalt") or b_details.get("salt")):
                brand_candidate = b_details.get("brand") or ner["brand"]
                salt = b_details.get("salt")
                canonical_salt = b_details.get("canonicalSalt") or salt
                if b_details.get("strength"):
                    strength = b_details["strength"]
                if b_details.get("form"):
                    form = b_details["form"]
                if b_details.get("manufacturer"):
                    manufacturer = b_details["manufacturer"]
                if b_details.get("url"):
                    official_url = b_details["url"]
                basis = "brand-hint"

    # Full printed ingredient names take priority over an unsupported CRF guess.
    # This is not fuzzy reconstruction: exact ingredient text must be visible.
    observed_roots = frozenset().union(
        *(ingredient_roots(name) for name in observed_ingredients)
    )
    mapped_roots = ingredient_roots(salt)
    if observed_roots and observed_roots != mapped_roots:
        if len(observed_roots) == 1 and len(observed_ingredients) == 1:
            # The catalog/NER mapped to a DIFFERENT medicine despite legible
            # ingredient text. Show the printed generic as a candidate instead;
            # never retain an unrelated brand, manufacturer or reference URL.
            salt = observed_ingredients[0]
            canonical_salt = observed_ingredients[0]
            brand_candidate = None
            manufacturer = None
            official_url = None
            basis = "explicit-ingredient-in-ocr"
        else:
            # Multiple clearly printed ingredients cannot safely be reduced to
            # one guessed salt. Ask for review instead of suggesting the wrong
            # product or inventing an incomplete combination formulation.
            return {
                "found": False, "query": text[:400], "candidates": [],
                "salt": None, "brand": None, "strength": detected_strength,
                "form": detected_form if form_m else None,
                "observedIngredients": observed_ingredients,
                "mappingBasis": "multiple-ingredient-conflict",
                "entities": entities, "nerModel": ner["model"],
                "sources": [], "webEvidence": [],
                "note": "MULTIPLE_INGREDIENTS_REQUIRE_REVIEW",
                "verificationStatus": "none",
            }
    elif basis in ("salt-in-text", "brand-hint") and not observed_roots:
        # A model-predicted name or a lookup from an arbitrary NER fragment
        # is NOT evidence of the actual medicine on the package.
        # Keep the input available for review / online discovery instead.
        salt = None
        canonical_salt = None
        brand_candidate = None
        manufacturer = None
        official_url = None
        basis = "none"

    # Keep explicit package observations separate from catalog proposals.
    proposed_identity = {
        "brand": brand_candidate, "salt": salt, "strength": strength, "form": form,
    }
    observed_identity = {
        "strength": detected_strength if str_m else None,
        "form": detected_form if form_m else None,
    }
    conflicts = []
    for field, observed in observed_identity.items():
        proposed = proposed_identity[field]
        if observed and proposed and observed.casefold() != proposed.casefold():
            conflicts.append({"field": field, "observed": observed, "proposed": proposed})
    strength = observed_identity["strength"] or strength
    form = observed_identity["form"] or form

    # Priority 3: Online retrieval grounding
    # Search for full brand and strength, never isolated chemical suffixes like "Hydrochloride" alone
    search_query = None
    if brand_candidate:
        search_query = f"{brand_candidate} {strength or ''} medicine tablet uses composition"
    elif salt:
        search_query = f"{salt} {strength or ''} medicine tablet uses composition"
    else:
        # Filter out isolated chemical suffixes and stop words
        medical_words = [
            w for w in re.findall(r"[A-Za-z0-9\-]+", text)
            if len(w) >= 3 and not is_insufficient_salt(w) and w.lower() not in (
                "tablet", "tablets", "capsule", "capsules", "strip", "dose", "oral"
            )
        ]
        if medical_words:
            search_query = f"{' '.join(medical_words)} medicine tablet uses composition"

    if search_query:
        hits = retriever.web_search(search_query, n=6)
        if hits and _relevance_ok(text, hits, require_medical=True):
            web_evidence = [{"title": h["title"], "url": h["url"], "snippet": h["snippet"]} for h in hits[:5]]
            # Search snippets are discovery references, never product identity proof.

    # If the local brand/NER path has no safe answer, use a single coherent
    # search result to propose an UNVERIFIED candidate; do not synthesize
    # ingredient/strength across different snippets or mark as verified.
    if not salt and web_evidence:
        found_online = discover_search_candidate(text, web_evidence)
        if found_online:
            salt = found_online["salt"]
            canonical_salt = salt
            brand_candidate = found_online["brand"]
            strength = found_online.get("strength") or detected_strength
            form = detected_form
            basis = "online-search-candidate"
            proposed_identity = {
                "brand": brand_candidate, "salt": salt,
                "strength": strength, "form": form,
            }

    # Priority 4: Strict patient-safety gate:
    # Isolated chemical suffixes like "hydrochloride" are INSUFFICIENT to establish identity.
    # Return NO_MATCH rather than fabricated medicine or false verified identity.
    if not salt or is_insufficient_salt(salt) or is_insufficient_salt(canonical_salt):
        return {
            "found": False,
            "query": text[:400],
            "candidates": [],
            "salt": None,
            "brand": None,
            "strength": None,
            "form": None,
            "mappingBasis": "none",
            "entities": entities,
            "nerModel": ner["model"],
            "sources": [],
            "webEvidence": [],
            "note": "NO_MATCH",
            "verificationStatus": "none",
        }

    # Canonicalize salt for US lookup
    canonical_salt = canonical_salt or salt
    us_name = SALT_TO_US.get(canonical_salt, canonical_salt)
    rxnorm_id = retriever.rxnorm_verify(us_name)
    label = retriever.openfda_label(us_name, expected_form=form)
    leaflet = retriever.dailymed_url(us_name)

    # Genuine provenance sources (NO manufactured or fictitious URLs)
    if official_url:
        sources.append({
            "title": f"{manufacturer or brand_candidate} — Official Product Reference",
            "url": official_url,
            "sourceType": "manufacturer",
        })
    if rxnorm_id:
        sources.append({
            "title": f"RxNorm (U.S. NIH) — {us_name} [RxCUI: {rxnorm_id}]",
            "url": f"https://rxnav.nlm.nih.gov/REST/rxcui.json?name={quote(us_name)}",
            "sourceType": "government",
        })
    if label and label.get("sourceUrl"):
        sources.append({
            "title": f"openFDA Drug Label (U.S. FDA) — {us_name}",
            "url": label["sourceUrl"],
            "sourceType": "government",
        })
    if leaflet:
        sources.append({
            "title": f"DailyMed Patient Leaflet — {us_name}",
            "url": leaflet,
            "sourceType": "label",
        })
    for w in web_evidence:
        sources.append({
            "title": w["title"],
            "url": w["url"],
            "sourceType": "medical-reference",
        })

    # Evidence details
    evidence_dict: dict[str, Any] = {}
    if label:
        evidence_dict = {
            "uses": label.get("uses") or "",
            "warnings": label.get("warnings") or "",
            "sideEffects": label.get("sideEffects") or "",
            "manufacturer": label.get("manufacturer") or manufacturer,
        }
        if not manufacturer and label.get("manufacturer"):
            manufacturer = label["manufacturer"]
    else:
        snippets = [w["snippet"] for w in web_evidence if w.get("snippet")]
        evidence_dict = {
            "uses": f"{canonical_salt} is commonly prescribed for: " + (snippets[0][:140] if snippets else "therapeutic use as directed by a physician."),
            "warnings": "Take only as prescribed by your doctor. Check packaging for precautions.",
            "sideEffects": "Common side effects may include mild drowsiness, dry mouth, or headache. Consult a doctor if persistent.",
            "webSnippets": snippets[:4],
        }

    # PMBJP generic pricing lookup (enforcing exact root, strength and dosage form)
    pmjp_pricing = None
    if indian_pricing.available() and not conflicts:
        pmjp_pricing = indian_pricing.lookup_generic_price(canonical_salt, strength, form)
        if pmjp_pricing:
            sources.append({
                "title": f"PMBJP Jan Aushadhi — {pmjp_pricing.get('brand', canonical_salt)}",
                "url": "https://janaushadhi.gov.in/",
                "sourceType": "government",
            })

    # Gemini Easy-Read Card (Multilingual: EN, TA, HI)
    card = retriever.gemini_compose(canonical_salt, basis, evidence_dict)
    if not card:
        card = {
            "en": {
                "uses": evidence_dict.get("uses") or f"{canonical_salt} is used according to your doctor's prescription.",
                "beforeYouTake": [
                    "Check the expiry date and packaging before taking.",
                    "Tell your doctor if you have allergies, liver, or kidney problems.",
                    "Do not take with other medicines without asking your pharmacist.",
                ],
                "sideEffects": evidence_dict.get("sideEffects") or "Consult your doctor if you experience unusual side effects.",
                "stopAndGetHelp": [
                    "Signs of severe allergy: facial swelling, rash, or breathing trouble.",
                    "Severe dizziness, fainting, or chest discomfort.",
                ],
            },
            "ta": {
                "uses": f"இந்த {canonical_salt} மருந்து உங்கள் மருத்துவரின் பரிந்துரையின்படி பயன்படுத்தப்படுகிறது.",
                "beforeYouTake": [
                    "மருந்தை எடுக்கும் முன் காலாவதி தேதியை சரிபார்க்கவும்.",
                    "ஒவ்வாமை அல்லது பிற நோய்கள் இருந்தால் மருத்துவரிடம் தெரிவிக்கவும்.",
                    "மருந்தாளுனரிடம் கேட்காமல் மற்ற மருந்துகளுடன் சேர்த்து எடுக்க வேண்டாம்.",
                ],
                "sideEffects": "அசாதாரண பக்க விளைவுகள் ஏற்பட்டால் மருத்துவரிடம் ஆலோசனை பெறவும்.",
                "stopAndGetHelp": [
                    "தீவிர ஒவ்வாமை: முக வீக்கம், அரிப்பு அல்லது மூச்சுத் திணறல்.",
                    "மயக்கம் அல்லது தீவிர உடல் அசௌகரியம் ஏற்பட்டால் உடனே மருத்துவ உதவி பெறவும்.",
                ],
            },
            "hi": {
                "uses": f"यह {canonical_salt} दवा आपके डॉक्टर के परामर्श के अनुसार उपयोग की जाती है।",
                "beforeYouTake": [
                    "दवा लेने से पहले समाप्ति तिथि (expiry date) अवश्य जांचें।",
                    "यदि एलर्जी या अन्य बीमारियां हैं तो डॉक्टर को बताएं।",
                    "बिना डॉक्टर या फार्मासिस्ट की सलाह के अन्य दवाओं के साथ न लें।",
                ],
                "sideEffects": "यदि कोई असामान्य दुष्प्रभाव दिखे तो तुरंत डॉक्टर से संपर्क करें।",
                "stopAndGetHelp": [
                    "गंभीर एलर्जी के लक्षण: चेहरे पर सूजन, लाल चकत्ते या सांस लेने में परेशानी।",
                    "अत्यधिक चक्कर या सीने में तकलीफ होने पर आपातकालीन मदद लें।",
                ],
            },
            "model": "grounded-evidence-fallback",
            "caveats": ["General guidance only; verify product identity and medical details with a pharmacist. Unverified sources must not be treated as manufacturer-confirmed."],
        }

    identity_evidence = retriever.corroborate_product(
        brand_candidate, salt, strength, form
    ) if not conflicts else []
    for evidence in identity_evidence:
        sources.append({
            "title": "openFDA NDC product identity",
            "url": evidence["url"],
            "sourceType": evidence["sourceType"],
        })
    has_verified_evidence = bool(identity_evidence)
    verification_status = (
        "conflicting-identification" if conflicts else
        "verified-online" if has_verified_evidence else "candidate-needs-confirmation"
    )

    return {
        "found": True,
        "proposedIdentity": proposed_identity,
        "observedIdentity": observed_identity,
        "conflicts": conflicts,
        "requiresManualReview": bool(conflicts),
        "identityEvidence": identity_evidence,
        "query": text[:400],
        "candidates": [canonical_salt],
        "salt": salt,
        "canonicalSalt": canonical_salt,
        "brand": brand_candidate or (label or {}).get("brandExamples") or salt,
        "usName": us_name,
        "strength": strength or "as printed on packet",
        "form": form,
        "rxnormId": rxnorm_id,
        "brandExamples": brand_candidate or (label or {}).get("brandExamples"),
        "manufacturer": manufacturer,
        "mappingBasis": basis,
        "label": {
            "uses": evidence_dict.get("uses") or "",
            "warnings": evidence_dict.get("warnings") or "",
            "sideEffects": evidence_dict.get("sideEffects") or "",
        },
        "genericPricing": pmjp_pricing,
        "card": card,
        "entities": entities,
        "nerModel": ner["model"],
        "sources": sources,
        "webEvidence": web_evidence,
        "verificationStatus": verification_status,
        "note": "IDENTITY_CONFLICT" if conflicts else "OK" if has_verified_evidence else "NO_LABEL",
    }
