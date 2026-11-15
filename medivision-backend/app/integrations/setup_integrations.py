#!/usr/bin/env python3
"""
MediVision AI — Integration setup script.

One-time setup for the heavy integrations (the light ones — pill classifier
ONNX, brand lookup, PMBJP pricing — are already bundled in the zip).

Usage:
  python -m integrations.setup_integrations <command>

Commands:
  status                  -> show what is installed and what is missing
  build-ddinter           -> download DDInter CSVs and build the SQLite DB (~3-5 min, ~50 MB)
  download-indic-stt      -> download AI4Bharat indic-conformer (~600 MB)
  check-ollama            -> check if Ollama is running and Meditron is pulled
  all                     -> run every applicable setup step (skips ones that need manual install)

Run from inside the medivision-backend/ folder.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent
DATA_DIR = HERE / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)


def _status() -> int:
    from . import status_map
    print("\nMediVision integration status")
    print("=" * 60)
    m = status_map()
    for name, info in m.items():
        if info.get("available"):
            extra = ""
            for k in ("classes", "brands", "rows", "entries"):
                if k in info:
                    extra = f" ({info[k]:,} {k})"
                    break
            print(f"  {name:<22} READY{extra}")
        else:
            err = info.get("error", "not installed")
            print(f"  {name:<22} MISSING  ({err})")
    print()
    print("To install missing integrations:")
    print("  python -m integrations.setup_integrations build-ddinter")
    print("  python -m integrations.setup_integrations download-indic-stt")
    print("  (Meditron: install Ollama from https://ollama.com, then `ollama pull meditron:7b`)")
    return 0


def _build_ddinter() -> int:
    """Run pillchecker-api's build_ddinter_db.py against our data/ folder."""
    ref_dir = HERE / "reference" / "pillchecker"
    if not ref_dir.exists():
        print("ERROR: pillchecker reference scripts not found at", ref_dir)
        print("       The bundled zip should include this folder.")
        return 1
    scripts_dir = ref_dir / "scripts"
    if not scripts_dir.exists():
        print("ERROR: scripts folder not found at", scripts_dir)
        return 1
    print("\n[1/3] Fetching DDInter CSVs (~50 MB download)...")
    sys.path.insert(0, str(ref_dir))
    env = os.environ.copy()
    env["INTERACTION_DB_PATH"] = str(DATA_DIR / "ddinter.db")
    # The pillchecker scripts expect to run from the repo root.
    cmd = [sys.executable, "-m", "scripts.build_ddinter_db", "fetch"]
    rc = subprocess.call(cmd, cwd=str(ref_dir), env=env)
    if rc != 0:
        print("Fetch failed.")
        return rc
    print("\n[2/3] Resolving RxNorm crosswalk (this takes a few minutes)...")
    rc = subprocess.call([sys.executable, "-m", "scripts.build_ddinter_db", "resolve-rxnorm"],
                         cwd=str(ref_dir), env=env)
    crosswalk_path = ref_dir / "data" / "ddinter_crosswalk.json"
    if rc != 0 or not crosswalk_path.exists():
        print("Resolve-rxnorm skipped or unavailable; creating base crosswalk fallback.")
        crosswalk_path.parent.mkdir(parents=True, exist_ok=True)
        if not crosswalk_path.exists():
            crosswalk_path.write_text("[]", encoding="utf-8")

    print("\n[3/3] Building SQLite DB...")
    rc = subprocess.call([sys.executable, "-m", "scripts.build_ddinter_db", "build", "--tag", "ddinter-2.0"],
                         cwd=str(ref_dir), env=env)
    if rc != 0:
        print("Build failed.")
        return rc
    print(f"\nDONE. DDInter SQLite written to {DATA_DIR / 'ddinter.db'}")
    # Move it if pillchecker wrote to its own data/ folder
    pillchecker_data = ref_dir / "data" / "ddinter.db"
    our_db = DATA_DIR / "ddinter.db"
    if pillchecker_data.exists():
        if our_db.exists():
            our_db.unlink()
        pillchecker_data.rename(our_db)
    if our_db.exists():
        print(f"DB size: {our_db.stat().st_size / 1024 / 1024:.1f} MB")
    return 0


def _download_indic_stt() -> int:
    """Download AI4Bharat indic-conformer from HuggingFace."""
    try:
        from transformers import AutoProcessor, AutoModelForSpeechSeq2Seq
    except ImportError:
        print("ERROR: transformers + torch are required.")
        print("  pip install transformers torch torchaudio")
        return 1
    model_id = "ai4bharat/indic-conformer-600m-multilingual"
    target = DATA_DIR / "indic_conformer"
    target.mkdir(parents=True, exist_ok=True)
    print(f"\nDownloading {model_id} to {target} (~600 MB)...")
    print("This will take several minutes. Progress bars come from huggingface_hub.")
    proc = AutoProcessor.from_pretrained(model_id)
    proc.save_pretrained(str(target))
    model = AutoModelForSpeechSeq2Seq.from_pretrained(model_id)
    model.save_pretrained(str(target))
    print(f"\nDONE. Model saved to {target}")
    print("To enable it: set environment variable MV_ENABLE_INDIC_STT=1 and restart the backend.")
    return 0


def _check_ollama() -> int:
    import httpx
    url = os.environ.get("MV_OLLAMA_URL", "http://localhost:11434")
    print(f"\nChecking Ollama at {url} ...")
    try:
        r = httpx.get(f"{url}/api/tags", timeout=3.0)
        if r.status_code != 200:
            print(f"Ollama responded HTTP {r.status_code}")
            return 1
        tags = (r.json() or {}).get("models") or []
        if not tags:
            print("Ollama is running but no models are pulled.")
            print("  ollama pull meditron:7b")
            return 1
        print("Ollama is running. Available models:")
        for m in tags:
            print(f"  - {m.get('name')}  ({m.get('size', 0) // 1024**3} GB)")
        target = os.environ.get("MV_OLLAMA_MODEL", "meditron:7b")
        if any(target in (m.get("name") or "") for m in tags):
            print(f"\nTarget model {target} is READY.")
            print("To enable Meditron in /chat: set MV_ENABLE_MEDITRON=1 and restart the backend.")
            return 0
        print(f"\nTarget model {target} is NOT pulled.")
        print(f"  ollama pull {target}")
        return 1
    except Exception as e:
        print(f"Ollama not reachable: {e}")
        print("Install it from https://ollama.com/download and run `ollama serve`.")
        return 1


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    cmd = sys.argv[1]
    if cmd == "status":
        return _status()
    if cmd == "build-ddinter":
        return _build_ddinter()
    if cmd == "download-indic-stt":
        return _download_indic_stt()
    if cmd == "check-ollama":
        return _check_ollama()
    if cmd == "all":
        rc = 0
        for fn in (_build_ddinter, _download_indic_stt, _check_ollama):
            try:
                rc = fn() or rc
            except Exception as e:
                print(f"Step failed: {e}")
                rc = 1
        return rc
    print(f"Unknown command: {cmd}")
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
