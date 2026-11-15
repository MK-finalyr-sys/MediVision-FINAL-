"""
MediVision AI — Mandatory Regression Tests for Medicine Identification.

Verifies fixes for patient-safety identification bugs:
A. Damaged A-TRIP-10 OCR -> correct brand (A-TRIP-10), full ingredient (Amitriptyline), strength (10 mg), form (Tablet).
B. "Hydrochloride Tablets 10 mg" -> must NOT return a verified medicine (NO_MATCH).
C. "nitine Hydrochloride" -> must NOT produce an arbitrary homeopathic label.
D. Price for tramadol injection must NOT be returned for amitriptyline tablet.
E. Mismatched external drug labels must be excluded.
F. Unknown product must return unverified / NO_MATCH rather than fabricated info.
G. Valid external evidence must include the corresponding retrieved source URL.
H. Existing Dolo/Pantoprazole and DDInter behavior must not regress.
"""
from __future__ import annotations

import sys
from fastapi.testclient import TestClient

from app.main import app
from app import pipeline, candidates
from app.integrations import indian_pricing, ddinter

client = TestClient(app)


def test_a_damaged_atrip10():
    ocr = "nitine Hydrochloride Tablets I.P. 10 mg\nA-TRIP-10"
    resp = client.post("/identify", json={"ocrText": ocr})
    assert resp.status_code == 200, f"Status code {resp.status_code}"
    res = resp.json()
    assert res.get("found") is True, f"Expected found=True, got {res.get('found')}"
    assert res.get("brand") == "A-TRIP-10", f"Expected brand A-TRIP-10, got {res.get('brand')}"
    assert "Amitriptyline" in str(res.get("salt")), f"Expected Amitriptyline, got {res.get('salt')}"
    assert res.get("strength") == "10 mg", f"Expected 10 mg, got {res.get('strength')}"
    assert res.get("form") == "Tablet", f"Expected Tablet, got {res.get('form')}"
    assert res.get("manufacturer") == "Marc Cure", f"Expected Marc Cure, got {res.get('manufacturer')}"
    assert res.get("verificationStatus") == "verified-online", f"Expected verified-online, got {res.get('verificationStatus')}"


def test_b_hydrochloride_tablets():
    ocr = "Hydrochloride Tablets 10 mg"
    resp = client.post("/identify", json={"ocrText": ocr})
    assert resp.status_code == 200
    res = resp.json()
    assert res.get("found") is False, f"Expected found=False, got {res.get('found')}"
    assert res.get("note") == "NO_MATCH", f"Expected note=NO_MATCH, got {res.get('note')}"
    assert res.get("verificationStatus") == "none", f"Expected status=none, got {res.get('verificationStatus')}"


def test_c_nitine_hydrochloride():
    ocr = "nitine Hydrochloride"
    resp = client.post("/identify", json={"ocrText": ocr})
    assert resp.status_code == 200
    res = resp.json()
    assert res.get("found") is False, f"Expected found=False, got {res.get('found')}"
    assert res.get("note") == "NO_MATCH", f"Expected note=NO_MATCH, got {res.get('note')}"
    label = res.get("label") or {}
    assert not label.get("uses"), f"Expected no homeopathic label, got {label.get('uses')}"


def test_d_pricing_mismatch_prevention():
    pricing = indian_pricing.lookup_generic_price("Amitriptyline", "10 mg", "Tablet")
    assert pricing is not None, "Expected valid pricing for Amitriptyline 10 mg Tablet"
    assert "Amitriptyline" in pricing["brand"], f"Expected Amitriptyline in brand, got {pricing['brand']}"
    assert "Tramadol" not in pricing["brand"], f"Tramadol should NOT be in brand: {pricing['brand']}"
    assert "Injection" not in pricing["brand"], f"Injection should NOT be returned for tablet: {pricing['brand']}"
    # Verify Hydrochloride alone yields NO generic price
    hcl_pricing = indian_pricing.lookup_generic_price("Hydrochloride", "10 mg", "Tablet")
    assert hcl_pricing is None, f"Hydrochloride alone must return None, got {hcl_pricing}"


def test_e_mismatched_external_label_excluded():
    res_b = pipeline.identify("Hydrochloride Tablets 10 mg")
    label = res_b.get("label") or {}
    assert not label.get("uses"), "External drug label must NOT be returned for unverified chemical suffix"


def test_f_unknown_product_no_match():
    gibberish = "xyz999foobar completely unknown text 12345"
    res = pipeline.identify(gibberish)
    assert res.get("found") is False, f"Expected found=False, got {res.get('found')}"
    assert res.get("note") == "NO_MATCH", f"Expected note=NO_MATCH, got {res.get('note')}"
    cand = candidates.ranked_candidates(gibberish)
    assert cand.get("found") is False, f"Expected candidates found=False, got {cand.get('found')}"
    assert cand.get("candidates") == [], f"Expected empty candidates, got {cand.get('candidates')}"


def test_g_valid_evidence_includes_source_url():
    res = pipeline.identify("nitine Hydrochloride Tablets I.P. 10 mg\nA-TRIP-10")
    sources = res.get("sources", [])
    mfr_source = next((s for s in sources if s.get("sourceType") == "manufacturer"), None)
    assert mfr_source is not None, "Expected manufacturer source in sources"
    assert mfr_source.get("url") == "https://marccure.in/products/a-trip-10-amitriptyline-tablet", (
        f"Expected Marc Cure official URL, got {mfr_source.get('url')}"
    )


def test_h_existing_behavior_preserved():
    # Dolo 650
    res_dolo = pipeline.identify("Dolo 650 Tablet")
    assert res_dolo.get("found") is True
    assert res_dolo.get("salt") == "Paracetamol"
    assert res_dolo.get("strength") == "650 mg"

    # Pantoprazole
    res_panto = pipeline.identify("P.ntopra 40")
    assert res_panto.get("found") is True
    assert "Pantoprazole" in str(res_panto.get("salt"))

    # DDInter aspirin + warfarin interaction
    ddi = ddinter.check_pair("aspirin", "warfarin")
    assert ddi is not None
    assert ddi.get("level") in ("Major", "Moderate", "CRITICAL", "WARN")


if __name__ == "__main__":
    print("Running Regression Test Suite A-H...")
    test_a_damaged_atrip10()
    print("PASS: Test A (Damaged A-TRIP-10 OCR)")
    test_b_hydrochloride_tablets()
    print("PASS: Test B (Hydrochloride Tablets 10 mg -> NO_MATCH)")
    test_c_nitine_hydrochloride()
    print("PASS: Test C (nitine Hydrochloride -> No homeopathic label)")
    test_d_pricing_mismatch_prevention()
    print("PASS: Test D (No Tramadol injection pricing for Amitriptyline tablet)")
    test_e_mismatched_external_label_excluded()
    print("PASS: Test E (Mismatched external drug labels excluded)")
    test_f_unknown_product_no_match()
    print("PASS: Test F (Unknown product returns NO_MATCH)")
    test_g_valid_evidence_includes_source_url()
    print("PASS: Test G (Valid evidence includes real source URL)")
    test_h_existing_behavior_preserved()
    print("PASS: Test H (Existing Dolo, Pantoprazole, and DDInter preserved)")
    print("\nALL 8 REGRESSION TESTS PASSED CLEANLY!")
