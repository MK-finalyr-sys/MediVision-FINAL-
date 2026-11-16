"""Optional multimodal second OCR pass for medicine packaging.

This does NOT identify a medicine from appearance or verify an ingredient.
Gemini is asked to transcribe only visibly printed text. The existing pipeline
still performs candidate lookup and evidence validation separately.

To opt in, set MV_ENABLE_GEMINI_VISION=1 and configure a valid backend key.
Never log an image, API key, or transcript. Image bytes are not stored here.
The caller must disclose the external image processing to the user.
"""
from __future__ import annotations

import base64
import json
import os
import re

import httpx

MAX_IMAGE_BYTES = 2_000_000
SAFE_MIMES = {"image/jpeg", "image/png", "image/webp"}


def _decode_data_uri(image: str) -> tuple[str, str] | None:
    match = re.fullmatch(
        r"data:(image/(?:jpeg|png|webp));base64,([A-Za-z0-9+/=]+)",
        (image or "").strip(),
    )
    if not match or len(match.group(2)) > (MAX_IMAGE_BYTES * 4 // 3) + 16:
        return None
    try:
        data = base64.b64decode(match.group(2), validate=True)
    except (ValueError, TypeError):
        return None
    if not data or len(data) > MAX_IMAGE_BYTES:
        return None
    if match.group(1) not in SAFE_MIMES:
        return None
    return match.group(1), match.group(2)


def read_printed_text(image_b64: str | None) -> str | None:
    """Read packaging, not infer identity. Requires explicit backend opt-in."""
    if os.environ.get("MV_ENABLE_GEMINI_VISION", "0") != "1" or not image_b64:
        return None
    from .retriever import get_gemini_key, GEMINI_MODEL
    key = get_gemini_key()
    if not key or len(key) < 12:
        return None
    parsed = _decode_data_uri(image_b64)
    if not parsed:
        return None
    mime, data = parsed
    try:
        response = httpx.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent",
            headers={"Content-Type": "application/json", "x-goog-api-key": key},
            json={
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"text": (
                            "Transcribe ONLY clearly visible, printed text on this Indian medicine package. "
                            "Do not guess missing letters, infer drugs from color or appearance, "
                            "invent brands, strengths, ingredients or give health advice. "
                            'Return JSON of form {"printedText":"..."}. '
                            "If unreadable, return an empty printedText. Preserve line breaks."
                        )},
                        {"inline_data": {"mime_type": mime, "data": data}},
                    ],
                }],
                "generationConfig": {
                    "temperature": 0,
                    "responseMimeType": "application/json",
                },
            },
            timeout=22,
        )
        if response.status_code != 200:
            return None
        parts = (((response.json().get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        raw = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
        obj = json.loads(re.sub(r"^\s*\x60\x60\x60(?:json)?|\x60\x60\x60\s*$", "", raw).strip())
        txt = obj.get("printedText") if isinstance(obj, dict) else None
        return txt.strip()[:1200] if isinstance(txt, str) and len(txt.strip()) >= 4 else None
    except (httpx.HTTPError, ValueError, TypeError, KeyError, IndexError):
        return None
