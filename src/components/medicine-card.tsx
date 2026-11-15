"use client";
import { useEffect, useState, useRef } from "react";
import {
  Pill,
  Volume2,
  Pause,
  Play,
  Square,
  BookmarkPlus,
  BookmarkCheck,
  CheckCircle2,
  AlertTriangle,
  ExternalLink,
  ShieldCheck,
  ClipboardCheck,
  Lightbulb,
  Languages,
  ShieldAlert,
  Coins,
  MessageSquare,
} from "lucide-react";
import type { Medicine, Language } from "@/lib/contracts";
import { tipsForTags, confidenceTier } from "@/lib/engine";
import { tips } from "@/lib/catalog";
import { Modal, cleanTranslation } from "./ui";

const headings = {
  en: {
    use: "What it's commonly used for",
    before: "Before you take it",
    side: "Possible side effects",
    help: "Stop and get medical help if…",
    check: "A quick check before you take it",
    listen: "Listen to this information",
  },
  ta: {
    use: "பொதுவாக எதற்குப் பயன்படுகிறது",
    before: "எடுத்துக்கொள்ளும் முன்",
    side: "ஏற்படக்கூடிய பக்கவிளைவுகள்",
    help: "நிறுத்தி மருத்துவ உதவி பெறவும்…",
    check: "எடுக்கும் முன் ஒரு சரிபார்ப்பு",
    listen: "இந்தத் தகவலைக் கேளுங்கள்",
  },
  hi: {
    use: "आमतौर पर किसलिए उपयोग होती है",
    before: "लेने से पहले",
    side: "संभावित दुष्प्रभाव",
    help: "रोकें और चिकित्सा मदद लें अगर…",
    check: "लेने से पहले एक जांच",
    listen: "यह जानकारी सुनें",
  },
};

interface MedicineCardProps {
  medicine: Medicine;
  language: Language;
  score?: number;
  saved: boolean;
  onSave: () => void;
  onClose: () => void;
  onLanguage: (l: Language) => void;
  onCheckSafety?: (m: Medicine) => void;
  onCheckPricing?: (m: Medicine) => void;
  onAskAI?: (m: Medicine) => void;
}

export function MedicineCard({
  medicine,
  language,
  score,
  saved,
  onSave,
  onClose,
  onLanguage,
  onCheckSafety,
  onCheckPricing,
  onAskAI,
}: MedicineCardProps) {
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [speaking, setSpeaking] = useState(false);
  const [paused, setPaused] = useState(false);
  const [speechError, setSpeechError] = useState("");
  const utterance = useRef<SpeechSynthesisUtterance | null>(null);

  const locale = { en: "en-IN", ta: "ta-IN", hi: "hi-IN" }[language];
  const voice = voices.find(
    (v) =>
      v.localService &&
      v.lang.toLowerCase().replace("_", "-") === locale.toLowerCase()
  );

  useEffect(() => {
    if (!("speechSynthesis" in window)) return;
    const update = () => setVoices(window.speechSynthesis.getVoices());
    update();
    window.speechSynthesis.addEventListener("voiceschanged", update);
    return () => {
      window.speechSynthesis.removeEventListener("voiceschanged", update);
      window.speechSynthesis.cancel();
    };
  }, []);

  function handleLanguageSwitch(l: Language) {
    if ("speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setSpeaking(false);
    setPaused(false);
    onLanguage(l);
  }

  const content = medicine[language];
  const h = headings[language];

  function listen() {
    if (!voice) return;
    window.speechSynthesis.cancel();
    setSpeechError("");
    const spoken = [
      medicine.name,
      h.use,
      content.uses,
      h.before,
      ...content.beforeYouTake,
      h.side,
      content.sideEffects,
      h.help,
      ...content.stopAndGetHelp,
      "Information from the label and a reference list. Not medical advice.",
    ]
      .map(cleanTranslation)
      .join(". ");

    const u = new SpeechSynthesisUtterance(spoken);
    u.voice = voice;
    u.lang = locale;
    u.rate = 0.85;
    u.onend = () => {
      setSpeaking(false);
      setPaused(false);
    };
    u.onerror = (e) => {
      setSpeaking(false);
      if (e.error !== "canceled" && e.error !== "interrupted") {
        setSpeechError("Audio could not play. Check device sound and try Listen again.");
      }
    };
    utterance.current = u;
    setSpeaking(true);
    setPaused(false);
    window.speechSynthesis.speak(u);
  }

  const medTips = tipsForTags(medicine.tags, tips).slice(0, 2);

  return (
    <Modal
      title={`${medicine.name} information`}
      onClose={onClose}
      className="medicine-modal"
    >
      <div className="medicine-card-header">
        <div className="medicine-icon">
          <Pill size={32} />
        </div>
        <div>
          <p className="eyebrow">YOUR MEDICINE, MADE CLEARER</p>
          <h2>{medicine.name}</h2>
          <p>
            {medicine.activeIngredient}
            {medicine.activeIngredient2 ? ` + ${medicine.activeIngredient2}` : ""}
          </p>
          <div className="medicine-tags">
            <span>{medicine.strength}</span>
            <span>{medicine.form}</span>
            <span>{medicine.category}</span>
          </div>
        </div>
      </div>

      {/* Prominent Continue with AI Assistant Action */}
      {onAskAI && (
        <div className="continue-ai-hero-box">
          <button
            type="button"
            className="button primary continue-ai-hero-btn"
            onClick={() => {
              onClose();
              onAskAI(medicine);
            }}
          >
            <MessageSquare size={19} />
            <span>Continue with AI Assistant</span>
          </button>
        </div>
      )}

      {/* AI Quick Actions Bar */}
      <div className="card-ai-actions-bar">
        {onCheckSafety && (
          <button
            type="button"
            className="ai-action-btn safety-btn"
            onClick={() => {
              onClose();
              onCheckSafety(medicine);
            }}
          >
            <ShieldAlert size={15} /> Check Safety
          </button>
        )}

        {onCheckPricing && (
          <button
            type="button"
            className="ai-action-btn pricing-btn"
            onClick={() => {
              onClose();
              onCheckPricing(medicine);
            }}
          >
            <Coins size={15} /> Generic Price
          </button>
        )}
      </div>

      <div className="card-confidence">
        <span className={score === undefined ? "" : "confidence-positive"}>
          {score === undefined ? (
            <ClipboardCheck size={16} />
          ) : (
            <CheckCircle2 size={16} />
          )}
          {score === undefined
            ? "Selected from reference catalog"
            : `${confidenceTier(score) === "HIGH" ? "Strong text match" : "Confirmed possible match"} · ${Math.round(score * 100)}%`}
        </span>
        <span>Reference content · not clinically verified</span>
      </div>

      <div className="card-language">
        <Languages size={19} />
        <span>Read in</span>
        {(["en", "ta", "hi"] as Language[]).map((l) => (
          <button
            type="button"
            className={language === l ? "active" : ""}
            onClick={() => handleLanguageSwitch(l)}
            key={l}
          >
            {l === "en" ? "English" : l === "ta" ? "தமிழ்" : "हिन्दी"}
          </button>
        ))}
      </div>

      {language !== "en" && (
        <div className="notice warning translation-note">
          <AlertTriangle size={22} />
          <p>
            <strong>[TODO: Verify translation]</strong>
            <br />
            This is an unverified draft translation. Ask a pharmacist to confirm;
            the English reference remains available.
          </p>
        </div>
      )}

      <div className="listen-area">
        <button
          type="button"
          className="button listen-button"
          onClick={listen}
          disabled={!voice}
        >
          <Volume2 size={22} />
          {h.listen}
        </button>
        {speaking && (
          <div className="button-row">
            <button
              type="button"
              className="button secondary"
              onClick={() => {
                if (paused) window.speechSynthesis.resume();
                else window.speechSynthesis.pause();
                setPaused(!paused);
              }}
            >
              {paused ? <Play size={18} /> : <Pause size={18} />}
              {paused ? "Resume" : "Pause"}
            </button>
            <button
              type="button"
              className="button secondary"
              onClick={() => {
                window.speechSynthesis.cancel();
                setSpeaking(false);
                setPaused(false);
              }}
            >
              <Square size={17} /> Stop
            </button>
          </div>
        )}
        {!voice && (
          <small>
            No on-device {locale} voice available. Add this language in your device&apos;s
            speech settings to listen privately.
          </small>
        )}
        {speechError && (
          <p role="alert" className="error-text">
            {speechError}
          </p>
        )}
      </div>

      <div className="medicine-content" lang={language}>
        <section>
          <h3>
            <Pill size={21} />
            {h.use}
          </h3>
          <p>{cleanTranslation(content.uses)}</p>
        </section>

        <section className="cautions-section">
          <h3>
            <ShieldCheck size={22} />
            {h.before}
          </h3>
          <ul>
            {content.beforeYouTake.map((s, i) => (
              <li key={i}>{cleanTranslation(s)}</li>
            ))}
          </ul>
        </section>

        <section>
          <h3>{h.side}</h3>
          <p>{cleanTranslation(content.sideEffects)}</p>
          <p className="muted">
            This is not a complete list. Check your medicine&apos;s leaflet.
          </p>
        </section>

        <section className="help-section">
          <h3>
            <AlertTriangle size={23} />
            {h.help}
          </h3>
          <ul>
            {content.stopAndGetHelp.map((s, i) => (
              <li key={i}>{cleanTranslation(s)}</li>
            ))}
          </ul>
          <p>
            <strong>
              For severe symptoms in India, call 112 or seek emergency care. Do not
              wait for this app.
            </strong>
          </p>
        </section>

        <section>
          <h3>
            <ClipboardCheck size={23} />
            {h.check}
          </h3>
          <div className="checklist">
            {content.preChecklist.map((s, i) => (
              <label key={i}>
                <input type="checkbox" />
                {cleanTranslation(s)}
              </label>
            ))}
          </div>
        </section>

        {medTips.map((t) => (
          <section className="inline-tip" key={t.id}>
            <h3>
              <Lightbulb size={22} />
              {cleanTranslation(t[language].title)}
            </h3>
            <p>{cleanTranslation(t[language].advice)}</p>
          </section>
        ))}

        <section className="sources">
          <h3>Where this information comes from</h3>
          <p>
            Ingredient-level references, not verification of your particular
            strip. Always compare the name, strength and leaflet on your own packet.
          </p>
          {medicine.sources.map((s) => (
            <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer">
              {s.title}
              <ExternalLink size={17} />
            </a>
          ))}
          <small>Opening a source uses the internet and leaves this app.</small>
        </section>
      </div>

      <footer className="medicine-footer">
        <div className="button-row" style={{ width: "100%", justifyContent: "space-between", gap: "10px" }}>
          <button
            type="button"
            className={`button ${saved ? "saved-button" : "secondary"}`}
            onClick={onSave}
            disabled={saved}
          >
            {saved ? <BookmarkCheck size={20} /> : <BookmarkPlus size={20} />}
            {saved ? "Saved in Cabinet" : "Save to Cabinet"}
          </button>
          {onAskAI && (
            <button
              type="button"
              className="button primary"
              onClick={() => {
                onClose();
                onAskAI(medicine);
              }}
            >
              <MessageSquare size={19} />
              <span>Continue with AI Assistant</span>
            </button>
          )}
        </div>
        <p>Information from the label and a reference list. Not medical advice.</p>
      </footer>
    </Modal>
  );
}
