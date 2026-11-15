"use client";
import { useState } from "react";
import {
  ArrowUpRight,
  ArrowRight,
  ScanLine,
  CalendarDays,
  Pill,
  ShieldCheck,
  Plus,
  Clock3,
  Sun,
  Sunset,
  Moon,
  Lightbulb,
  HeartHandshake,
  Check,
  Sparkles,
  ChevronRight,
  Bookmark,
  BarChart3,
  ShieldAlert,
  Coins,
  MessageSquare,
  Activity,
  Cpu,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import type {
  SavedMedicine,
  DoseLog,
  RecentScan,
  Medicine,
  Language,
  Slot,
} from "@/lib/contracts";
import type { HealthResult } from "@/lib/ai-backend";
import { medicines, tips } from "@/lib/catalog";
import { localDate, rollingLogs, tipsForTags } from "@/lib/engine";
import { cleanTranslation } from "./ui";

export type View =
  | "overview"
  | "scan"
  | "safety"
  | "pricing"
  | "chat"
  | "medicines"
  | "reminders"
  | "tips"
  | "share"
  | "privacy";

const slotIcons = {
  Morning: Sun,
  Afternoon: Sun,
  Evening: Sunset,
  Night: Moon,
};

interface DashboardProps {
  saved: SavedMedicine[];
  logs: DoseLog[];
  recent: RecentScan[];
  language: Language;
  health?: HealthResult | null;
  onNavigate: (v: View, focus?: boolean) => void;
  onOpen: (m: Medicine) => void;
  onLog: (id: string, slot: Slot, status: "taken" | "missed") => void;
}

export function Dashboard({
  saved,
  logs,
  recent,
  language,
  health,
  onNavigate,
  onOpen,
  onLog,
}: DashboardProps) {
  const [slot, setSlot] = useState<Slot>("Morning");
  const [showTechDetails, setShowTechDetails] = useState(false);

  const today = localDate();
  const todayLogs = logs.filter((l) => l.date === today);
  const weekLogs = rollingLogs(logs);
  const taken = weekLogs.filter((l) => l.status === "taken").length;

  const relevantTags = [...saved.map((s) => s.id), ...recent.map((s) => s.id)].flatMap(
    (id) => medicines.find((m) => m.id === id)?.tags || []
  );
  const tip = tipsForTags(relevantTags, tips)[0] || tips[0];
  const scheduled = saved.filter((s) => s.slots.includes(slot));
  const totalToday = saved.reduce((n, s) => n + s.slots.length, 0);
  const todayTaken = todayLogs.filter((l) => l.status === "taken").length;

  const isBackendOnline = health?.status === "ok";

  return (
    <div className="dashboard page-enter">
      {/* Welcome Row */}
      <div className="welcome-row">
        <div>
          <div className="greeting-eyebrow">
            <span className="tiny-sun">☀</span> A LITTLE CARE, EVERY DAY
          </div>
          <h1>
            {language === "ta"
              ? "உங்கள் ஆரோக்கியம், இன்னும் தெளிவாக."
              : language === "hi"
              ? "आपकी सेहत, थोड़ी और स्पष्ट।"
              : "Your health, a little clearer."}
          </h1>
          <p>
            AI-powered medicine identification, clinical safety screening, and
            generic cost savings.
          </p>
        </div>
        <div className="today-date">
          <CalendarDays size={17} />
          <span suppressHydrationWarning>
            {new Date().toLocaleDateString("en-IN", {
              day: "numeric",
              month: "short",
              year: "numeric",
            })}
          </span>
        </div>
      </div>

      {/* Backend Integration Status Bar */}
      <section className="backend-health-banner">
        <div className="health-status-summary">
          <span
            className={`health-dot-indicator ${
              isBackendOnline ? "status-online" : "status-offline"
            }`}
          />
          <div className="health-title-group">
            <strong>
              {isBackendOnline
                ? "AI Model Backend Connected"
                : "Backend Offline · Local Retrieval Tier Active"}
            </strong>
            <span className="health-summary-text">
              {health?.ner
                ? `NER Model: ${health.ner}`
                : "Running on-device catalog & OCR fallback"}
            </span>
          </div>
          <button
            type="button"
            className="text-button health-toggle-button"
            onClick={() => setShowTechDetails(!showTechDetails)}
          >
            <Cpu size={14} />
            <span>Capability Details</span>
            {showTechDetails ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
          </button>
        </div>

        {showTechDetails && (
          <div className="backend-capabilities-grid">
            <div className="capability-card">
              <span className="cap-label">CRF NER Model:</span>
              <span className="cap-val">
                {health?.ner ? (
                  <span className="tag-ok">Trained (F1=0.996)</span>
                ) : (
                  <span className="tag-warn">Offline fallback</span>
                )}
              </span>
            </div>

            <div className="capability-card">
              <span className="cap-label">Pill Classifier:</span>
              <span className="cap-val">
                {health?.integrations?.pillClassifier?.available ? (
                  <span className="tag-ok">
                    Ready ({String(health.integrations.pillClassifier.classes ?? 0)} classes)
                  </span>
                ) : (
                  <span className="tag-muted">Optional / Standby</span>
                )}
              </span>
            </div>

            <div className="capability-card">
              <span className="cap-label">Brand-to-Salt Lookup:</span>
              <span className="cap-val">
                {health?.integrations?.brandLookup?.available ? (
                  <span className="tag-ok">
                    Active ({String(health.integrations.brandLookup.brands ?? 0)} brands)
                  </span>
                ) : (
                  <span className="tag-muted">Curated 80 brands</span>
                )}
              </span>
            </div>

            <div className="capability-card">
              <span className="cap-label">PMBJP Pricing:</span>
              <span className="cap-val">
                {health?.integrations?.pmjpPricing?.available ? (
                  <span className="tag-ok">Jan Aushadhi Active</span>
                ) : (
                  <span className="tag-muted">Local catalog only</span>
                )}
              </span>
            </div>

            <div className="capability-card">
              <span className="cap-label">DDInter Drug-Drug:</span>
              <span className="cap-val">
                {health?.integrations?.ddInter?.available ? (
                  <span className="tag-ok">
                    Indexed ({String(health.integrations.ddInter.rows ?? 0)} rows)
                  </span>
                ) : (
                  <span className="tag-muted">Rule-based fallback</span>
                )}
              </span>
            </div>

            <div className="capability-card">
              <span className="cap-label">OpenFDA Label API:</span>
              <span className="cap-val">
                {health?.integrations?.openfdaInteractions?.available ? (
                  <span className="tag-ok">Ready</span>
                ) : (
                  <span className="tag-muted">Offline reference</span>
                )}
              </span>
            </div>

            <div className="capability-card">
              <span className="cap-label">Indic STT Voice:</span>
              <span className="cap-val">
                {health?.integrations?.indicSTT?.available ? (
                  <span className="tag-ok">AI4Bharat Conformer</span>
                ) : (
                  <span className="tag-muted">Web Speech API Fallback</span>
                )}
              </span>
            </div>

            <div className="capability-card">
              <span className="cap-label">Chat LLM Engine:</span>
              <span className="cap-val">
                {health?.features?.chatLLM === "meditron" ? (
                  <span className="tag-ok">Meditron (Clinical LLM)</span>
                ) : health?.features?.chatLLM === "gemini" ? (
                  <span className="tag-ok">Gemini 2.5 Flash</span>
                ) : (
                  <span className="tag-muted">Deterministic Rule Engine</span>
                )}
              </span>
            </div>
          </div>
        )}
      </section>

      {/* Hero Card */}
      <section className="hero-card">
        {/* eslint-disable-next-line @next/next/no-img-element */}
        <img
          className="hero-image"
          src="/images/medicine-hero.webp"
          alt=""
          aria-hidden="true"
        />
        <div className="hero-gradient" />
        <div className="hero-copy">
          <span className="hero-eyebrow">
            <span className="blue-dot" /> AI-POWERED MEDICINE ASSISTANT
          </span>
          <h2>
            Know what you take.
            <br />
            <span>Take care with confidence.</span>
          </h2>
          <p>
            Scan medicine strips with on-device OCR and trained CRF NER.
            Check multi-drug safety, compare generic PMBJP prices, and chat in
            your native language.
          </p>
          <div className="hero-actions">
            <button
              type="button"
              className="button primary"
              onClick={() => onNavigate("scan")}
            >
              <ScanLine size={20} /> Smart Medicine Scanner <ArrowRight size={17} />
            </button>
            <button
              type="button"
              className="hero-search-link"
              onClick={() => onNavigate("scan", true)}
            >
              Search by name <ChevronRight size={16} />
            </button>
          </div>
          <div className="hero-footnote">
            <ShieldCheck size={15} /> Private by design. No cloud account required.
          </div>
        </div>
        <div className="hero-floating-note">
          <span>
            <Check size={16} />
          </span>{" "}
          A clearer picture. A calmer you.
        </div>
      </section>

      {/* Core AI Medicine Capabilities Suite */}
      <section className="ai-features-section">
        <div className="section-title">
          <span className="icon-tile blue">
            <Sparkles size={22} />
          </span>
          <div>
            <h2>AI Medicine Assistant Capabilities</h2>
            <p>Integrated tools designed to make healthcare safer and transparent</p>
          </div>
        </div>

        <div className="ai-features-grid">
          {/* Feature 1: Smart Scanner */}
          <button
            type="button"
            className="ai-feature-card"
            onClick={() => onNavigate("scan")}
          >
            <div className="ai-card-top">
              <span className="icon-tile blue">
                <ScanLine size={24} />
              </span>
              <span className="feature-status-pill">Feature 1</span>
            </div>
            <h3>Smart Medicine Scanner</h3>
            <p>
              Photograph strip text. Identifies active salt, brand, strength, form,
              and generates probability-ranked candidates for damaged strips.
            </p>
            <div className="ai-card-footer">
              <span>Open Scanner</span>
              <ArrowUpRight size={16} />
            </div>
          </button>

          {/* Feature 2: Personal Safety Checker */}
          <button
            type="button"
            className="ai-feature-card"
            onClick={() => onNavigate("safety")}
          >
            <div className="ai-card-top">
              <span className="icon-tile lilac">
                <ShieldAlert size={24} />
              </span>
              <span className="feature-status-pill">Feature 2</span>
            </div>
            <h3>Personal Safety Checker</h3>
            <p>
              Screen against your age, chronic conditions, current prescriptions,
              and allergies. Severity-ranked CRITICAL / WARN / INFO alerts.
            </p>
            <div className="ai-card-footer">
              <span>Check Safety</span>
              <ArrowUpRight size={16} />
            </div>
          </button>

          {/* Feature 3: Generic Medicine Finder */}
          <button
            type="button"
            className="ai-feature-card"
            onClick={() => onNavigate("pricing")}
          >
            <div className="ai-card-top">
              <span className="icon-tile mint">
                <Coins size={24} />
              </span>
              <span className="feature-status-pill">Feature 3</span>
            </div>
            <h3>Generic Medicine Finder</h3>
            <p>
              Lookup Jan Aushadhi (PMBJP) generic equivalents and compare real
              savings (50% to 90% off) for commercial brand names.
            </p>
            <div className="ai-card-footer">
              <span>Find Generics</span>
              <ArrowUpRight size={16} />
            </div>
          </button>

          {/* Feature 4: MediVision AI Assistant */}
          <button
            type="button"
            className="ai-feature-card"
            onClick={() => onNavigate("chat")}
          >
            <div className="ai-card-top">
              <span className="icon-tile peach">
                <MessageSquare size={24} />
              </span>
              <span className="feature-status-pill">Feature 4</span>
            </div>
            <h3>MediVision AI Assistant</h3>
            <p>
              Safety-grounded conversational medical assistance in English, தமிழ்,
              and हिन्दी with voice input and text-to-speech reading.
            </p>
            <div className="ai-card-footer">
              <span>Start Consultation</span>
              <ArrowUpRight size={16} />
            </div>
          </button>
        </div>
      </section>

      {/* Routine & Adherence Stats Grid */}
      <div className="stats-grid">
        <button
          type="button"
          className="stat-card"
          onClick={() => onNavigate("medicines")}
        >
          <span className="icon-tile blue">
            <Pill size={24} />
          </span>
          <span className="stat-info">
            <span className="stat-label">My medicines</span>
            <strong>
              {saved.length}{" "}
              <small>
                {saved.length === 1 ? "medicine saved" : "medicines saved"}
              </small>
            </strong>
            <span className="stat-caption">Your cabinet, always close</span>
          </span>
          <ChevronRight size={18} className="stat-arrow" />
        </button>

        <button
          type="button"
          className="stat-card"
          onClick={() => onNavigate("reminders")}
        >
          <span className="icon-tile mint">
            <BarChart3 size={23} />
          </span>
          <span className="stat-info">
            <span className="stat-label">Your 7-day rhythm</span>
            <strong>
              {weekLogs.length
                ? `${Math.round((taken / weekLogs.length) * 100)}%`
                : "—"}{" "}
              <small>
                {weekLogs.length ? "of doses recorded" : "let's build a routine"}
              </small>
            </strong>
            <span className="stat-caption">Little steps add up</span>
          </span>
          <ChevronRight size={18} className="stat-arrow" />
        </button>

        <button
          type="button"
          className="stat-card privacy-stat"
          onClick={() => onNavigate("privacy")}
        >
          <span className="icon-tile lilac">
            <ShieldCheck size={25} />
          </span>
          <span className="stat-info">
            <span className="stat-label">Just you & your data</span>
            <strong className="privacy-stat-title">On your device. Always.</strong>
            <span className="stat-caption">No accounts. No cloud storage.</span>
          </span>
          <ChevronRight size={18} className="stat-arrow" />
        </button>
      </div>

      {/* Schedule & Daily Tip Grid */}
      <div className="dashboard-grid">
        <section className="panel schedule-card">
          <div className="panel-heading">
            <h2>
              <Clock3 size={21} /> Today&apos;s reminders
            </h2>
            <button
              type="button"
              className="text-button"
              onClick={() => onNavigate("reminders")}
            >
              View all <ArrowRight size={16} />
            </button>
          </div>

          <div className="slot-tabs" aria-label="Reminder time">
            {(Object.keys(slotIcons) as Slot[]).map((s) => {
              const Icon = slotIcons[s];
              return (
                <button
                  key={s}
                  type="button"
                  aria-pressed={slot === s}
                  className={slot === s ? "active" : ""}
                  onClick={() => setSlot(s)}
                >
                  <Icon size={17} />
                  {s}
                </button>
              );
            })}
          </div>

          {scheduled.length ? (
            <div className="dashboard-dose-list">
              {scheduled.map((s) => {
                const m = medicines.find((med) => med.id === s.id);
                if (!m) return null;
                const status = todayLogs.find(
                  (l) => l.medicineId === s.id && l.slot === slot
                )?.status;
                return (
                  <div className="dashboard-dose" key={s.id}>
                    <span className="icon-tile blue small">
                      <Pill size={21} />
                    </span>
                    <button
                      type="button"
                      className="medicine-name-link"
                      onClick={() => onOpen(m)}
                    >
                      {m.name}
                      <small>{m.activeIngredient}</small>
                    </button>
                    <button
                      type="button"
                      className={`button compact ${
                        status === "taken" ? "taken-button" : "secondary"
                      }`}
                      onClick={() => onLog(s.id, slot, "taken")}
                    >
                      <Check size={17} />
                      {status === "taken" ? "Taken" : "Mark taken"}
                    </button>
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="schedule-empty">
              <div className="empty-clock">
                <Clock3 size={29} />
                <span className="clock-dot" />
              </div>
              <h3>
                {saved.length
                  ? "A little breathing room."
                  : "Good routines start with one step."}
              </h3>
              <p>
                {saved.length
                  ? `You have no medicines scheduled for ${slot.toLowerCase()}.`
                  : "Save a medicine and set a time that works for you."}
              </p>
              <button
                type="button"
                className="button secondary"
                onClick={() => onNavigate(saved.length ? "medicines" : "scan", true)}
              >
                <Plus size={17} />
                {saved.length ? "Set up your schedule" : "Add your first medicine"}
              </button>
            </div>
          )}

          <div className="schedule-footer">
            <span className="green-dot" />
            {totalToday
              ? `${todayTaken} of ${totalToday} scheduled doses marked taken today`
              : "Your daily check-in, at your own pace."}
          </div>
        </section>

        {/* Tip of the day */}
        <section className="tip-card">
          <div className="tip-card-heading">
            <span className="tip-bulb">
              <Lightbulb size={24} />
            </span>
            <h2>Tip of the day</h2>
            <span className="tip-small-star">
              <Sparkles size={19} />
            </span>
          </div>
          <span className="tip-category">A SMALL CHECK. A SAFER CHOICE.</span>
          <h3>{cleanTranslation(tip[language].title)}</h3>
          <p>{cleanTranslation(tip[language].advice)}</p>
          <div className="tip-card-footer">
            <button
              type="button"
              className="text-button"
              onClick={() => onNavigate("tips")}
            >
              A little more to know <ArrowRight size={17} />
            </button>
            <span className="tip-dots">
              <i className="active" />
              <i />
              <i />
            </span>
          </div>
        </section>
      </div>

      {/* Recently Scanned Section */}
      {recent.length > 0 && (
        <section className="recent-section">
          <div className="panel-heading">
            <h2>Recently scanned</h2>
            <span>Only on this device</span>
          </div>
          <div className="recent-grid">
            {recent.slice(0, 3).map((s, i) => {
              const m = medicines.find((med) => med.id === s.id);
              return m ? (
                <button
                  type="button"
                  className="recent-card"
                  key={`${s.at}-${i}`}
                  onClick={() => onOpen(m)}
                >
                  <span className="icon-tile blue">
                    <ScanLine size={22} />
                  </span>
                  <span>
                    <strong>{m.name}</strong>
                    <small>{m.activeIngredient}</small>
                  </span>
                  <ArrowUpRight size={18} />
                </button>
              ) : null;
            })}
          </div>
        </section>
      )}

      {/* Bottom Disclaimer */}
      <div className="dashboard-disclaimer">
        <ShieldCheck size={16} />
        <span>
          Made for peace of mind. Not a substitute for professional medical advice.
        </span>
        <button type="button" onClick={() => onNavigate("privacy")}>
          Privacy & your data <ArrowUpRight size={14} />
        </button>
      </div>
    </div>
  );
}
