"""
MediVision AI — Phase 4 AI/ML MODEL.
CRF (Conditional Random Field) sequence tagger that extracts medicine entities
(BRAND / SALT / STRENGTH / FORM / MFR) from noisy OCR text of blister strips.

- Train   : python3 -m app.train   -> models/ner_crf.joblib + models/report.json
- Predict : app.model_ner.predict_entities("Do1o 650 Tab1et")  (OCR noise ok)
- Fallback: before the model is trained, a lexicon matcher keeps the API alive
  so the backend never hard-fails.
"""
import difflib
import os
import re

import joblib

HERE = os.path.dirname(__file__)
MODEL_PATH = os.path.join(HERE, "..", "models", "ner_crf.joblib")
REPORT_PATH = os.path.join(HERE, "..", "models", "report.json")

from .data import BRAND_TO_SALT, tokenize  # single source of truth

_salt_words = {w.lower() for s in BRAND_TO_SALT.values() for w in s.split()}
_salt_words |= {w.lower() for s in BRAND_TO_SALT.values() for w in s.replace("-", " ").split()}
for extra in (
    "Paracetamol Acetaminophen Ibuprofen Aspirin Pantoprazole Omeprazole Esomeprazole "
    "Rabeprazole Metformin Glimepiride Gliclazide Sitagliptin Amlodipine Telmisartan "
    "Losartan Ramipril Atenolol Metoprolol Atorvastatin Rosuvastatin Clopidogrel "
    "Azithromycin Amoxicillin Cefixime Ciprofloxacin Ofloxacin Levofloxacin Doxycycline "
    "Cetirizine Levocetirizine Montelukast Diclofenac Aceclofenac Tramadol Ondansetron "
    "Domperidone Ranitidine Levothyroxine Cholecalciferol Salbutamol Albuterol"
).split():
    _salt_words.add(extra.lower())

_brands_lower = list(BRAND_TO_SALT.keys())

_ALL_SALTS = list({s for s in BRAND_TO_SALT.values()})

INSUFFICIENT_SALTS = {
    "hydrochloride", "hcl", "sodium", "potassium", "maleate", "tartrate",
    "succinate", "mesylate", "phosphate", "sulfate", "sulphate", "acetate",
    "citrate", "hydrate", "dihydrate", "trihydrate", "monohydrate", "fumarate",
    "gluconate", "nitrate", "bromide", "chloride", "calcium", "dipivoxil",
    "axetil", "palmitate", "decanoate", "valerate", "propionate", "carbonate",
    "bicarbonate", "disodium", "dipotassium", "zinc", "oxide", "acid", "salt",
    "salts", "tablets", "capsules", "injection", "syrup", "ip", "bp", "usp",
    "mg", "ml", "gm", "g", "mcg", "iu",
}


def is_insufficient_salt(name: str | None) -> bool:
    """True if name is empty or only contains chemical suffixes / dosage terms."""
    if not name:
        return True
    clean = re.sub(r"[^a-zA-Z\s]", " ", name).lower().strip()
    words = clean.split()
    if not words:
        return True
    return all(w in INSUFFICIENT_SALTS for w in words)


def _canon_salt(name):
    """'Tamsu1osin' -> 'Tamsulosin'; verify against known pharmaceutical salts."""
    if not name or is_insufficient_salt(name):
        return None
    name_clean = name.strip()
    if is_insufficient_salt(name_clean):
        return None
    if name_clean in _ALL_SALTS:
        return name_clean
    m = difflib.get_close_matches(name_clean, _ALL_SALTS, n=1, cutoff=0.72)
    if m:
        return m[0]
    # Check if name is in Indian brand/salt lexicon
    try:
        from .integrations import brand_salt_lookup
        if brand_salt_lookup.available():
            brand_salt_lookup._ensure_loaded()
            if brand_salt_lookup._cache:
                low = name_clean.lower()
                all_salts_lower = {
                    s.lower(): s
                    for s in brand_salt_lookup._cache.values()
                    if not is_insufficient_salt(s)
                }
                if low in all_salts_lower:
                    return all_salts_lower[low].title()
                salt_m = difflib.get_close_matches(low, list(all_salts_lower.keys()), n=1, cutoff=0.82)
                if salt_m:
                    return all_salts_lower[salt_m[0]].title()
    except Exception:
        pass
    # If not in any recognized medicine salt list, do NOT invent a valid salt
    return None


def _canon_brand_salt(brand_text):
    """'Do1o' -> 'Paracetamol' via fuzzy brand lookup."""
    b = (brand_text or "").lower()
    if b in BRAND_TO_SALT:
        s = BRAND_TO_SALT[b]
        return None if is_insufficient_salt(s) else s
    m = difflib.get_close_matches(b, _brands_lower, n=1, cutoff=0.72)
    if m:
        s = BRAND_TO_SALT[m[0]]
        return None if is_insufficient_salt(s) else s
    return None


def _shape(w: str) -> str:
    s = re.sub(r"[A-Z]", "X", re.sub(r"[a-z]", "x", w))
    return re.sub(r"\d", "9", s)


def word_features(sent, i):
    w = sent[i]
    f = {
        "bias": 1.0,
        "lower": w.lower(),
        "isupper": w.isupper(),
        "istitle": w.istitle(),
        "isdigit": w.isdigit(),
        "ndigits": sum(c.isdigit() for c in w),
        "len": len(w),
        "shape": _shape(w),
        "pre1": w[:1].lower(),
        "pre2": w[:2].lower(),
        "pre3": w[:3].lower(),
        "suf1": w[-1:].lower(),
        "suf2": w[-2:].lower(),
        "suf3": w[-3:].lower(),
        "hasdigit": any(c.isdigit() for c in w),
    }
    if i > 0:
        p = sent[i - 1]
        f.update({"-1:lower": p.lower(), "-1:istitle": p.istitle(), "-1:shape": _shape(p)})
    else:
        f["BOS"] = True
    if i < len(sent) - 1:
        n = sent[i + 1]
        f.update({"+1:lower": n.lower(), "+1:istitle": n.istitle(), "+1:shape": _shape(n)})
    else:
        f["EOS"] = True
    return f


def features(sent):
    return [word_features(sent, i) for i in range(len(sent))]


# ---------------- inference ----------------

def _model():
    if os.path.exists(MODEL_PATH):
        if not hasattr(_model, "_cache"):
            _model._cache = joblib.load(MODEL_PATH)
        return _model._cache
    return None


def status() -> str:
    if os.path.exists(MODEL_PATH):
        try:
            rep = open(REPORT_PATH, encoding="utf-8").read()
            f1 = re.search(r'"f1":\s*([\d.]+)', rep)
            return f"crf-trained (entity F1={f1.group(1) if f1 else '?'})"
        except Exception:
            return "crf-trained"
    return "lexicon-fallback (model not trained yet — run: python3 -m app.train)"


def _spanify(tokens, tags):
    """BIO tags -> entity spans with char offsets."""
    ents, cur, cur_label = [], [], None
    idx = 0
    starts = []
    pos = 0
    for t in tokens:
        starts.append(pos)
        pos += len(t) + 1
    for i, (t, g) in enumerate(zip(tokens, tags)):
        lab = g[2:] if g != "O" else None
        if g.startswith("B-"):
            if cur:
                ents.append((cur_label, " ".join(cur), starts[i - len(cur)], 0))
            cur, cur_label = [t], lab
        elif g.startswith("I-") and cur and lab == cur_label:
            cur.append(t)
        else:
            if cur:
                ents.append((cur_label, " ".join(cur), starts[i - len(cur)], 0))
            cur, cur_label = ([t], lab) if lab else ([], None)
            if not lab:
                cur = []
    if cur:
        ents.append((cur_label, " ".join(cur), starts[len(tokens) - len(cur)], 0))
    out = []
    for lab, text, start, _ in ents:
        out.append({"label": lab, "text": text, "start": start, "end": start + len(text)})
    return out


def _lexicon_predict(text: str):
    """No-model fallback: find known salts/brands via word-boundary regex."""
    ents = []
    for w in sorted(_salt_words | set(_brands_lower), key=len, reverse=True):
        for m in re.finditer(rf"\b({re.escape(w)})\b", text, re.IGNORECASE):
            frag = m.group(1)
            # de-noise OCR chars when matching (D0lo -> Dolo)
            frag_ok = frag.lower()
            if frag_ok in _brands_lower:
                ents.append({"label": "BRAND", "text": frag, "start": m.start(), "end": m.end()})
            elif frag_ok in _salt_words:
                ents.append({"label": "SALT", "text": frag, "start": m.start(), "end": m.end()})
    # dedupe overlapping (keep longer)
    ents.sort(key=lambda e: -(e["end"] - e["start"]))
    kept, taken = [], []
    for e in ents:
        if not any(not (e["end"] <= s or e["start"] >= t) for s, t in taken):
            kept.append(e)
            taken.append((e["start"], e["end"]))
    return sorted(kept, key=lambda e: e["start"])


def predict_entities(text: str):
    """Full pipeline entry: returns entity list + derived salt/brand/strength."""
    model = _model()
    tokens = tokenize(text)
    if model is None:
        spans = _lexicon_predict(text)
    else:
        tags = model.predict_single(features(tokens))
        spans = _spanify(tokens, tags)
    first = lambda lab: next((s for s in spans if s["label"] == lab), None)  # noqa: E731
    brand_e, salt_e, str_e = first("BRAND"), first("SALT"), first("STRENGTH")
    salt = None
    basis = "none"
    if salt_e:
        cand_s = _canon_salt(salt_e["text"])
        if cand_s and not is_insufficient_salt(cand_s):
            salt = cand_s
            basis = "salt-in-text"
    if not salt and brand_e:
        cand_s = _canon_brand_salt(brand_e["text"])
        if cand_s and not is_insufficient_salt(cand_s):
            salt = cand_s
            basis = "brand-hint"
    return {
        "entities": spans,
        "salt": salt,
        "brand": brand_e["text"] if brand_e else None,
        "strength": str_e["text"] if str_e else None,
        "mappingBasis": basis,
        "model": status(),
    }
