# MediVision AI — Fully Integrated Final Application

**Know what you take. Think before you take it.**

A complete, mobile-first PWA that scans medicine strips, identifies them,
shows trilingual (EN/TA/HI) safety information, warns about drug
interactions based on the patient's profile, and lets users ask a
multilingual chatbot about the scanned medicine.

This zip contains your full MK frontend **plus** the integrated Python
backend **plus** 5 upstream open-source integrations, all wired together.

---

## What's inside

```
medivision-final-app/
├── src/                                  ← Your Next.js 16 frontend (untouched UI)
│   ├── app/api/ai/                       ← 7 same-origin proxy routes (NEW)
│   │   ├── identify/route.ts             ← existing pipeline
│   │   ├── candidates/route.ts           ← Feature 1: damaged-strip probability
│   │   ├── recommend/route.ts            ← Feature 2: patient-aware safety
│   │   ├── chat/route.ts                 ← Feature 3: multilingual chatbot
│   │   ├── transcribe/route.ts           ← Tamil/Hindi voice input (AI4Bharat)
│   │   ├── pricing/route.ts              ← PMBJP generic price lookup
│   │   └── health/route.ts               ← backend capability probe
│   ├── lib/ai-backend.ts                 ← typed client + zod schemas (NEW)
│   ├── lib/storage.ts                    ← +1 key: aiMeds (minimal edit)
│   ├── lib/catalog.ts                    ← +AI helpers (additive)
│   ├── components/scan-view.tsx          ← +AI rescue hook at low-confidence
│   └── components/medivision.tsx         ← +1 line: hydrate AI meds
│
├── medivision-backend/                   ← Python FastAPI backend
│   ├── app/                              ← existing pipeline + 3 new endpoints
│   │   ├── main.py                       ← wires ALL endpoints + integrations
│   │   ├── candidates.py                 ← Feature 1: probability analysis
│   │   ├── safety.py                     ← Feature 2: rule-based engine (fallback)
│   │   ├── chatbot.py                    ← Feature 3: Gemini + rule-based chat
│   │   ├── pipeline.py, model_ner.py, retriever.py, data.py, train.py
│   │   ├── models/ner_crf.joblib         ← trained CRF (F1=0.9963)
│   │   └── integrations/                 ← 5 upstream repos integrated (NEW)
│   │       ├── pill_classifier/          ← EfficientNet-B0 ONNX (16 MB, bundled)
│   │       │   ├── pill_classifier_effnetb0.onnx
│   │       │   └── labels.json
│   │       ├── indian_pricing/           ← PMBJP catalog (1.5 MB, bundled)
│   │       │   ├── jan_aushadhi_catalog.json
│   │       │   ├── price_catalog.json
│   │       │   └── brand_hints.json      ← 323,711 Indian brand→salt mappings
│   │       ├── reference/pillchecker/    ← SPerekrestova/pillchecker-api (MIT)
│   │       │   ├── clients/              ← ddinter_db.py, openfda_client.py, rxnorm_client.py
│   │       │   ├── nlp/                  ← severity_classifier.py (DeBERTa)
│   │       │   ├── services/
│   │       │   └── scripts/              ← build_ddinter_db.py
│   │       ├── reference/rxcheck/        ← indiser/Rxcheck (MIT) — code only
│   │       ├── pill_classifier.py        ← adapter: ONNX inference + salt parsing
│   │       ├── brand_salt_lookup.py      ← adapter: 323k brand index
│   │       ├── indian_pricing.py         ← adapter: PMBJP pricing lookup
│   │       ├── ddinter.py                ← adapter: SQLite client (DB built on first run)
│   │       ├── openfda_interactions.py   ← adapter: OpenFDA fallback (keyless)
│   │       ├── indic_stt.py              ← adapter: AI4Bharat conformer (download on first run)
│   │       ├── meditron_chat.py          ← adapter: Meditron via Ollama (opt-in)
│   │       ├── chatbot_proxy.py          ← shared system prompt
│   │       ├── setup_integrations.py     ← one-time setup script
│   │       └── __init__.py               ← status_map() for /health
│   │
│   ├── data/                             ← train.jsonl, val.jsonl (model corpus)
│   ├── INTEGRATION.md                    ← full API docs
│   ├── requirements.txt                  ← Python deps
│   └── demo-frontend.html                ← standalone reference UI
│
├── .env.example                          ← backend URL + optional keys
├── package.json                          ← your existing Next.js deps
├── README.md                             ← this file
└── WHATS_IN_THIS_ZIP.md                  ← detailed manifest
```

---

## Quick start (5 minutes)

### 1. Install frontend deps

```bash
cd medivision-final-app
npm install   # or: bun install
```

### 2. Install backend deps + start the backend

```bash
cd medivision-backend
pip install -r requirements.txt
uvicorn app.main:app --port 8000 --reload
```

Open http://localhost:8000/health in another tab — you should see all 7
features reported, including the bundled integrations:

```json
{
  "status": "ok",
  "ner": "crf-trained (entity F1=0.9963)",
  "integrations": {
    "pillClassifier": {"available": true, "model": "EfficientNet-B0 ONNX...", "classes": 112},
    "brandLookup":    {"available": true, "brands": 323711},
    "pmjpPricing":    {"available": true, "entries": ...},
    "ddInter":        {"available": false, "dbPath": "..."},   // run setup to enable
    "openfdaInteractions": {"available": true},
    "indicSTT":       {"available": false},                    // opt-in
    "meditron":       {"available": false}                     // opt-in
  }
}
```

### 3. Start the frontend

```bash
cd ..   # back to project root
npm run dev
```

Open http://localhost:3000 — you should see your MediVision app exactly as
before, plus a small "AI model backend connected" indicator.

### 4. (Optional) Enable the heavy integrations

The 3 light integrations are bundled and work immediately. The 2 heavy ones
need a one-time setup:

```bash
cd medivision-backend

# DDInter SQLite (drug-drug interactions, ~50 MB download, 3-5 min)
python -m app.integrations.setup_integrations build-ddinter

# Indic Conformer (Tamil/Hindi STT, ~600 MB download)
pip install transformers torch torchaudio
python -m app.integrations.setup_integrations download-indic-stt

# Meditron 7B (offline chatbot, needs Ollama)
# Install from https://ollama.com/download, then:
ollama pull meditron:7b
# Set env var MV_ENABLE_MEDITRON=1 before starting the backend
```

Re-run `python -m app.integrations.setup_integrations status` any time to see
what is installed and what is missing.

---

## How the 5 repos are integrated

| # | Repo | How it's integrated | Bundled? |
|---|---|---|---|
| 1 | `SPerekrestova/pillchecker-api` | `app/integrations/reference/pillchecker/` has the full source. `app/integrations/ddinter.py` adapts the async SQLite client to sync. `app/integrations/openfda_interactions.py` is a sync port of their OpenFDA client (4-hour TTL cache). `python -m app.integrations.setup_integrations build-ddinter` runs their `build_ddinter_db.py` to build the SQLite DB. | Reference code bundled; DB built on first run |
| 2 | `krishrakholiya32/fake-medicine-detection` | `app/integrations/pill_classifier/pill_classifier_effnetb0.onnx` (16 MB) + `labels.json` (112 classes) bundled directly. `app/integrations/pill_classifier.py` loads ONNX via onnxruntime, runs PIL preprocessing + softmax + top-k, parses the salt from the label. Wired into `/candidates` as a vision-based tiebreaker when `imageB64` is supplied. | ONNX + labels bundled |
| 3 | `ai4bharat/indic-conformer-600m-multilingual` | `app/integrations/indic_stt.py` adapts the HF model. Wired into a new `/transcribe` endpoint. Frontend proxy `/api/ai/transcribe`. `python -m app.integrations.setup_integrations download-indic-stt` downloads the ~600 MB model on first run. Opt-in via `MV_ENABLE_INDIC_STT=1`. | Adapter only — too large to bundle |
| 4 | `indiser/Rxcheck` | `app/integrations/reference/rxcheck/` has the full Python source. `app/integrations/indian_pricing/` bundles their PMBJP JSON catalogs (1.5 MB). `app/integrations/indian_pricing.py` loads them and serves the new `/pricing` endpoint. `app/integrations/brand_salt_lookup.py` loads their 13 MB `brand_hints.json` (323,711 brand→salt mappings) and is queried by `/candidates` and `/identify`. | Data + reference code bundled |
| 5 | `epfllm/meditron` | `app/integrations/meditron_chat.py` calls Meditron-7B through a local Ollama server (no model bundling — too large). Wired into `/chat` as the first-choice LLM (above Gemini). Opt-in via `MV_ENABLE_MEDITRON=1`. | Adapter only — needs Ollama |

---

## API endpoints (full list)

| Method | Path | Purpose |
|---|---|---|
| GET | `/health` | Backend status + integrations status map |
| POST | `/extract` | NER entities only (no network) |
| POST | `/identify` | Full sourced result for an OCR text |
| POST | `/candidates` | Feature 1: probability-ranked candidates (+ vision tiebreaker if imageB64) |
| POST | `/recommend` | Feature 2: patient-aware safety (rules + DDInter + OpenFDA + PMBJP pricing) |
| POST | `/chat` | Feature 3: multilingual chatbot (Meditron > Gemini > rule-based) |
| POST | `/transcribe` | Tamil/Hindi/English voice → text (AI4Bharat conformer) |
| POST | `/pricing` | PMBJP generic price lookup |
| GET | `/brand-search?q=...` | Search the 323k Indian brand index |

---

## Safety rules (hard, never violated anywhere)

- No diagnosis. No personalised dosing. No free-form AI answers about drugs.
- No ordering. Low confidence always routes to "ask your pharmacist".
- Disclaimer on every card: "Information from the label and a reference list. Not medical advice."
- All data stays on-device (localStorage); only OCR text + (optional) image bytes
  go to your backend. No third-party analytics.
- Every claim has a real source URL (FDA / MedlinePlus / RxNorm / DailyMed / DDInter).

---

## Deploy

### Backend → Render (free tier)

1. Push the whole folder to GitHub.
2. Render → New → Web Service → pick the repo.
3. Root Directory: `medivision-backend`
4. Build: `pip install -r requirements.txt`
5. Start: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
6. Environment: `GEMINI_API_KEY=<optional>`, `MV_ENABLE_MEDITRON=<optional>`
7. Copy the `https://…onrender.com` URL.

### Frontend → Vercel or Netlify

1. Import the same GitHub repo.
2. Root Directory: project root (where `package.json` lives).
3. Environment Variables: `BACKEND_URL=https://your-app.onrender.com`
4. Deploy.

---

## Honest limitations (say these in your viva)

- The CRF is trained on lexicon-generated synthetic strip text; real-world
  photos add layout noise that the Tesseract stage cleans up.
- The EfficientNet pill classifier was trained on the OGYEIv2 dataset (112
  European pill classes). For Indian brands it gives a SALT hint (parsed from
  the label), not a direct brand match. Retraining on Indian pill photos is a
  documented upgrade path.
- DDInter 2.0 covers international drugs but is Chinese-sourced; some
  Indian-specific brands may not have interaction rows. OpenFDA fallback
  catches the rest.
- Indic Conformer is 600 MB — too large to bundle, hence the opt-in setup.
- Meditron needs a local Ollama install with ~13 GB model. For the viva demo,
  Gemini free tier is the easier path.
- No dosing, no diagnosis — by design, everywhere.

---

## Reverting any single integration

Each integration is independent. To disable one without touching the others,
set the matching env var before starting the backend:

```bash
MV_DISABLE_PILL_CLASSIFIER=1   # skip the EfficientNet vision path
MV_DISABLE_DDINTER=1           # skip the DDInter SQLite lookup
MV_DISABLE_OPENFDA_INTERACTIONS=1
MV_DISABLE_BRAND_LOOKUP=1      # use only the 80-brand lexicon
MV_DISABLE_PMJP_PRICING=1      # skip PMBJP pricing warnings
```

The endpoints stay live and fall back to the built-in rule-based layer.
