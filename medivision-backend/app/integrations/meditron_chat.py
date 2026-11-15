"""
Meditron-7B chat adapter — offline medical LLM alternative to Gemini.

Model: epfllm/meditron (Meditron-7B, Llama-2 fine-tuned on 48B tokens of
PubMed + clinical guidelines, Apache 2.0 code / Llama 2 license model).

This adapter does NOT bundle the model (it is ~13 GB). Instead it expects the
user to run Meditron locally via Ollama:

    ollama pull meditron:7b
    ollama serve   # listens on http://localhost:11434

To enable in MediVision:
  1) Install Ollama: https://ollama.com/download
  2) ollama pull meditron:7b  (or use any other medical LLM tag you prefer)
  3) Set environment variable MV_ENABLE_MEDITRON=1
  4) Optionally set MV_OLLAMA_URL=http://localhost:11434 and MV_OLLAMA_MODEL=meditron:7b

When enabled, /chat tries Meditron FIRST; on any failure falls back to Gemini
(if a key is set) or the rule-based responder. So enabling Meditron never
breaks the chat endpoint.

This is the offline / privacy-preserving alternative to Gemini — useful when:
  - The viva demo is in a room with no internet
  - The user does not want to send medical questions to Google
  - The FYP report needs an "offline LLM" comparison section
"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

OLLAMA_URL = os.environ.get("MV_OLLAMA_URL", "http://localhost:11434").rstrip("/")
OLLAMA_MODEL = os.environ.get("MV_OLLAMA_MODEL", "meditron:7b")
HTTP_TIMEOUT = 60.0   # local LLMs are slow on CPU

# The same safety prompt used in app/chatbot.py, so Meditron gets the same
# grounding rules as Gemini. Imported lazily to avoid a circular import.
_SYSTEM_PROMPT_CACHE = None


def _system_prompt() -> str:
    global _SYSTEM_PROMPT_CACHE
    if _SYSTEM_PROMPT_CACHE is None:
        from .chatbot_proxy import SYSTEM_PROMPT   # local proxy avoids import cycle
        _SYSTEM_PROMPT_CACHE = SYSTEM_PROMPT
    return _SYSTEM_PROMPT_CACHE


def available() -> bool:
    """True if MV_ENABLE_MEDITRON=1 AND the local Ollama server is reachable
    AND the configured model is loaded."""
    if os.environ.get("MV_ENABLE_MEDITRON", "").lower() not in ("1", "true", "yes"):
        return False
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=3.0)
        if r.status_code != 200:
            return False
        tags = (r.json() or {}).get("models") or []
        return any(OLLAMA_MODEL in (m.get("name") or "") for m in tags)
    except Exception:
        return False


def chat(message: str, language: str, ctx: dict[str, Any], history: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Call the local Meditron Ollama endpoint. Returns the parsed JSON reply
    matching the /chat contract, or None on any failure (caller falls back)."""
    if not available() or not message:
        return None
    try:
        ctx_json = json.dumps(ctx or {}, ensure_ascii=False)[:1200]
        history_text = "\n".join(
            f"User: {t.get('message','')}\nAssistant: {t.get('reply','')}"
            for t in (history or [])[-4:]
        )[:1200]
        user_prompt = (
            f"LANGUAGE: {language}\n"
            f"USER_MESSAGE: {message}\n"
            f"MEDICINE_CONTEXT: {ctx_json}\n"
            f"RECENT_HISTORY:\n{history_text}\n"
            f"Answer now as JSON per the schema."
        )
        # Ollama's /api/chat endpoint supports system + user turns + JSON mode.
        payload = {
            "model": OLLAMA_MODEL,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": _system_prompt()},
                {"role": "user", "content": user_prompt},
            ],
            "options": {"temperature": 0.3},
        }
        r = httpx.post(f"{OLLAMA_URL}/api/chat", json=payload, timeout=HTTP_TIMEOUT)
        if r.status_code != 200:
            return None
        msg = (r.json() or {}).get("message") or {}
        content = msg.get("content") or ""
        # The model should have produced JSON; parse defensively.
        import re
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content).strip()
        try:
            parsed = json.loads(content)
        except Exception:
            # If parsing fails, wrap the raw text so the caller can still show something.
            return {
                "ok": True,
                "reply": content[:500],
                "speakableText": content[:240],
                "language": language,
                "model": OLLAMA_MODEL,
                "disclaimer": "Information from public medicine references. Not medical advice.",
                "flagged": False,
                "flagReason": None,
            }
        return {
            "ok": True,
            "reply": str(parsed.get("reply") or "").strip(),
            "speakableText": str(parsed.get("speakableText") or parsed.get("reply") or "").strip(),
            "language": parsed.get("language") or language,
            "model": OLLAMA_MODEL,
            "disclaimer": parsed.get("disclaimer") or "Information from public medicine references. Not medical advice.",
            "flagged": bool(parsed.get("flagged")),
            "flagReason": parsed.get("flagReason"),
        }
    except Exception:
        return None
