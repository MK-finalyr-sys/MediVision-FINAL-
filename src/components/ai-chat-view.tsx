"use client";
import { useState, useRef, useEffect } from "react";
import {
  MessageSquare,
  Send,
  Pill,
  Sparkles,
  Volume2,
  VolumeX,
  RotateCcw,
  Bot,
  User,
  ShieldCheck,
  AlertTriangle,
  LoaderCircle,
  X,
  ChevronDown,
  Languages,
} from "lucide-react";
import { medicines } from "@/lib/catalog";
import type { Medicine, Language } from "@/lib/contracts";
import {
  aiChat,
  type ChatMessage,
  type MedicineChatContext,
  type HealthResult,
} from "@/lib/ai-backend";
import { VoiceInput } from "./voice-input";

interface AiChatProps {
  initialMedicine?: Medicine | null;
  language: Language;
  onLanguageChange: (lang: Language) => void;
  indicSttAvailable: boolean;
  backendHealth?: HealthResult | null;
}

interface MessageItem {
  sender: "user" | "assistant";
  text: string;
  speakableText?: string;
  model?: string;
  provider?: string;
  isFallback?: boolean;
  fallbackNotice?: string;
  flagged?: boolean;
  flagReason?: string | null;
  timestamp: string;
}

const SUGGESTIONS = {
  en: [
    "What is this medicine commonly used for?",
    "Should it be taken before or after meals?",
    "What are the most common side effects?",
    "Can elderly patients take this safely?",
    "What happens if I miss a scheduled dose?",
  ],
  ta: [
    "இந்த மருந்து பொதுவாக எதற்குப் பயன்படுகிறது?",
    "உணவுக்கு முன் அல்லது பின் சாப்பிட வேண்டுமா?",
    "இதன் பொதுவான பக்கவிளைவுகள் என்ன?",
    "முதியவர்கள் இதை பாதுகாப்பாக எடுக்கலாமா?",
    "ஒரு வேளை மருந்தை மறந்தால் என்ன செய்ய வேண்டும்?",
  ],
  hi: [
    "यह दवा आमतौर पर किसलिए उपयोग की जाती है?",
    "क्या इसे खाने से पहले या बाद में लेना चाहिए?",
    "इसके सामान्य दुष्प्रभाव क्या हैं?",
    "क्या बुजुर्ग मरीज इसे सुरक्षित रूप से ले सकते हैं?",
    "अगर एक खुराक छूट जाए तो क्या करना चाहिए?",
  ],
};

export function AiChatView({
  initialMedicine,
  language,
  onLanguageChange,
  indicSttAvailable,
  backendHealth,
}: AiChatProps) {
  const [selectedMedicine, setSelectedMedicine] = useState<Medicine | null>(
    initialMedicine || null
  );
  const [messages, setMessages] = useState<MessageItem[]>([]);
  const [inputText, setInputText] = useState("");
  const [loading, setLoading] = useState(false);
  const [speakingIdx, setSpeakingIdx] = useState<number | null>(null);
  const [speechWarning, setSpeechWarning] = useState<string>("");
  const [providerOverride, setProviderOverride] = useState<{
    isFallback: boolean;
    provider?: string;
    model?: string;
    notice?: string;
  } | null>(null);

  const activeProviderStatus =
    providerOverride ||
    (backendHealth
      ? {
          isFallback: !backendHealth.gemini,
          provider: "gemini",
          model: backendHealth.gemini
            ? backendHealth.geminiModel || "Gemini 2.5 Flash"
            : "rule-based-fallback",
          notice: !backendHealth.gemini
            ? "Online AI conversation is currently running in offline fallback mode because a Gemini API key is not configured on the backend. Responses are limited to standard published medicine labels."
            : undefined,
        }
      : null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const utteranceRef = useRef<SpeechSynthesisUtterance | null>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, loading]);

  useEffect(() => {
    return () => {
      if (typeof window !== "undefined" && "speechSynthesis" in window) {
        window.speechSynthesis.cancel();
      }
    };
  }, []);

  function getMedicineContext(): MedicineChatContext | undefined {
    if (!selectedMedicine) return undefined;
    return {
      salt: selectedMedicine.activeIngredient,
      brand: selectedMedicine.name,
      strength: selectedMedicine.strength,
      form: selectedMedicine.form,
      uses: selectedMedicine.en.uses,
      sideEffects: selectedMedicine.en.sideEffects,
      warnings: selectedMedicine.en.beforeYouTake.join("; "),
      sources: selectedMedicine.sources.map((s) => s.title).join("; "),
    };
  }

  function getConversationHistory(): ChatMessage[] {
    const history: ChatMessage[] = [];
    for (let i = 0; i < messages.length; i += 2) {
      const userMsg = messages[i];
      const botMsg = messages[i + 1];
      if (userMsg?.sender === "user" && botMsg?.sender === "assistant") {
        history.push({ message: userMsg.text, reply: botMsg.text });
      }
    }
    return history.slice(-6); // Keep last 6 exchanges
  }

  async function handleSendMessage(textToSend?: string) {
    const text = (textToSend || inputText).trim();
    if (!text || loading) return;

    const userMsg: MessageItem = {
      sender: "user",
      text,
      timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
    };

    const nextMessages = [...messages, userMsg];
    setMessages(nextMessages);
    setInputText("");
    setLoading(true);

    try {
      const res = await aiChat(
        text,
        language,
        getMedicineContext(),
        getConversationHistory()
      );

      if (res?.isFallback) {
        setProviderOverride({
          isFallback: true,
          provider: res.provider || "gemini",
          model: res.model || "rule-based-fallback",
          notice:
            res.fallbackNotice ||
            "Online AI conversation is currently running in offline fallback mode because a Gemini API key is not configured on the backend. Responses are limited to standard published medicine labels.",
        });
      } else if (res?.ok) {
        setProviderOverride({
          isFallback: false,
          provider: res.provider || "gemini",
          model: res.model || "Gemini 2.5 Flash",
        });
      }

      const botReply: MessageItem = {
        sender: "assistant",
        text:
          res?.reply ||
          (language === "ta"
            ? "சேவையை தொடர்பு கொள்ள முடியவில்லை. தயவுசெய்து உங்கள் மருத்துவரிடம் கேளுங்கள்."
            : language === "hi"
            ? "सेवा से संपर्क नहीं हो सका। कृपया अपने डॉक्टर से संपर्क करें।"
            : "The AI assistant service could not be reached. Please consult your doctor or pharmacist."),
        speakableText: res?.speakableText || res?.reply,
        model: res?.model || (res?.isFallback ? "Rule-based Offline Fallback" : (res?.available ? "AI Assistant" : "Offline Fallback")),
        provider: res?.provider,
        isFallback: res?.isFallback,
        fallbackNotice: res?.fallbackNotice,
        flagged: res?.flagged,
        flagReason: res?.flagReason,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };

      setMessages([...nextMessages, botReply]);
    } catch {
      const errorReply: MessageItem = {
        sender: "assistant",
        text:
          language === "ta"
            ? "மன்னிக்கவும், பிழை ஏற்பட்டுள்ளது. தயவுசெய்து மீண்டும் முயற்சிக்கவும்."
            : language === "hi"
            ? "क्षमा करें, एक त्रुटि हुई। कृपया पुनः प्रयास करें।"
            : "I'm sorry, an unexpected error occurred while communicating with the assistant.",
        model: "Client Fallback",
        isFallback: true,
        timestamp: new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }),
      };
      setMessages([...nextMessages, errorReply]);
    } finally {
      setLoading(false);
    }
  }

  function handleSpeak(msg: MessageItem, idx: number) {
    if (typeof window === "undefined" || !("speechSynthesis" in window)) return;

    if (speakingIdx === idx) {
      window.speechSynthesis.cancel();
      setSpeakingIdx(null);
      return;
    }

    window.speechSynthesis.cancel();
    setSpeechWarning("");
    const textToRead = msg.speakableText || msg.text;
    const utterance = new SpeechSynthesisUtterance(textToRead);
    utteranceRef.current = utterance;

    const langCode = language === "ta" ? "ta-IN" : language === "hi" ? "hi-IN" : "en-IN";
    utterance.lang = langCode;
    utterance.rate = 0.9;

    const voices = window.speechSynthesis.getVoices();
    const matchedVoice = voices.find((v) =>
      v.lang.toLowerCase().replace("_", "-").startsWith(langCode.toLowerCase())
    );
    if (matchedVoice) {
      utterance.voice = matchedVoice;
    } else if (language !== "en") {
      setSpeechWarning(
        language === "ta"
          ? "சாதனத்தில் தமிழ் குரல் கிடைக்கவில்லை. குரல் கேட்க சாதன அமைப்புகளில் தமிழ் பேச்சைச் சேர்க்கவும்."
          : "डिवाइस पर हिन्दी आवाज़ नहीं मिली। आवाज़ सुनने के लिए डिवाइस सेटिंग्स में हिन्दी भाषा जोड़ें।"
      );
    }

    utterance.onend = () => setSpeakingIdx(null);
    utterance.onerror = () => setSpeakingIdx(null);

    setSpeakingIdx(idx);
    window.speechSynthesis.speak(utterance);
  }

  function handleVoiceTranscript(recognizedText: string) {
    setInputText(recognizedText);
  }

  function clearHistory() {
    if (typeof window !== "undefined" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
    }
    setSpeakingIdx(null);
    setSpeechWarning("");
    setMessages([]);
  }

  const currentSuggestions = SUGGESTIONS[language] || SUGGESTIONS.en;
  const selectableMedicines =
    selectedMedicine && !medicines.some((m) => m.id === selectedMedicine.id)
      ? [selectedMedicine, ...medicines]
      : medicines;

  return (
    <div className="ai-chat-page page-enter">
      <div className="page-heading">
        <div>
          <p className="eyebrow">CLINICAL MEDICINE INTELLIGENCE</p>
          <h1>MediVision AI Assistant</h1>
          <p>
            Ask questions about uses, precautions, side effects, and safe routines
            in English, தமிழ், or हिन्दी.
          </p>
        </div>
        <div className="chat-top-controls">
          {/* Language Switcher */}
          <div className="chat-lang-switcher" aria-label="Conversation language">
            <Languages size={16} />
            {(["en", "ta", "hi"] as Language[]).map((l) => (
              <button
                key={l}
                type="button"
                className={`lang-pill ${language === l ? "active" : ""}`}
                onClick={() => onLanguageChange(l)}
              >
                {l === "en" ? "EN" : l === "ta" ? "தமிழ்" : "हिन्दी"}
              </button>
            ))}
          </div>

          {messages.length > 0 && (
            <button
              type="button"
              className="button compact secondary"
              onClick={clearHistory}
              title="Clear current chat"
            >
              <RotateCcw size={14} /> Clear
            </button>
          )}
        </div>
      </div>

      <div className="ai-chat-container panel">
        {/* Medicine Context Selector Bar */}
        <div className="chat-context-bar">
          <div className="context-label">
            <Pill size={16} />
            <span>Active Medicine Context:</span>
          </div>

          <div className="context-selector">
            <select
              value={selectedMedicine?.id || ""}
              onChange={(e) => {
                const found = selectableMedicines.find((m) => m.id === e.target.value);
                setSelectedMedicine(found || null);
              }}
              aria-label="Select medicine context"
            >
              <option value="">General inquiry (no specific medicine)</option>
              {selectableMedicines.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} ({m.activeIngredient} · {m.strength})
                </option>
              ))}
            </select>
            <ChevronDown size={14} className="select-arrow" />
          </div>

          {selectedMedicine && (
            <button
              type="button"
              className="context-clear-btn"
              onClick={() => setSelectedMedicine(null)}
              title="Remove medicine context"
            >
              <X size={14} />
            </button>
          )}
        </div>

        {/* Provider Operational Status Banner */}
        {activeProviderStatus?.isFallback && (
          <div className="notice warning chat-fallback-banner" role="alert" style={{ margin: "10px 16px" }}>
            <AlertTriangle size={18} />
            <div>
              <strong>Online AI Conversation in Limited Fallback Mode</strong>
              <p>
                {activeProviderStatus.notice ||
                  "Online AI chat is running in offline fallback mode because a Gemini API key is not configured on the backend. Responses are limited to standard published medicine labels."}
              </p>
            </div>
          </div>
        )}

        {!activeProviderStatus?.isFallback && activeProviderStatus?.model && (
          <div className="chat-online-banner" style={{ margin: "8px 16px", display: "flex", alignItems: "center", gap: "8px", fontSize: "13px", color: "#1b5edb", background: "#f0f5ff", padding: "6px 12px", borderRadius: "6px" }}>
            <Sparkles size={15} />
            <span>
              <strong>{activeProviderStatus.model}</strong> · Grounded Online Clinical Assistant
            </span>
          </div>
        )}

        {speechWarning && (
          <div className="notice warning" role="status" style={{ margin: "4px 16px" }}>
            <AlertTriangle size={16} />
            <span>{speechWarning}</span>
          </div>
        )}

        {/* Chat History Messages */}
        <div className="chat-messages-area" role="log" aria-live="polite">
          {messages.length === 0 && (
            <div className="chat-welcome-state">
              <div className="bot-avatar large">
                <Sparkles size={30} />
              </div>
              <h3>
                {language === "ta"
                  ? "மருந்து பற்றி என்ன தெரிந்துகொள்ள விரும்புகிறீர்கள்?"
                  : language === "hi"
                  ? "दवा के बारे में आप क्या जानना चाहते हैं?"
                  : "How can I help you understand your medicine?"}
              </h3>
              <p>
                {selectedMedicine
                  ? `Inquiring about ${selectedMedicine.name} (${selectedMedicine.activeIngredient}). Choose a suggested question below or type your query.`
                  : "Grounding responses in published pharmacological labels. Pick a topic or type any question."}
              </p>

              <div className="chat-suggested-grid">
                {currentSuggestions.map((q, idx) => (
                  <button
                    key={idx}
                    type="button"
                    className="suggested-question-pill"
                    onClick={() => handleSendMessage(q)}
                  >
                    <span>{q}</span>
                  </button>
                ))}
              </div>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={`chat-message-row ${
                msg.sender === "user" ? "user-row" : "bot-row"
              }`}
            >
              <div className="message-avatar">
                {msg.sender === "user" ? <User size={18} /> : <Bot size={18} />}
              </div>

              <div className="message-bubble">
                <div className="message-header-meta">
                  <span className="sender-name">
                    {msg.sender === "user" ? "You" : "MediVision Assistant"}
                  </span>
                  {msg.model && (
                    <span
                      className={`model-chip ${msg.isFallback ? "model-chip-fallback" : "model-chip-ai"}`}
                      title={msg.isFallback ? "Rule-based offline fallback" : "Active AI model"}
                      style={{
                        background: msg.isFallback ? "#fef3f2" : "#eef3ff",
                        color: msg.isFallback ? "#b3392a" : "#3b5cb8",
                        border: `1px solid ${msg.isFallback ? "#fedcd8" : "#d6e2fe"}`,
                        fontSize: "11px",
                        padding: "2px 8px",
                        borderRadius: "4px",
                        fontWeight: 600,
                      }}
                    >
                      {msg.isFallback ? `[Offline Fallback] ${msg.model}` : msg.model}
                    </span>
                  )}
                  <span className="message-time">{msg.timestamp}</span>
                </div>

                <div className="message-body-text">{msg.text}</div>

                {msg.flagged && (
                  <div className="chat-flag-notice" role="alert">
                    <AlertTriangle size={15} />
                    <span>
                      {msg.flagReason ||
                        "Important safety flag: Do not alter prescribed doses without speaking to your doctor."}
                    </span>
                  </div>
                )}

                {msg.sender === "assistant" && (
                  <div className="message-actions-bar">
                    <button
                      type="button"
                      className="speech-btn"
                      onClick={() => handleSpeak(msg, idx)}
                      aria-label={
                        speakingIdx === idx ? "Stop speaking" : "Listen to answer"
                      }
                      title="Read aloud in local voice"
                    >
                      {speakingIdx === idx ? (
                        <>
                          <VolumeX size={15} /> Stop listening
                        </>
                      ) : (
                        <>
                          <Volume2 size={15} /> Listen ({language.toUpperCase()})
                        </>
                      )}
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))}

          {loading && (
            <div className="chat-message-row bot-row loading-row">
              <div className="message-avatar">
                <Bot size={18} />
              </div>
              <div className="message-bubble loading-bubble">
                <LoaderCircle size={18} className="spin text-blue" />
                <span>Formulating safety-grounded response...</span>
              </div>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {/* Input Bar with Voice Support */}
        <div className="chat-input-container">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              handleSendMessage();
            }}
            className="chat-input-form"
          >
            <input
              type="text"
              className="chat-text-input"
              placeholder={
                language === "ta"
                  ? "கேள்வியைத் தட்டச்சு செய்யவும் அல்லது பேசவும்..."
                  : language === "hi"
                  ? "प्रश्न टाइप करें या बोलें..."
                  : "Type your medicine question or speak..."
              }
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
              disabled={loading}
            />

            <div className="chat-input-actions">
              <VoiceInput
                language={language}
                indicSttAvailable={indicSttAvailable}
                onTranscript={handleVoiceTranscript}
              />

              <button
                type="submit"
                className="button primary send-button"
                disabled={loading || !inputText.trim()}
                aria-label="Send message"
              >
                <Send size={16} />
              </button>
            </div>
          </form>

          <p className="chat-disclaimer-note">
            <ShieldCheck size={13} />
            <span>
              MediVision Assistant provides reference information. It never prescribes,
              diagnoses, or calculates custom doses. Always follow your doctor&apos;s instructions.
            </span>
          </p>
        </div>
      </div>
    </div>
  );
}
