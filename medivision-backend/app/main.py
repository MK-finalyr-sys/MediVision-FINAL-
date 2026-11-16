"""
MediVision AI — Phase 4 BACKEND (FastAPI) — FULLY INTEGRATED VERSION.

Endpoints:
  GET  /health       -> status of NER, Gemini, integrations layer
  POST /extract      -> { text }                       -> NER entities only
  POST /identify     -> { ocrText, imageB64? }         -> full sourced result
  POST /candidates   -> { ocrText, imageB64?, topK? }  -> probability-ranked candidates
                                                         (uses pill_classifier when imageB64 provided)
  POST /recommend    -> { salt, brand?, patient }      -> patient-aware safety warnings
                                                         (uses DDInter + OpenFDA + safety.py rules)
  POST /chat         -> { message, language, ctx?, history? }
                                                       -> multilingual chatbot
                                                         (Meditron > Gemini > rule-based)
  POST /transcribe   -> { audioB64, language }         -> Tamil/Hindi STT (AI4Bharat conformer)
  POST /pricing      -> { salt, strength? }            -> PMBJP generic price lookup

Run:
  uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional

from . import pipeline, retriever, candidates, safety, chatbot, vision_ocr
from .model_ner import predict_entities, status as ner_status
from .integrations import status_map as integration_status_map, integration_summary
from .integrations import pill_classifier, ddinter, openfda_interactions
from .integrations import brand_salt_lookup, indian_pricing
from .integrations import indic_stt, meditron_chat

app = FastAPI(title="MediVision AI — Phase 4 backend (integrated)", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------------- request models ----------------

class ExtractIn(BaseModel):
    text: str


class IdentifyIn(BaseModel):
    ocrText: str
    imageB64: Optional[str] = None


class CandidatesIn(BaseModel):
    ocrText: str
    imageB64: Optional[str] = None
    topK: Optional[int] = Field(default=5, ge=1, le=10)


class PatientIn(BaseModel):
    age: Optional[int] = None
    conditions: list[str] = []
    currentMeds: list[str] = []
    allergens: list[str] = []


class RecommendIn(BaseModel):
    salt: str
    brand: Optional[str] = None
    patient: PatientIn = PatientIn()


class ChatIn(BaseModel):
    message: str
    language: str = "en"
    medicineContext: Optional[dict] = None
    history: list[dict] = []


class TranscribeIn(BaseModel):
    audioB64: str
    language: str = "ta"


class PricingIn(BaseModel):
    salt: str
    strength: Optional[str] = None


# ---------------- endpoints ----------------

@app.get("/health")
def health():
    gemini_check = chatbot.check_gemini_operational()
    gemini_on = bool(gemini_check.get("operational", False))
    return {
        "status": "ok",
        "ner": ner_status(),
        "gemini": gemini_on,
        "geminiModel": retriever.GEMINI_MODEL if gemini_on else None,
        "geminiStatus": gemini_check.get("status", "unknown"),
        "geminiMessage": gemini_check.get("message", ""),
        "integrations": integration_status_map(),
        "integrationSummary": integration_summary(),
        "features": {
            "identify": True,
            "candidates": True,
            "recommend": True,
            "chat": True,
            "transcribe": indic_stt.available(),
            "pricing": indian_pricing.available(),
            "chatLLM": "meditron" if meditron_chat.available() else ("gemini" if gemini_on else "rule-based"),
        },
        "version": "3.0.0",
    }


@app.post("/extract")
def extract(body: ExtractIn):
    return predict_entities(pipeline.normalise(body.text))


@app.post("/identify")
def identify(body: IdentifyIn):
    # A photograph is optional. Keep browser OCR as the fallback when remote
    # visual reading is unavailable, disabled, rate-limited, or ambiguous.
    # Never identify from pill color/shape or turn model transcription into
    # independent online proof.
    visual_text = vision_ocr.read_printed_text(body.imageB64)
    result = pipeline.identify(visual_text or body.ocrText)
    if visual_text:
        result["visionAssisted"] = True
        result["visionPrintedText"] = visual_text[:500]
        result["originalOcrText"] = body.ocrText[:500]
    else:
        result["visionAssisted"] = False
    return result


@app.post("/candidates")
def candidates_endpoint(body: CandidatesIn):
    """Feature 1 — damaged-strip probability analysis.

    Returns ranked candidate salts with probabilities. When imageB64 is also
    supplied AND the pill_classifier integration is available, the image's
    top-1 salt is merged into the candidate list as an extra evidence signal.
    """
    base = candidates.ranked_candidates(body.ocrText, top_k=body.topK)
    if body.imageB64 and pill_classifier.available():
        try:
            import base64
            img_bytes = base64.b64decode(body.imageB64.split(",", 1)[-1] if "," in body.imageB64 else body.imageB64)
            vision_top = pill_classifier.classify(img_bytes, top_k=3)
            if vision_top:
                base["visionEvidence"] = vision_top
                # If the top vision prediction maps to a known salt, boost it.
                top_vision_salt = vision_top[0].get("salt")
                if top_vision_salt:
                    for cand in base.get("candidates", []):
                        if cand["salt"].lower() == top_vision_salt.lower():
                            cand["probability"] = round(min(0.95, cand["probability"] + 0.20), 4)
                            cand["basis"] = (cand.get("basis", "") + "+vision").strip("+")
                            cand["visionMatched"] = True
                            break
                    else:
                        # Vision found a salt that OCR didn't — add it as a candidate.
                        base.setdefault("candidates", []).append({
                            "salt": top_vision_salt,
                            "usName": pipeline.SALT_TO_US.get(top_vision_salt, top_vision_salt),
                            "probability": round(vision_top[0]["probability"], 4),
                            "basis": "vision-only",
                            "matchedToken": None,
                            "matchedBrand": None,
                            "brandScore": 0.0,
                            "saltScore": float(vision_top[0]["probability"]),
                            "nerTagged": False,
                            "strengthDetected": vision_top[0].get("strength"),
                            "visionMatched": True,
                        })
                # Renormalise probabilities so they sum to ~1.0 again
                total = sum(c["probability"] for c in base.get("candidates", []))
                if total > 0:
                    for c in base["candidates"]:
                        c["probability"] = round(c["probability"] / total, 4)
                base["candidates"].sort(key=lambda c: -c["probability"])
        except Exception as e:
            base["visionError"] = str(e)[:120]
    return base


@app.post("/recommend")
def recommend_endpoint(body: RecommendIn):
    """Feature 2 — patient-aware safety recommendation.

    Layered evidence (in priority order):
      1. Rule-based safety.py (always on, keyless) — duplicate therapy, allergens, age, conditions
      2. DDInter SQLite lookup (when built) — thousands of real interaction pairs
      3. openFDA drug_interactions fallback — for pairs DDInter doesn't have

    All layers contribute warnings; CRITICAL > WARN > INFO ordering preserved.
    """
    payload = body.model_dump()
    base = safety.recommend(payload)   # rule-based layer (always on)

    # --- DDInter + OpenFDA layer (adds drug-pair interactions) ---
    patient_salts = set(base.get("patient", {}).get("mappedSalts", []))
    for m in (body.patient.currentMeds or []):
        if m and m.strip():
            patient_salts.add(m.strip())
    scanned_salt = body.salt
    if scanned_salt and patient_salts:
        extra_warnings = []
        for other_salt in patient_salts:
            if other_salt == scanned_salt:
                continue
            # Try DDInter first
            pair = None
            if ddinter.available():
                try:
                    pair = ddinter.check_pair(scanned_salt, other_salt)
                except Exception:
                    pair = None
            # Fallback to OpenFDA label text scan
            if not pair:
                try:
                    pair = openfda_interactions.check_pair(scanned_salt, other_salt)
                except Exception:
                    pair = None
            if pair:
                sev = "WARN"
                level = (pair.get("level") or "").lower()
                if "major" in level or "severe" in level or "contraind" in level:
                    sev = "CRITICAL"
                elif "minor" in level or "low" in level:
                    sev = "INFO"
                extra_warnings.append({
                    "severity": sev,
                    "title": f"Interaction with {other_salt}",
                    "detail": pair.get("effect") or pair.get("mechanism") or f"Interaction reported between {scanned_salt} and {other_salt}.",
                    "action": "Consult your doctor before combining these medicines.",
                    "source": pair.get("url") or pair.get("source") or "https://www.fda.gov/drugs/drug-interactions-labeling",
                    "kind": "drug-interaction-db",
                    "conflictingSalts": [other_salt],
                    "database": pair.get("source"),
                })
        # Merge extra warnings into base, dedup by (kind, conflictingSalts)
        existing_keys = {(w.get("kind"), tuple(sorted(w.get("conflictingSalts", [])))) for w in base.get("warnings", [])}
        for w in extra_warnings:
            key = (w.get("kind"), tuple(sorted(w.get("conflictingSalts", []))))
            if key not in existing_keys:
                base.setdefault("warnings", []).append(w)
                existing_keys.add(key)
        # Re-sort by severity
        sev_rank = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
        base["warnings"].sort(key=lambda w: sev_rank.get(w["severity"], 9))
        base["shouldConsultDoctor"] = any(w["severity"] == "CRITICAL" for w in base["warnings"])

    # --- PMBJP pricing layer (INFO-level: cheapest generic alternative) ---
    if indian_pricing.available() and body.salt:
        try:
            generic = indian_pricing.lookup_generic_price(body.salt, body.strength)
            if generic:
                base.setdefault("warnings", []).append({
                    "severity": "INFO",
                    "title": "Low-cost generic alternative available",
                    "detail": f"A Janaushadhi (government-subsidised) generic for {body.salt} is available: {generic['brand']} — MRP {generic['mrp']}.",
                    "action": "Ask your pharmacist for the Janaushadhi equivalent to save on cost.",
                    "source": "https://janaushadhi.gov.in/",
                    "kind": "pricing",
                })
        except Exception:
            pass

    return base


@app.post("/chat")
def chat_endpoint(body: ChatIn):
    """Feature 3 — multilingual chatbot.

    Layered LLM priority:
      1. Meditron (offline, when MV_ENABLE_MEDITRON=1 and Ollama is running)
      2. Gemini (when GEMINI_API_KEY is set)
      3. Rule-based responder (always available, keyless, multilingual)
    """
    payload = body.model_dump()
    # Try Meditron first (offline preference)
    if meditron_chat.available():
        out = meditron_chat.chat(payload["message"], payload["language"],
                                 payload.get("medicineContext") or {}, payload.get("history") or [])
        if out and out.get("reply"):
            out["ok"] = True
            return out
    # Fall through to the existing chatbot.chat (which tries Gemini, then rule-based)
    return chatbot.chat(payload)


@app.post("/transcribe")
def transcribe(body: TranscribeIn):
    """Feature 3 (voice) — Tamil/Hindi speech-to-text via AI4Bharat conformer.

    The frontend captures audio via MediaRecorder, base64-encodes it, and POSTs
    here. The returned text is then fed to /chat as the user's message.
    """
    if not indic_stt.available():
        return {
            "ok": False,
            "text": "",
            "reason": "Indic STT not enabled. Run: python -m integrations.setup_integrations download-indic-stt, then set MV_ENABLE_INDIC_STT=1.",
            "language": body.language,
            "model": None,
        }
    return indic_stt.transcribe_b64(body.audioB64, body.language)


@app.post("/pricing")
def pricing(body: PricingIn):
    """PMBJP generic pricing lookup for a scanned salt."""
    if not indian_pricing.available():
        return {"ok": False, "reason": "Pricing catalog not loaded."}
    generic = indian_pricing.lookup_generic_price(body.salt, body.strength)
    all_generics = indian_pricing.lookup_all_generics(body.salt, limit=5)
    return {
        "ok": bool(generic),
        "salt": body.salt,
        "best": generic,
        "alternatives": all_generics,
        "source": "Pradhan Mantri Bhartiya Janaushadhi Pariyojana (PMBJP)",
    }


@app.get("/brand-search")
def brand_search(q: str, limit: int = 10):
    """Quick brand-name search across the 323,711-brand Indian index."""
    if not brand_salt_lookup.available():
        return {"ok": False, "results": [], "reason": "Brand index not loaded."}
    return {"ok": True, "query": q, "results": brand_salt_lookup.search_brands(q, limit=limit)}
