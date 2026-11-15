"""
AI4Bharat Indic Conformer — Tamil / Hindi / Indic speech-to-text.

Model: ai4bharat/indic-conformer-600m-multilingual (HuggingFace, 600M params,
~600 MB download, covers all 22 official Indian languages).

This adapter downloads the model + processor on first use (or via the
setup_integrations.py script), caches them under integrations/data/, and runs
inference via the transformers library.

To enable:
  1) pip install transformers torch torchaudio
  2) python -m integrations.setup_integrations download-indic-stt
  3) Set environment variable MV_ENABLE_INDIC_STT=1

To call:
  POST /transcribe  { audioB64: "<base64-encoded WAV>", language: "ta"|"hi"|"en" }
  -> { "text": "...", "language": "ta", "model": "indic-conformer-600m" }

The frontend can capture voice via the browser MediaRecorder API and POST the
resulting WAV bytes here for transcription, then feed the text to /chat.

NOTE: This is OPT-IN because the model is 600 MB and torch is a heavy dep.
Without it, /chat still accepts text directly and the Web Speech API in the
browser handles voice input client-side.
"""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
MODEL_DIR = HERE / "data" / "indic_conformer"
MODEL_ID = "ai4bharat/indic-conformer-600m-multilingual"

_processor = None
_model = None
_tried_load = False


def available() -> bool:
    """True if MV_ENABLE_INDIC_STT=1 AND the model is downloaded AND transformers+torch import cleanly."""
    if os.environ.get("MV_ENABLE_INDIC_STT", "").lower() not in ("1", "true", "yes"):
        return False
    if not MODEL_DIR.exists() or not any(MODEL_DIR.iterdir() if MODEL_DIR.exists() else []):
        return False
    try:
        import transformers  # noqa: F401
        import torch  # noqa: F401
        return True
    except Exception:
        return False


def _ensure_loaded() -> bool:
    global _processor, _model, _tried_load
    if _processor is not None and _model is not None:
        return True
    if _tried_load:
        return False
    _tried_load = True
    if not available():
        return False
    try:
        from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq
        import torch
        _processor = AutoProcessor.from_pretrained(str(MODEL_DIR))
        _model = AutoModelForSpeechSeq2Seq.from_pretrained(str(MODEL_DIR))
        _model.to("cpu")  # CPU-only for portability; GPU works if available
        _model.eval()
        return True
    except Exception:
        _processor, _model = None, None
        return False


def transcribe(audio_bytes: bytes, language: str = "ta") -> dict[str, Any]:
    """Transcribe WAV/FLAC/MP3 bytes to text in the chosen Indic language."""
    if not _ensure_loaded():
        return {
            "ok": False,
            "text": "",
            "reason": "Indic STT not enabled. Run setup_integrations download-indic-stt and set MV_ENABLE_INDIC_STT=1.",
            "language": language,
        }
    try:
        import torchaudio
        # Decode bytes to a temp file, then load with torchaudio
        import tempfile, os
        suffix = ".wav"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name
        try:
            waveform, sample_rate = torchaudio.load(tmp_path)
            # Resample to 16kHz if needed (conformer expects 16k)
            if sample_rate != 16000:
                resampler = torchaudio.transforms.Resample(sample_rate, 16000)
                waveform = resampler(waveform)
                sample_rate = 16000
            # Convert to mono
            if waveform.shape[0] > 1:
                waveform = waveform.mean(dim=0, keepdim=True)
            # Run inference
            import torch
            inputs = _processor(waveform.squeeze().numpy(), sampling_rate=sample_rate, return_tensors="pt")
            # Set language token if the processor supports it
            lang_token = f"<|{language}|>" if hasattr(_processor, "lang_to_id") else None
            with torch.no_grad():
                if lang_token and hasattr(_model.config, "forced_decoder_ids"):
                    forced = _processor.get_decoder_prompt_ids(language=language, task="transcribe")
                    generated = _model.generate(**inputs, forced_decoder_ids=forced)
                else:
                    generated = _model.generate(**inputs)
            text = _processor.batch_decode(generated, skip_special_tokens=True)[0]
            return {"ok": True, "text": text.strip(), "language": language, "model": MODEL_ID}
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
    except Exception as e:
        return {"ok": False, "text": "", "reason": f"transcription failed: {e}", "language": language}


def transcribe_b64(audio_b64: str, language: str = "ta") -> dict[str, Any]:
    """Convenience wrapper: accept a base64-encoded WAV (as the frontend would send)."""
    try:
        raw = base64.b64decode(audio_b64)
        return transcribe(raw, language=language)
    except Exception as e:
        return {"ok": False, "text": "", "reason": f"base64 decode failed: {e}", "language": language}
