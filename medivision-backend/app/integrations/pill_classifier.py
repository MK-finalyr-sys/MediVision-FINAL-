"""
Pill image classifier — EfficientNet-B0 ONNX from krishrakholiya32/fake-medicine-detection.

When the user uploads a strip photo AND the OCR text is ambiguous (Feature 1:
/candidates), this adapter runs the photo through the ONNX model and returns
the top-k predicted pill classes with probabilities. The result is merged with
the OCR-based candidates to break ties.

The model was trained on the OGYEIv2 dataset (112 pill classes, mostly
European/Hungarian brand names). Labels look like 'aspirin_ultra_500_mg',
'atorvastatin_teva_20_mg' — the SALT is recoverable from the label, so even
when the brand is European, the salt can be matched against our 40-salt
lexicon for the downstream pipeline.

Bundle: 16 MB ONNX + 4 KB labels.json — included directly in the zip.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

HERE = Path(__file__).parent
MODEL_PATH = HERE / "pill_classifier" / "pill_classifier_effnetb0.onnx"
LABELS_PATH = HERE / "pill_classifier" / "labels.json"
README_PATH = HERE / "pill_classifier" / "README_effnet.md"

MODEL_NAME = "EfficientNet-B0 ONNX (OGYEIv2, 112 classes, top-1 acc 97.2%)"
IMAGE_SIZE = 224
IMAGENET_MEAN = (0.485, 0.456, 0.406)
IMAGENET_STD = (0.229, 0.224, 0.225)

# --- lazy-loaded singletons (so the model loads once per process) ---
_session = None
_labels: list[str] | None = None
_tried_load = False


def available() -> bool:
    return MODEL_PATH.exists() and LABELS_PATH.exists()


def num_classes() -> int:
    if not LABELS_PATH.exists():
        return 0
    global _labels
    if _labels is None:
        _labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
    return len(_labels)


def _ensure_loaded() -> bool:
    """Returns True if the ONNX session is loaded; False if it cannot be."""
    global _session, _labels, _tried_load
    if _session is not None and _labels is not None:
        return True
    if _tried_load:
        return False
    _tried_load = True
    if not available():
        return False
    try:
        import onnxruntime as ort
        import numpy as np  # noqa: F401  (peer dep of onnxruntime inference)
        opts = ort.SessionOptions()
        opts.intra_op_num_threads = 2
        opts.inter_op_num_threads = 1
        _session = ort.InferenceSession(str(MODEL_PATH), sess_options=opts, providers=["CPUExecutionProvider"])
        _labels = json.loads(LABELS_PATH.read_text(encoding="utf-8"))
        return True
    except Exception:
        # onnxruntime not installed, or model file corrupt — degrade silently.
        _session = None
        _labels = None
        return False


def _softmax(x):
    import numpy as np
    e = __import__("math").exp  # noqa: F841
    m = float(max(x))
    exps = [float(__import__("math").exp(xi - m)) for xi in x]
    z = sum(exps)
    return [v / z for v in exps]


def _preprocess(image_rgb_bytes: bytes):
    """Decode image bytes -> NCHW float32 tensor at IMAGE_SIZE."""
    import numpy as np
    from PIL import Image
    import io
    img = Image.open(io.BytesIO(image_rgb_bytes)).convert("RGB")
    img = img.resize((IMAGE_SIZE, IMAGE_SIZE), Image.LANCZOS)
    arr = np.asarray(img, dtype=np.float32) / 255.0
    arr = (arr - np.array(IMAGENET_MEAN, dtype=np.float32)) / np.array(IMAGENET_STD, dtype=np.float32)
    arr = arr.transpose(2, 0, 1)[np.newaxis].astype(np.float32)
    return arr


def classify(image_bytes: bytes, top_k: int = 3) -> list[dict[str, Any]]:
    """Run the pill image through the EfficientNet ONNX model.

    Returns top-k dicts:
      [{"label": "aspirin_ultra_500_mg", "probability": 0.78,
        "salt": "Aspirin", "strength": "500 mg"}, ...]
    The salt is parsed from the label using the underscore-separated structure.
    """
    if not _ensure_loaded():
        return []
    try:
        import numpy as np
        arr = _preprocess(image_bytes)
        input_name = _session.get_inputs()[0].name
        # Try common output names — the model exports "logits" but onnxruntime
        # may name it differently depending on export.
        out_names = [o.name for o in _session.get_outputs()]
        logits_key = "logits" if "logits" in out_names else out_names[0]
        logits = _session.run([logits_key], {input_name: arr})[0][0]
        probs = _softmax(logits)
        top_idx = list(__import__("numpy").argsort(probs)[::-1][:top_k])
        out = []
        for i in top_idx:
            label = _labels[i]
            out.append({
                "label": label,
                "labelPretty": label.replace("_", " ").title(),
                "probability": round(float(probs[i]), 4),
                "salt": _salt_from_label(label),
                "strength": _strength_from_label(label),
            })
        return out
    except Exception:
        return []


# ---- label parsing -------------------------------------------------------

# Common European/INN salt names that appear in the OGYEI labels.
_KNOWN_SALTS = [
    "aspirin", "paracetamol", "acetaminophen", "ibuprofen", "diclofenac",
    "aceclofenac", "atorvastatin", "rosuvastatin", "simvastatin",
    "omeprazole", "pantoprazole", "esomeprazole", "rabeprazole",
    "metformin", "glimepiride", "gliclazide", "sitagliptin",
    "amlodipine", "telmisartan", "losartan", "ramipril", "atenolol",
    "metoprolol", "bisoprolol", "enalapril",
    "azithromycin", "amoxicillin", "doxycycline", "ciprofloxacin",
    "levofloxacin", "ofloxacin", "cefixime", "cephalexin",
    "cetirizine", "levocetirizine", "loratadine", "desloratadine",
    "montelukast", "salbutamol", "budesonide",
    "tramadol", "codeine", "morphine",
    "ondansetron", "domperidone", "metoclopramide",
    "levothyroxine", "warfarin", "clopidogrel",
    "furosemide", "spironolactone", "hydrochlorothiazide",
    "diazepam", "lorazepam", "clonazepam", "alprazolam",
    "sertraline", "escitalopram", "fluoxetine", "venlafaxine",
    "vitamin c", "ascorbic acid", "vitamin d", "cholecalciferol",
    "cyanocobalamin", "folic acid", "iron",
]
_SALT_PATTERN = re.compile(r"\b(" + "|".join(re.escape(s) for s in _KNOWN_SALTS) + r")\b", re.I)
_STRENGTH_PATTERN = re.compile(r"(\d+(?:[.,]\d+)?)\s*(mg|mcg|g|iu|ml)\b", re.I)


def _salt_from_label(label: str) -> str | None:
    m = _SALT_PATTERN.search(label.lower())
    if m:
        s = m.group(1).lower()
        # Normalise to our canonical salt names where they differ
        return {
            "paracetamol": "Paracetamol",
            "acetaminophen": "Paracetamol",
            "salbutamol": "Salbutamol",
            "ascorbic acid": "Cholecalciferol",  # rough — both are vitamins
        }.get(s, s.capitalize())
    # Fallback: take the first word, capitalised
    parts = label.split("_")
    return parts[0].capitalize() if parts and parts[0] else None


def _strength_from_label(label: str) -> str | None:
    m = _STRENGTH_PATTERN.search(label.lower())
    if m:
        return f"{m.group(1)} {m.group(2)}"
    return None
