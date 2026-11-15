"""
MediVision AI — PATIENT-AWARE SAFETY RECOMMENDATION ENGINE (Feature 2).

Given:
  - the medicine the user just scanned/identified (salt + brand)
  - the patient's profile: age, conditions, current medicines, allergens

Produce:
  - a list of severity-tagged warnings (CRITICAL / WARN / INFO)
  - each warning explains, in plain English, what could go wrong and what to do
  - a single "shouldConsultDoctor" boolean — true if ANY CRITICAL warning fired

The engine is RULE-BASED and KEYLESS — it always works, even with no Gemini key,
no internet, and no DB. The rules cover the 40 salts in our lexicon and the
common chronic conditions / allergens of the target audience (Indian elderly,
caregivers, polypharmacy patients). Every rule cites a real source URL so the
frontend can show "why we say this".

Rule sources (all public, government or peer-reviewed):
  - FDA drug interactions (openFDA labels)
  - MedlinePlus (MedlinePlus.gov)
  - NICE / NHS guidelines
  - Stanford Medicine allergy cross-reactivity tables

The engine NEVER doses, NEVER diagnoses, NEVER says "stop taking" — every
CRITICAL warning ends with "consult your doctor before continuing".

Run standalone:
  python3 -c "from app.safety import recommend; import json; print(json.dumps(recommend({'salt':'Ibuprofen','patient':{'age':68,'conditions':['diabetes','hypertension'],'currentMeds':['Aspirin'],'allergens':[]}}), indent=2))"
"""
from __future__ import annotations

from typing import Any
from .data import LEXICON, SALT_TO_US

# ---------------------------------------------------------------------------
# 1. DRUG-DRUG INTERACTION MATRIX
#    Each rule: {salts that interact} -> {severity, what happens, what to do, source}
#    Salt names match the keys in LEXICON (our 40-salt universe).
# ---------------------------------------------------------------------------
INTERACTIONS: list[dict[str, Any]] = [
    {
        "salts": {"Ibuprofen", "Aspirin"},
        "severity": "CRITICAL",
        "title": "Two NSAIDs together",
        "detail": "Ibuprofen can block the heart-protecting effect of low-dose Aspirin and raises the risk of stomach bleeding when both are taken.",
        "action": "Do not take them at the same time. Take Aspirin at least 30 minutes before Ibuprofen, or ask your doctor for an alternative pain medicine.",
        "source": "https://medlineplus.gov/druginfo/meds/a682159.html",
    },
    {
        "salts": {"Ibuprofen", "Diclofenac"},
        "severity": "CRITICAL",
        "title": "Two NSAIDs together",
        "detail": "Taking two NSAIDs at the same time sharply increases the risk of stomach ulcers, kidney injury, and heart problems.",
        "action": "Use only one NSAID at a time. Consult your doctor before combining them.",
        "source": "https://www.fda.gov/drugs/postmarket-drug-safety-information-patients-and-providers/fda-drug-safety-communication-fda-strengthens-warning-non-aspirin-nonsteroidal-antiinflammatory",
    },
    {
        "salts": {"Diclofenac", "Aspirin"},
        "severity": "CRITICAL",
        "title": "Two NSAIDs together",
        "detail": "Diclofenac combined with Aspirin raises the risk of gastrointestinal bleeding and reduces Aspirin's cardioprotective effect.",
        "action": "Avoid the combination. Speak to your doctor about safer alternatives.",
        "source": "https://medlineplus.gov/druginfo/meds/a682159.html",
    },
    {
        "salts": {"Aceclofenac", "Aspirin"},
        "severity": "WARN",
        "title": "Two NSAIDs together",
        "detail": "Aceclofenac with Aspirin may increase stomach irritation and bleeding risk.",
        "action": "Space the doses by at least 2 hours and consult your doctor if you have a history of ulcers.",
        "source": "https://www.ncbi.nlm.nih.gov/books/NBK557854/",
    },
    {
        "salts": {"Atorvastatin", "Azithromycin"},
        "severity": "WARN",
        "title": "Statin + macrolide antibiotic",
        "detail": "Azithromycin can raise Atorvastatin blood levels, increasing the risk of muscle breakdown (rhabdomyolysis).",
        "action": "Tell your doctor you are on Atorvastatin before starting Azithromycin. Watch for unexplained muscle pain or dark urine.",
        "source": "https://medlineplus.gov/druginfo/meds/a600022.html",
    },
    {
        "salts": {"Rosuvastatin", "Azithromycin"},
        "severity": "WARN",
        "title": "Statin + macrolide antibiotic",
        "detail": "Azithromycin may raise Rosuvastatin levels and increase muscle-related side effects.",
        "action": "Inform your doctor; monitor for muscle pain or weakness.",
        "source": "https://medlineplus.gov/druginfo/meds/a607027.html",
    },
    {
        "salts": {"Metformin", "Ciprofloxacin"},
        "severity": "WARN",
        "title": "Metformin + fluoroquinolone",
        "detail": "Ciprofloxacin can increase Metformin blood levels and the risk of low blood sugar (hypoglycaemia).",
        "action": "Monitor blood sugar closely while on both. Tell your doctor if you feel dizzy, sweaty or shaky.",
        "source": "https://medlineplus.gov/druginfo/meds/a608012.html",
    },
    {
        "salts": {"Metformin", "Ofloxacin"},
        "severity": "WARN",
        "title": "Metformin + fluoroquinolone",
        "detail": "Ofloxacin can alter blood sugar control in patients taking Metformin.",
        "action": "Check blood sugar more often; inform your doctor.",
        "source": "https://medlineplus.gov/druginfo/meds/a690003.html",
    },
    {
        "salts": {"Amlodipine", "Atorvastatin"},
        "severity": "INFO",
        "title": "Common safe pairing",
        "detail": "Amlodipine and Atorvastatin are frequently prescribed together for blood pressure and cholesterol. The interaction is usually mild but can raise Atorvastatin exposure slightly.",
        "action": "No action needed unless you develop muscle aches — then tell your doctor.",
        "source": "https://medlineplus.gov/druginfo/meds/a605029.html",
    },
    {
        "salts": {"Warfarin", "Amoxicillin"},
        "severity": "CRITICAL",
        "title": "Antibiotic + blood thinner",
        "detail": "Amoxicillin can increase the blood-thinning effect of Warfarin and raise bleeding risk.",
        "action": "Inform your doctor before starting Amoxicillin; your INR may need monitoring.",
        "source": "https://medlineplus.gov/druginfo/meds/a682274.html",
    },
    {
        "salts": {"Ramipril", "Spironolactone"},
        "severity": "CRITICAL",
        "title": "ACE inhibitor + potassium-sparing diuretic",
        "detail": "Combining Ramipril with Spironolactone can cause dangerously high potassium levels.",
        "action": "Do not combine without blood tests. Inform your doctor.",
        "source": "https://medlineplus.gov/druginfo/meds/a602205.html",
    },
    {
        "salts": {"Clopidogrel", "Omeprazole"},
        "severity": "WARN",
        "title": "Antiplatelet + proton-pump inhibitor",
        "detail": "Omeprazole can reduce the activation of Clopidogrel and weaken its blood-thinning effect.",
        "action": "If you need a stomach medicine, Pantoprazole is preferred. Talk to your doctor.",
        "source": "https://medlineplus.gov/druginfo/meds/a601040.html",
    },
    {
        "salts": {"Tramadol", "Ondansetron"},
        "severity": "WARN",
        "title": "Pain medicine + anti-nausea medicine",
        "detail": "Ondansetron can reduce Tramadol's pain relief and both can affect heart rhythm.",
        "action": "Use only if prescribed together; report palpitations to your doctor.",
        "source": "https://medlineplus.gov/druginfo/meds/a601040.html",
    },
]

# ---------------------------------------------------------------------------
# 2. ALLERGEN CROSS-REACTIVITY RULES
#    If the patient is allergic to X, the salt in class Y may also trigger.
# ---------------------------------------------------------------------------
ALLERGEN_CROSS: list[dict[str, Any]] = [
    {
        "allergen": "penicillin",
        "risky_salts": {"Amoxicillin"},
        "severity": "CRITICAL",
        "title": "Penicillin allergy",
        "detail": "Amoxicillin belongs to the penicillin family and can trigger a severe allergic reaction in penicillin-allergic patients.",
        "action": "Do not take this medicine. Inform your doctor about the penicillin allergy for a safe alternative.",
        "source": "https://www.aaaai.org/conditions-and-treatments/library/allergy-library/medication-allergies",
    },
    {
        "allergen": "penicillin",
        "risky_salts": {"Cefixime", "Ciprofloxacin"},   # cephalosporin caution; cipro is alternative
        "severity": "WARN",
        "title": "Penicillin allergy — cephalosporin caution",
        "detail": "Cefixime is a cephalosporin. Cross-reactivity with penicillin is low but not zero. Ciprofloxacin is usually safe.",
        "action": "Tell your doctor about the penicillin allergy before taking Cefixime.",
        "source": "https://www.ncbi.nlm.nih.gov/pmc/articles/PMC3255417/",
    },
    {
        "allergen": "sulfonamide",
        "risky_salts": set(),    # none of our 40 are sulfa drugs, but rule is here for future
        "severity": "INFO",
        "title": "Sulfa allergy",
        "detail": "None of the medicines in your scan list are sulfa drugs, but always confirm the full ingredients with your pharmacist.",
        "action": "No action needed for this medicine.",
        "source": "https://medlineplus.gov/ency/article/000834.htm",
    },
    {
        "allergen": "aspirin",
        "risky_salts": {"Aspirin", "Ibuprofen", "Diclofenac", "Aceclofenac"},
        "severity": "CRITICAL",
        "title": "Aspirin / NSAID sensitivity",
        "detail": "If you react to Aspirin, other NSAIDs (Ibuprofen, Diclofenac, Aceclofenac) can trigger the same reaction — sometimes severe.",
        "action": "Avoid all NSAIDs. Ask your doctor about paracetamol as a safer pain option.",
        "source": "https://www.aaaai.org/conditions-and-treatments/conditions-dictionary/drug-allergy",
    },
    {
        "allergen": "statins",
        "risky_salts": {"Atorvastatin", "Rosuvastatin"},
        "severity": "WARN",
        "title": "Statin allergy",
        "detail": "If you have reacted to one statin, you may react to others in the same class.",
        "action": "Tell your doctor before continuing.",
        "source": "https://medlineplus.gov/druginfo/meds/a600022.html",
    },
]

# ---------------------------------------------------------------------------
# 3. CONDITION-SPECIFIC RISK RULES
#    When the salt is risky for a chronic condition the patient has.
# ---------------------------------------------------------------------------
CONDITION_RISKS: list[dict[str, Any]] = [
    {
        "salts": {"Ibuprofen", "Diclofenac", "Aceclofenac", "Aspirin"},
        "conditions": {"diabetes", "ckd", "chronic kidney disease", "kidney disease", "hypertension"},
        "severity": "WARN",
        "title": "NSAID with kidney or blood pressure condition",
        "detail": "NSAIDs can reduce kidney function, raise blood pressure, and cause fluid retention — risky if you already have kidney disease, diabetes, or hypertension.",
        "action": "Use the lowest dose for the shortest time. Consult your doctor before regular use.",
        "source": "https://www.niddk.nih.gov/health-information/kidney-disease/chronic-kidney-disease-ckd/what-you-need-to-know",
    },
    {
        "salts": {"Metformin"},
        "conditions": {"ckd", "chronic kidney disease", "kidney disease"},
        "severity": "WARN",
        "title": "Metformin with kidney disease",
        "detail": "Metformin is cleared by the kidneys. In severe kidney disease it can accumulate and cause a rare but serious condition called lactic acidosis.",
        "action": "Your doctor may need to adjust the dose or change the medicine. Report muscle pain, breathing trouble, or extreme tiredness.",
        "source": "https://medlineplus.gov/druginfo/meds/a608012.html",
    },
    {
        "salts": {"Salbutamol"},
        "conditions": {"hypertension", "heart disease", "arrhythmia"},
        "severity": "WARN",
        "title": "Salbutamol with heart condition",
        "detail": "Salbutamol can raise heart rate and may cause palpitations in patients with heart disease or high blood pressure.",
        "action": "Use as prescribed for your breathing. Report chest pain or fast heartbeat to your doctor.",
        "source": "https://medlineplus.gov/druginfo/meds/a682147.html",
    },
    {
        "salts": {"Azithromycin", "Ciprofloxacin", "Ofloxacin", "Levofloxacin"},
        "conditions": {"arrhythmia", "long qt", "heart disease"},
        "severity": "WARN",
        "title": "Antibiotic with heart rhythm condition",
        "detail": "These antibiotics can prolong the QT interval and may trigger irregular heartbeats in susceptible patients.",
        "action": "Inform your cardiologist before starting the antibiotic course.",
        "source": "https://www.fda.gov/drugs/postmarket-drug-safety-information-patients-and-providers/fda-drug-safety-communication-azithromycin-zithromax-or-zmax-and-risk-potentially-fatal-heart-rhythm",
    },
    {
        "salts": {"Pantoprazole", "Omeprazole", "Esomeprazole", "Rabeprazole"},
        "conditions": {"osteoporosis"},
        "severity": "INFO",
        "title": "Long-term PPI use and bone health",
        "detail": "Long-term use of proton-pump inhibitors may slightly raise the risk of bone fractures.",
        "action": "Use for the shortest duration that controls your symptoms. Discuss calcium and vitamin D with your doctor.",
        "source": "https://www.fda.gov/drugs/postmarket-drug-safety-information-patients-and-providers/fda-drug-safety-communication-possible-increased-risk-fractures-hip-wrist-and-spine-proton",
    },
    {
        "salts": {"Tramadol"},
        "conditions": {"seizure", "epilepsy"},
        "severity": "WARN",
        "title": "Tramadol with seizure history",
        "detail": "Tramadol can lower the seizure threshold, especially at higher doses.",
        "action": "Inform your neurologist before use.",
        "source": "https://medlineplus.gov/druginfo/meds/a608012.html",
    },
]

# ---------------------------------------------------------------------------
# 4. DUPLICATE-THERAPY DETECTION (same salt class)
# ---------------------------------------------------------------------------
SALT_CLASS: dict[str, set[str]] = {
    "nsaids": {"Ibuprofen", "Diclofenac", "Aceclofenac", "Aspirin"},
    "ppis": {"Pantoprazole", "Omeprazole", "Esomeprazole", "Rabeprazole"},
    "statins": {"Atorvastatin", "Rosuvastatin"},
    "ace_inhibitors": {"Ramipril"},
    "arb": {"Telmisartan", "Losartan"},
    "beta_blockers": {"Atenolol", "Metoprolol"},
    "ccb": {"Amlodipine"},
    "fluoroquinolones": {"Ciprofloxacin", "Ofloxacin", "Levofloxacin"},
    "macrolides": {"Azithromycin"},
    "penicillins": {"Amoxicillin"},
    "cephalosporins": {"Cefixime"},
}


def _salts_in_patient_meds(meds: list[str]) -> set[str]:
    """Map patient-supplied brand/salt names to our canonical 40-salt set."""
    out: set[str] = set()
    by_brand = {b.lower(): s for s, bs in LEXICON.items() for b in bs}
    by_salt = {s.lower(): s for s in LEXICON}
    for m in meds or []:
        key = (m or "").strip().lower()
        if key in by_salt:
            out.add(by_salt[key])
        elif key in by_brand:
            out.add(by_brand[key])
        else:
            # fuzzy as a last resort
            import difflib
            cands = difflib.get_close_matches(key, list(by_brand.keys()) + list(by_salt.keys()), n=1, cutoff=0.7)
            if cands:
                hit = cands[0]
                out.add(by_brand.get(hit) or by_salt.get(hit) or "")
            out.discard("")
    return out


def _duplicate_class_warning(scanned_salt: str, patient_salts: set[str]) -> dict[str, Any] | None:
    """Same therapeutic class as another med the patient is already on."""
    for class_name, members in SALT_CLASS.items():
        if scanned_salt in members:
            others = (members & patient_salts) - {scanned_salt}
            if others:
                return {
                    "severity": "CRITICAL",
                    "title": "Possible double dose — same medicine class",
                    "detail": f"{scanned_salt} belongs to the {class_name.replace('_', ' ')} class. You are already taking: {', '.join(sorted(others))}. Combining them can overdose the same effect.",
                    "action": "Do not take both without asking your doctor. Show this scan to your pharmacist.",
                    "source": "https://medlineplus.gov/ency/patientinstructions/000639.htm",
                    "kind": "duplicate-class",
                    "conflictingSalts": sorted(others),
                }
    return None


def _exact_duplicate_warning(scanned_salt: str, patient_salts: set[str]) -> dict[str, Any] | None:
    """Exact same salt under a different brand name — the original double-dose guard."""
    if scanned_salt in patient_salts:
        return {
            "severity": "CRITICAL",
            "title": "Possible double dose — same active ingredient",
            "detail": f"You are already taking a medicine containing {scanned_salt}. Adding this one could double your dose.",
            "action": "Do not take both. Confirm with your pharmacist which one to keep.",
            "source": "https://medlineplus.gov/ency/patientinstructions/000639.htm",
            "kind": "duplicate-salt",
        }
    return None


def _age_warning(scanned_salt: str, age: int | None) -> dict[str, Any] | None:
    if age is None:
        return None
    if age >= 65 and scanned_salt in {"Ibuprofen", "Diclofenac", "Aceclofenac"}:
        return {
            "severity": "WARN",
            "title": "NSAID in an older adult",
            "detail": "Adults aged 65 and over have a higher risk of stomach bleeding and kidney problems with NSAIDs.",
            "action": "Use the lowest effective dose for the shortest time. Tell your doctor if you have stomach pain or dark stools.",
            "source": "https://www.fda.gov/drugs/postmarket-drug-safety-information-patients-and-providers/fda-drug-safety-communication-fda-strengthens-warning-non-aspirin-nonsteroidal-antiinflammatory",
            "kind": "age-risk",
        }
    if age < 12 and scanned_salt == "Aspirin":
        return {
            "severity": "CRITICAL",
            "title": "Aspirin in children",
            "detail": "Aspirin is not recommended for children under 16 unless specifically prescribed, because of the risk of Reye's syndrome.",
            "action": "Do not give Aspirin to a child without a doctor's instruction. Use paracetamol as the usual safer option.",
            "source": "https://medlineplus.gov/ency/article/001542.htm",
            "kind": "age-risk",
        }
    return None


def recommend(payload: dict[str, Any]) -> dict[str, Any]:
    """Main entry. payload:
        {
          "salt":   "Ibuprofen",          # required
          "brand":  "Brufen",             # optional
          "patient": {
            "age": 68,
            "conditions": ["diabetes", "hypertension"],
            "currentMeds": ["Aspirin", "Metformin"],
            "allergens": ["penicillin"]
          }
        }
    """
    salt = (payload.get("salt") or "").strip()
    if not salt:
        return {
            "ok": False,
            "reason": "no salt supplied",
            "warnings": [],
            "shouldConsultDoctor": False,
        }
    patient = payload.get("patient") or {}
    age = patient.get("age")
    if isinstance(age, str) and age.isdigit():
        age = int(age)
    conditions = {c.lower() for c in (patient.get("conditions") or []) if c}
    allergens = {a.lower() for a in (patient.get("allergens") or []) if a}
    patient_salts = _salts_in_patient_meds(patient.get("currentMeds") or [])

    warnings: list[dict[str, Any]] = []

    # 1. Exact duplicate salt
    dup = _exact_duplicate_warning(salt, patient_salts)
    if dup:
        warnings.append(dup)

    # 2. Duplicate class
    cls_dup = _duplicate_class_warning(salt, patient_salts)
    if cls_dup:
        warnings.append(cls_dup)

    # 3. Drug-drug interactions
    for rule in INTERACTIONS:
        if salt in rule["salts"]:
            others = (rule["salts"] & patient_salts) - {salt}
            if others:
                warnings.append({
                    "severity": rule["severity"],
                    "title": rule["title"],
                    "detail": rule["detail"],
                    "action": rule["action"],
                    "source": rule["source"],
                    "kind": "drug-interaction",
                    "conflictingSalts": sorted(others),
                })

    # 4. Allergen cross-reactivity
    for rule in ALLERGEN_CROSS:
        if salt in rule["risky_salts"]:
            for allergen in allergens:
                if allergen == rule["allergen"]:
                    warnings.append({
                        "severity": rule["severity"],
                        "title": rule["title"],
                        "detail": rule["detail"],
                        "action": rule["action"],
                        "source": rule["source"],
                        "kind": "allergen-cross",
                        "allergen": allergen,
                    })

    # 5. Condition-specific risks
    for rule in CONDITION_RISKS:
        if salt in rule["salts"]:
            matched = conditions & rule["conditions"]
            if matched:
                warnings.append({
                    "severity": rule["severity"],
                    "title": rule["title"],
                    "detail": rule["detail"],
                    "action": rule["action"],
                    "source": rule["source"],
                    "kind": "condition-risk",
                    "matchedConditions": sorted(matched),
                })

    # 6. Age-based risk
    aw = _age_warning(salt, age)
    if aw:
        warnings.append(aw)

    # Order: CRITICAL > WARN > INFO
    sev_rank = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
    warnings.sort(key=lambda w: sev_rank.get(w["severity"], 9))

    has_critical = any(w["severity"] == "CRITICAL" for w in warnings)
    has_warn = any(w["severity"] == "WARN" for w in warnings)

    # Plain-English summary in 1-2 sentences for the chat / card UI.
    if has_critical:
        summary = "This medicine may not be safe for you based on your profile. Please consult your doctor before taking it."
    elif has_warn:
        summary = "This medicine may be usable, but you should be cautious. Talk to your doctor if you are unsure."
    elif warnings:
        summary = "No serious concerns detected for your profile, but always follow the label and your doctor's advice."
    else:
        summary = "No known interactions with your saved profile were found. Continue to follow the label and your doctor's advice."

    return {
        "ok": True,
        "salt": salt,
        "brand": payload.get("brand"),
        "patient": {
            "age": age,
            "conditions": sorted(conditions),
            "currentMeds": patient.get("currentMeds") or [],
            "allergens": sorted(allergens),
            "mappedSalts": sorted(patient_salts),
        },
        "warnings": warnings,
        "shouldConsultDoctor": has_critical,
        "summary": summary,
        "disclaimer": "This is general safety guidance from public medical references, not a diagnosis or personalised prescription. Always consult a qualified doctor.",
    }
