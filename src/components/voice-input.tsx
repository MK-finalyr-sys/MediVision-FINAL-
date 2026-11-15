"use client";
import { useState, useRef, useEffect } from "react";
import { Mic, Square, LoaderCircle, Check, RotateCcw, AlertCircle } from "lucide-react";
import { aiTranscribe } from "@/lib/ai-backend";

interface VoiceInputProps {
  language: "en" | "ta" | "hi";
  indicSttAvailable: boolean;
  onTranscript: (text: string) => void;
  placeholder?: string;
  className?: string;
}

type VoiceState = "idle" | "recording" | "transcribing" | "reviewing";

// SpeechRecognition typing for browsers that support it
interface SpeechRecognitionEvent {
  results: {
    [index: number]: {
      [index: number]: {
        transcript: string;
      };
    };
  };
}

interface SpeechRecognitionInstance {
  continuous: boolean;
  interimResults: boolean;
  lang: string;
  start: () => void;
  stop: () => void;
  onresult: (event: SpeechRecognitionEvent) => void;
  onerror: (event: { error: string }) => void;
  onend: () => void;
}

export function VoiceInput({
  language,
  indicSttAvailable,
  onTranscript,
  className = "",
}: VoiceInputProps) {
  const [state, setState] = useState<VoiceState>("idle");
  const [draftText, setDraftText] = useState("");
  const [engineUsed, setEngineUsed] = useState<string>("");
  const [errorMsg, setErrorMsg] = useState("");
  const [recordingSeconds, setRecordingSeconds] = useState(0);

  const mediaRecorderRef = useRef<MediaRecorder | null>(null);
  const audioChunksRef = useRef<Blob[]>([]);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const recognitionRef = useRef<SpeechRecognitionInstance | null>(null);

  const langCode = language === "ta" ? "ta-IN" : language === "hi" ? "hi-IN" : "en-IN";

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (recognitionRef.current) {
        try { recognitionRef.current.stop(); } catch {}
      }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
        try { mediaRecorderRef.current.stop(); } catch {}
      }
    };
  }, []);

  async function startRecording() {
    setErrorMsg("");
    setDraftText("");
    setRecordingSeconds(0);

    // If Indic STT is available on backend and user is on Tamil/Hindi, try recording audio for Indic STT
    if (indicSttAvailable && (language === "ta" || language === "hi")) {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        audioChunksRef.current = [];
        const recorder = new MediaRecorder(stream);
        mediaRecorderRef.current = recorder;

        recorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunksRef.current.push(e.data);
        };

        recorder.onstop = async () => {
          stream.getTracks().forEach((track) => track.stop());
          if (timerRef.current) clearInterval(timerRef.current);

          const audioBlob = new Blob(audioChunksRef.current, { type: "audio/webm" });
          if (audioBlob.size < 500) {
            setState("idle");
            return;
          }

          setState("transcribing");
          try {
            const reader = new FileReader();
            reader.readAsDataURL(audioBlob);
            reader.onloadend = async () => {
              const b64 = reader.result as string;
              const res = await aiTranscribe(b64, language);
              if (res && res.ok && res.text) {
                setDraftText(res.text);
                setEngineUsed(res.model || "Indic Conformer STT");
                setState("reviewing");
              } else {
                // Fallback to browser recognition if Indic STT failed
                startBrowserRecognition();
              }
            };
          } catch {
            startBrowserRecognition();
          }
        };

        recorder.start();
        setState("recording");
        timerRef.current = setInterval(() => {
          setRecordingSeconds((s) => s + 1);
        }, 1000);
        return;
      } catch (err) {
        console.warn("MediaRecorder permission or device error, falling back to Web Speech", err);
      }
    }

    // Otherwise use Web Speech API fallback
    startBrowserRecognition();
  }

  function startBrowserRecognition() {
    const windowWithSpeech = window as unknown as {
      SpeechRecognition?: new () => SpeechRecognitionInstance;
      webkitSpeechRecognition?: new () => SpeechRecognitionInstance;
    };
    const SpeechRecognitionClass =
      windowWithSpeech.SpeechRecognition || windowWithSpeech.webkitSpeechRecognition;
    if (!SpeechRecognitionClass) {
      setErrorMsg("Voice input is not supported in this browser. Please type your query.");
      setState("idle");
      return;
    }

    try {
      const recognition: SpeechRecognitionInstance = new SpeechRecognitionClass();
      recognitionRef.current = recognition;
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = langCode;

      recognition.onresult = (event: SpeechRecognitionEvent) => {
        const recognized = event.results[0]?.[0]?.transcript;
        if (recognized) {
          setDraftText(recognized);
          setEngineUsed("Browser Speech Recognition");
          setState("reviewing");
        } else {
          setState("idle");
        }
      };

      recognition.onerror = (e) => {
        const langName = language === "ta" ? "Tamil" : language === "hi" ? "Hindi" : "English";
        if (e.error === "language-not-supported") {
          setErrorMsg(`${langName} speech recognition is not supported by your current browser engine. Please type in ${langName} or check device language settings.`);
        } else if (e.error === "not-allowed") {
          setErrorMsg("Microphone permission was denied. Please allow microphone access to use voice input.");
        } else if (e.error === "no-speech") {
          setErrorMsg(`No ${langName} speech was detected. Please tap Speak and try again.`);
        } else {
          setErrorMsg(`${langName} speech recognition error: ${e.error || "could not recognize speech"}`);
        }
        setState("idle");
      };

      recognition.onend = () => {
        if (state === "recording") {
          setState("idle");
        }
        if (timerRef.current) clearInterval(timerRef.current);
      };

      recognition.start();
      setState("recording");
      timerRef.current = setInterval(() => {
        setRecordingSeconds((s) => s + 1);
      }, 1000);
    } catch (e) {
      setErrorMsg("Speech recognition could not be started.");
      setState("idle");
    }
  }

  function stopRecording() {
    if (timerRef.current) clearInterval(timerRef.current);
    if (mediaRecorderRef.current && mediaRecorderRef.current.state === "recording") {
      mediaRecorderRef.current.stop();
    } else if (recognitionRef.current) {
      try { recognitionRef.current.stop(); } catch {}
    }
  }

  function handleConfirm() {
    if (draftText.trim()) {
      onTranscript(draftText.trim());
      setDraftText("");
      setState("idle");
    }
  }

  function handleCancel() {
    setDraftText("");
    setState("idle");
  }

  return (
    <div className={`voice-input-container ${className}`}>
      {state === "idle" && (
        <div className="voice-idle-row">
          <button
            type="button"
            className="voice-button"
            onClick={startRecording}
            title={
              indicSttAvailable
                ? `Record voice (${language.toUpperCase()} · AI4Bharat Indic Conformer active)`
                : `Record voice (${langCode} · Browser Web Speech)`
            }
            aria-label="Start voice input"
          >
            <Mic size={18} />
            <span>Speak</span>
          </button>
          <span className="voice-engine-badge">
            {indicSttAvailable ? "Indic STT ready" : "Web Speech"}
          </span>
        </div>
      )}

      {state === "recording" && (
        <div className="voice-recording-box" role="status">
          <span className="recording-pulse" />
          <span className="recording-timer">
            Listening... {recordingSeconds}s ({langCode})
          </span>
          <button
            type="button"
            className="button compact danger stop-recording-button"
            onClick={stopRecording}
            aria-label="Stop recording"
          >
            <Square size={14} />
            <span>Done</span>
          </button>
        </div>
      )}

      {state === "transcribing" && (
        <div className="voice-transcribing-box" role="status">
          <LoaderCircle size={16} className="spin" />
          <span>Processing speech with AI model...</span>
        </div>
      )}

      {state === "reviewing" && (
        <div className="voice-review-box">
          <div className="voice-review-header">
            <span>Recognized ({engineUsed}):</span>
            <button
              type="button"
              className="text-button compact"
              onClick={startRecording}
            >
              <RotateCcw size={14} /> Retake
            </button>
          </div>
          <input
            type="text"
            className="voice-review-input"
            value={draftText}
            onChange={(e) => setDraftText(e.target.value)}
            placeholder="Edit recognized text..."
            autoFocus
          />
          <div className="button-row">
            <button
              type="button"
              className="button compact secondary"
              onClick={handleCancel}
            >
              Cancel
            </button>
            <button
              type="button"
              className="button compact primary"
              onClick={handleConfirm}
              disabled={!draftText.trim()}
            >
              <Check size={14} /> Use this text
            </button>
          </div>
        </div>
      )}

      {errorMsg && (
        <div className="voice-error-text" role="alert">
          <AlertCircle size={14} />
          <span>{errorMsg}</span>
        </div>
      )}
    </div>
  );
}
