"use client";
import { useState, useEffect } from "react";
import {
  ShieldAlert,
  ShieldCheck,
  AlertTriangle,
  Info,
  ExternalLink,
  Plus,
  X,
  Search,
  User,
  HeartPulse,
  Pill,
  Sparkles,
  LoaderCircle,
  RotateCcw,
  Stethoscope,
} from "lucide-react";
import { medicines } from "@/lib/catalog";
import type { SavedMedicine, Medicine } from "@/lib/contracts";
import type { View } from "./dashboard";
import {
  aiRecommend,
  type RecommendResult,
  type SafetyWarning,
  type PatientProfile,
} from "@/lib/ai-backend";

interface SafetyCheckerProps {
  saved: SavedMedicine[];
  initialMedicine?: Medicine | null;
  onOpenMedicine?: (m: Medicine) => void;
  onNavigate?: (view: View) => void;
}

const COMMON_CONDITIONS = [
  "Hypertension",
  "Type 2 Diabetes",
  "Chronic Kidney Disease",
  "Peptic Ulcer",
  "Asthma",
  "Liver Disease",
  "Heart Disease",
];

const COMMON_ALLERGENS = [
  "Penicillin",
  "Aspirin",
  "NSAIDs",
  "Sulfa antibiotics",
  "Paracetamol",
];

export function SafetyCheckerView({
  saved,
  initialMedicine,
  onOpenMedicine,
}: SafetyCheckerProps) {
  // Target medicine to check
  const [targetName, setTargetName] = useState(
    initialMedicine?.name || initialMedicine?.activeIngredient || ""
  );
  const [targetSalt, setTargetSalt] = useState(
    initialMedicine?.activeIngredient || ""
  );
  const [searchQuery, setSearchQuery] = useState("");
  const [showDropdown, setShowDropdown] = useState(false);

  // Patient profile
  const [age, setAge] = useState<string>("");
  const [conditions, setConditions] = useState<string[]>([]);
  const [customCondition, setCustomCondition] = useState("");
  const [allergens, setAllergens] = useState<string[]>([]);
  const [customAllergen, setCustomAllergen] = useState("");
  const [currentMeds, setCurrentMeds] = useState<string[]>(() =>
    saved
      .map((s) => medicines.find((m) => m.id === s.id)?.name)
      .filter((name): name is string => !!name)
  );
  const [customMed, setCustomMed] = useState("");

  // Analysis state
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<RecommendResult | null>(null);
  const [hasSearched, setHasSearched] = useState(false);
  const [serviceOffline, setServiceOffline] = useState(false);

  function handleSelectMedicine(m: Medicine) {
    setTargetName(m.name);
    setTargetSalt(m.activeIngredient);
    setSearchQuery("");
    setShowDropdown(false);
  }

  function toggleCondition(cond: string) {
    setConditions((prev) =>
      prev.includes(cond) ? prev.filter((c) => c !== cond) : [...prev, cond]
    );
  }

  function addCustomCondition() {
    const val = customCondition.trim();
    if (val && !conditions.includes(val)) {
      setConditions((prev) => [...prev, val]);
      setCustomCondition("");
    }
  }

  function toggleAllergen(allg: string) {
    setAllergens((prev) =>
      prev.includes(allg) ? prev.filter((a) => a !== allg) : [...prev, allg]
    );
  }

  function addCustomAllergen() {
    const val = customAllergen.trim();
    if (val && !allergens.includes(val)) {
      setAllergens((prev) => [...prev, val]);
      setCustomAllergen("");
    }
  }

  function toggleMed(med: string) {
    setCurrentMeds((prev) =>
      prev.includes(med) ? prev.filter((m) => m !== med) : [...prev, med]
    );
  }

  function addCustomMed() {
    const val = customMed.trim();
    if (val && !currentMeds.includes(val)) {
      setCurrentMeds((prev) => [...prev, val]);
      setCustomMed("");
    }
  }

  async function runSafetyCheck() {
    const saltToCheck = targetSalt.trim() || targetName.trim();
    if (!saltToCheck) return;

    setLoading(true);
    setHasSearched(true);
    setServiceOffline(false);
    setResult(null);

    const patientProfile: PatientProfile = {
      age: age ? parseInt(age, 10) : undefined,
      conditions,
      allergens,
      currentMeds,
    };

    try {
      const res = await aiRecommend(saltToCheck, targetName, patientProfile);
      if (!res || res.available === false || !res.ok) {
        setServiceOffline(true);
        setResult(res);
      } else {
        setResult(res);
      }
    } catch {
      setServiceOffline(true);
    } finally {
      setLoading(false);
    }
  }

  const filteredMedicines = searchQuery.trim()
    ? medicines.filter(
        (m) =>
          m.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
          m.activeIngredient.toLowerCase().includes(searchQuery.toLowerCase())
      )
    : [];

  const criticalWarnings =
    result?.warnings.filter((w) => w.severity === "CRITICAL") || [];
  const warnWarnings =
    result?.warnings.filter((w) => w.severity === "WARN") || [];
  const infoWarnings =
    result?.warnings.filter((w) => w.severity === "INFO") || [];

  return (
    <div className="safety-checker-page page-enter">
      <div className="page-heading">
        <div>
          <p className="eyebrow">PATIENT-AWARE SAFETY CHECK</p>
          <h1>Personal Safety Checker</h1>
          <p>
            Cross-check a medicine against your age, health conditions, current
            prescriptions and allergies before taking it.
          </p>
        </div>
        <span className="pill-badge">
          <ShieldCheck size={16} /> DDInter + OpenFDA rules
        </span>
      </div>

      <div className="safety-grid">
        {/* Left Column: Form & Profile */}
        <section className="panel safety-form-panel">
          <div className="section-title">
            <span className="icon-tile blue">
              <Pill size={22} />
            </span>
            <div>
              <h2>1. Medicine to Check</h2>
              <p>Select from catalog or enter medicine name / salt</p>
            </div>
          </div>

          <div className="medicine-select-box">
            <div className="target-input-row">
              <label className="search-field">
                <Search size={18} />
                <input
                  type="text"
                  placeholder="e.g. Brufen, Metformin, Dolo 650..."
                  value={targetName}
                  onChange={(e) => {
                    setTargetName(e.target.value);
                    setTargetSalt(e.target.value);
                  }}
                  onFocus={() => setShowDropdown(true)}
                />
                {targetName && (
                  <button
                    type="button"
                    className="icon-button"
                    onClick={() => {
                      setTargetName("");
                      setTargetSalt("");
                    }}
                  >
                    <X size={16} />
                  </button>
                )}
              </label>
            </div>

            {targetSalt && targetSalt !== targetName && (
              <span className="salt-hint-badge">
                Active Salt: <strong>{targetSalt}</strong>
              </span>
            )}

            {showDropdown && (
              <div className="medicine-dropdown">
                <div className="dropdown-search">
                  <input
                    type="text"
                    placeholder="Search catalog medicines..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    autoFocus
                  />
                  <button
                    type="button"
                    className="text-button"
                    onClick={() => setShowDropdown(false)}
                  >
                    Close
                  </button>
                </div>
                <div className="dropdown-list">
                  {(searchQuery ? filteredMedicines : medicines.slice(0, 8)).map(
                    (m) => (
                      <button
                        key={m.id}
                        type="button"
                        className="dropdown-item"
                        onClick={() => handleSelectMedicine(m)}
                      >
                        <div>
                          <strong>{m.name}</strong>
                          <small>
                            {m.activeIngredient} · {m.strength}
                          </small>
                        </div>
                        <Plus size={16} />
                      </button>
                    )
                  )}
                </div>
              </div>
            )}
          </div>

          <hr className="form-divider" />

          <div className="section-title">
            <span className="icon-tile mint">
              <User size={22} />
            </span>
            <div>
              <h2>2. Patient Profile</h2>
              <p>Tailor checks to your personal health background</p>
            </div>
          </div>

          {/* Age Input */}
          <div className="form-field-group">
            <label htmlFor="patient-age">Patient Age (years)</label>
            <input
              id="patient-age"
              type="number"
              min="0"
              max="120"
              placeholder="e.g. 68 (flags age-specific cautions)"
              value={age}
              onChange={(e) => setAge(e.target.value)}
              className="text-input age-input"
            />
          </div>

          {/* Pre-existing Conditions */}
          <div className="form-field-group">
            <label>Health Conditions</label>
            <div className="tag-chips">
              {COMMON_CONDITIONS.map((c) => {
                const active = conditions.includes(c);
                return (
                  <button
                    key={c}
                    type="button"
                    className={`tag-chip ${active ? "active" : ""}`}
                    onClick={() => toggleCondition(c)}
                  >
                    {active ? <X size={13} /> : <Plus size={13} />}
                    {c}
                  </button>
                );
              })}
              {conditions
                .filter((c) => !COMMON_CONDITIONS.includes(c))
                .map((c) => (
                  <button
                    key={c}
                    type="button"
                    className="tag-chip custom active"
                    onClick={() => toggleCondition(c)}
                  >
                    <X size={13} />
                    {c}
                  </button>
                ))}
            </div>
            <div className="custom-input-row">
              <input
                type="text"
                placeholder="Add other condition..."
                value={customCondition}
                onChange={(e) => setCustomCondition(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addCustomCondition()}
              />
              <button
                type="button"
                className="button compact secondary"
                onClick={addCustomCondition}
                disabled={!customCondition.trim()}
              >
                Add
              </button>
            </div>
          </div>

          {/* Current Medicines */}
          <div className="form-field-group">
            <label>Currently Taking</label>
            <p className="field-hint">
              {saved.length > 0
                ? "Preloaded from your saved medicines cabinet. Tap to include or exclude."
                : "Add other medicines you take regularly to check for drug-drug interactions."}
            </p>
            <div className="tag-chips">
              {currentMeds.map((med) => (
                <button
                  key={med}
                  type="button"
                  className="tag-chip active med-chip"
                  onClick={() => toggleMed(med)}
                >
                  <X size={13} />
                  {med}
                </button>
              ))}
            </div>
            <div className="custom-input-row">
              <input
                type="text"
                placeholder="Add current medicine (e.g. Aspirin)..."
                value={customMed}
                onChange={(e) => setCustomMed(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addCustomMed()}
              />
              <button
                type="button"
                className="button compact secondary"
                onClick={addCustomMed}
                disabled={!customMed.trim()}
              >
                Add
              </button>
            </div>
          </div>

          {/* Known Allergies */}
          <div className="form-field-group">
            <label>Known Drug Allergies</label>
            <div className="tag-chips">
              {COMMON_ALLERGENS.map((a) => {
                const active = allergens.includes(a);
                return (
                  <button
                    key={a}
                    type="button"
                    className={`tag-chip ${active ? "active danger-tag" : ""}`}
                    onClick={() => toggleAllergen(a)}
                  >
                    {active ? <X size={13} /> : <Plus size={13} />}
                    {a}
                  </button>
                );
              })}
              {allergens
                .filter((a) => !COMMON_ALLERGENS.includes(a))
                .map((a) => (
                  <button
                    key={a}
                    type="button"
                    className="tag-chip custom active danger-tag"
                    onClick={() => toggleAllergen(a)}
                  >
                    <X size={13} />
                    {a}
                  </button>
                ))}
            </div>
            <div className="custom-input-row">
              <input
                type="text"
                placeholder="Add allergen (e.g. Sulfa)..."
                value={customAllergen}
                onChange={(e) => setCustomAllergen(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && addCustomAllergen()}
              />
              <button
                type="button"
                className="button compact secondary"
                onClick={addCustomAllergen}
                disabled={!customAllergen.trim()}
              >
                Add
              </button>
            </div>
          </div>

          <button
            type="button"
            className="button primary full-width run-check-button"
            onClick={runSafetyCheck}
            disabled={loading || !targetName.trim()}
          >
            {loading ? (
              <>
                <LoaderCircle size={18} className="spin" />
                Analyzing interactions & risks...
              </>
            ) : (
              <>
                <ShieldCheck size={18} />
                Run Personal Safety Check
              </>
            )}
          </button>
        </section>

        {/* Right Column: Safety Report */}
        <section className="safety-results-panel">
          {!hasSearched && (
            <div className="panel safety-empty-card">
              <div className="empty-illustration">
                <HeartPulse size={44} strokeWidth={1.5} />
              </div>
              <h2>Ready for your safety assessment</h2>
              <p>
                Enter the medicine name and specify patient background on the
                left, then click <strong>Run Personal Safety Check</strong>.
              </p>
              <div className="safety-explainer-list">
                <div>
                  <ShieldAlert size={18} className="text-red" />
                  <span>
                    <strong>Drug-Drug Interactions:</strong> Checks against
                    DDInter database & published clinical rules.
                  </span>
                </div>
                <div>
                  <AlertTriangle size={18} className="text-amber" />
                  <span>
                    <strong>Condition Risks:</strong> Flags medications that may
                    worsen existing conditions (e.g. NSAIDs in CKD).
                  </span>
                </div>
                <div>
                  <Info size={18} className="text-blue" />
                  <span>
                    <strong>Allergens & Duplicates:</strong> Prevents duplicate
                    therapies and cross-reactive allergic triggers.
                  </span>
                </div>
              </div>
            </div>
          )}

          {loading && (
            <div className="panel safety-loading-card">
              <LoaderCircle size={36} className="spin text-blue" />
              <h3>Evaluating Clinical Evidence...</h3>
              <p>
                Querying DDInter interaction tables, OpenFDA contraindications,
                and rule engines for {targetName}...
              </p>
            </div>
          )}

          {/* CRITICAL HONESTY RULE: When service is offline, NEVER claim clearance */}
          {serviceOffline && !loading && (
            <div className="notice error safety-critical-notice" role="alert">
              <ShieldAlert size={28} />
              <div>
                <h3>Safety Analysis Engine Offline or Incomplete</h3>
                <p>
                  The AI clinical interaction service is currently unreachable
                  or returned an incomplete response.
                </p>
                <p>
                  <strong>Never treat an unavailable analysis as safety clearance.</strong>{" "}
                  Do not take this medicine without consulting your prescribing
                  doctor or pharmacist.
                </p>
                <button
                  type="button"
                  className="button secondary compact"
                  onClick={runSafetyCheck}
                >
                  <RotateCcw size={14} /> Retry safety check
                </button>
              </div>
            </div>
          )}

          {result && !loading && !serviceOffline && (
            <div className="safety-report">
              {/* Overall Status Banner */}
              {result.shouldConsultDoctor || criticalWarnings.length > 0 ? (
                <div
                  className="safety-status-banner critical-banner"
                  role="alert"
                >
                  <ShieldAlert size={32} />
                  <div>
                    <h3>CRITICAL SAFETY CONCERNS DETECTED</h3>
                    <p>
                      One or more severe drug interactions, allergen risks, or
                      condition contraindications were identified.
                    </p>
                    <strong>
                      Consult your doctor or pharmacist before taking this
                      medicine.
                    </strong>
                  </div>
                </div>
              ) : warnWarnings.length > 0 ? (
                <div className="safety-status-banner warn-banner" role="status">
                  <AlertTriangle size={30} />
                  <div>
                    <h3>Precautions & Warnings Found</h3>
                    <p>
                      No critical block was triggered, but important cautions
                      apply to your profile. Review below.
                    </p>
                  </div>
                </div>
              ) : (
                <div className="safety-status-banner clear-banner" role="status">
                  <ShieldCheck size={30} />
                  <div>
                    <h3>No Severe Interactions Detected</h3>
                    <p>
                      No high-risk contraindications were identified in our
                      rules, DDInter, or OpenFDA databases for this profile.
                    </p>
                    <small>
                      Automated safety screening is an aid, not a substitute for
                      clinical doctor consultation.
                    </small>
                  </div>
                </div>
              )}

              {/* Patient Context Summary Pill Bar */}
              <div className="patient-context-bar">
                <span>Evaluated Profile:</span>
                {age && <span className="profile-pill">Age: {age}y</span>}
                {conditions.map((c) => (
                  <span key={c} className="profile-pill">
                    Cond: {c}
                  </span>
                ))}
                {currentMeds.map((m) => (
                  <span key={m} className="profile-pill">
                    Current: {m}
                  </span>
                ))}
                {allergens.map((a) => (
                  <span key={a} className="profile-pill alert-pill">
                    Allergy: {a}
                  </span>
                ))}
                {!age &&
                  conditions.length === 0 &&
                  currentMeds.length === 0 &&
                  allergens.length === 0 && (
                    <span className="profile-pill">General Profile</span>
                  )}
              </div>

              {/* Warning Cards List */}
              <div className="warnings-list">
                {criticalWarnings.map((w, i) => (
                  <WarningCard key={`crit-${i}`} warning={w} />
                ))}
                {warnWarnings.map((w, i) => (
                  <WarningCard key={`warn-${i}`} warning={w} />
                ))}
                {infoWarnings.map((w, i) => (
                  <WarningCard key={`info-${i}`} warning={w} />
                ))}
              </div>

              {/* Summary & Disclaimer */}
              <div className="panel safety-summary-card">
                <div className="summary-header">
                  <Stethoscope size={18} />
                  <h4>Clinical Summary</h4>
                </div>
                <p className="summary-body">{result.summary}</p>
                {result.disclaimer && (
                  <p className="summary-disclaimer">
                    <Info size={14} /> {result.disclaimer}
                  </p>
                )}
              </div>
            </div>
          )}
        </section>
      </div>
    </div>
  );
}

function WarningCard({ warning }: { warning: SafetyWarning }) {
  const isCritical = warning.severity === "CRITICAL";
  const isWarn = warning.severity === "WARN";

  return (
    <article
      className={`warning-item-card ${
        isCritical ? "critical-card" : isWarn ? "warn-card" : "info-card"
      }`}
    >
      <div className="warning-card-header">
        <span
          className={`severity-badge ${
            isCritical ? "badge-critical" : isWarn ? "badge-warn" : "badge-info"
          }`}
        >
          {warning.severity}
        </span>
        {warning.database && (
          <span className="database-badge">{warning.database}</span>
        )}
        <h3>{warning.title}</h3>
      </div>

      <p className="warning-detail">{warning.detail}</p>

      {warning.action && (
        <div className="warning-action-row">
          <strong>Recommended Action:</strong>
          <span>{warning.action}</span>
        </div>
      )}

      {warning.source && (
        <div className="warning-source-row">
          <span>Source:</span>
          {warning.source.startsWith("http") ? (
            <a
              href={warning.source}
              target="_blank"
              rel="noopener noreferrer"
              className="source-link"
            >
              {warning.source} <ExternalLink size={12} />
            </a>
          ) : (
            <span className="source-label">{warning.source}</span>
          )}
        </div>
      )}
    </article>
  );
}
