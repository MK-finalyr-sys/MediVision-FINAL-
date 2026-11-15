"use client";
import { useEffect, useRef, useState } from "react";
import type { Worker } from "tesseract.js";
import {
  Camera,
  Upload,
  Search,
  ScanLine,
  ArrowRight,
  Check,
  ImageIcon,
  Sun,
  Focus,
  Video,
  X,
  LoaderCircle,
  AlertCircle,
  RotateCcw,
  ShieldCheck,
  ChevronRight,
  ShieldAlert,
  Coins,
  BookmarkPlus,
  ExternalLink,
  Layers,
  Sparkles,
  Info,
} from "lucide-react";
import { medicines, registerAIMedicines, findCatalogSaltMatchHelper } from "@/lib/catalog";
import type { Medicine } from "@/lib/contracts";
import { confidenceTier, matchMedicines, searchMedicines, type Match } from "@/lib/engine";
import { preprocessImage, isBlurry } from "@/lib/image";
import {
  aiCandidates,
  aiIdentify,
  backendToMedicine,
  candidateToMedicine,
  type Candidate,
  type CandidatesResult,
  type AIBackendResult,
  type VisionEvidence,
} from "@/lib/ai-backend";
import { PrivacyLine } from "./ui";

type Stage = "idle" | "Captured" | "Enhancing" | "Reading text" | "Matching" | "Complete";
const stages: Stage[] = ["Captured", "Enhancing", "Reading text", "Matching"];

interface ScanViewProps {
  onOpen: (m: Medicine, score?: number) => void;
  focusSearch?: boolean;
  onCheckSafety?: (m: Medicine) => void;
  onCheckPricing?: (m: Medicine) => void;
  onSave?: (m: Medicine) => void;
}

export function ScanView({
  onOpen,
  focusSearch = false,
  onCheckSafety,
  onCheckPricing,
  onSave,
}: ScanViewProps) {
  const [query, setQuery] = useState("");
  const [browse, setBrowse] = useState(false);
  const [stage, setStage] = useState<Stage>("idle");
  const [progress, setProgress] = useState(0);
  const [ocrStatus, setOcrStatus] = useState("");
  const [error, setError] = useState("");
  const [uncertain, setUncertain] = useState(false);
  const [previews, setPreviews] = useState<{ before: string; after: string; variance: number } | null>(null);
  const [text, setText] = useState("");
  const [candidate, setCandidate] = useState<Match | null>(null);
  const [live, setLive] = useState(false);

  // AI Pipeline State
  const [aiLoading, setAiLoading] = useState(false);
  const [aiResult, setAiResult] = useState<AIBackendResult | null>(null);
  const [aiMedicine, setAiMedicine] = useState<Medicine | null>(null);
  const [candidatesData, setCandidatesData] = useState<CandidatesResult | null>(null);
  const [savedSuccess, setSavedSuccess] = useState(false);

  const fileRef = useRef<HTMLInputElement>(null);
  const galleryRef = useRef<HTMLInputElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const workerRef = useRef<Worker | null>(null);
  const lastHash = useRef("");
  const run = useRef(0);
  const [aiImageB64, setAiImageB64] = useState<string | undefined>(undefined);

  const busy = stage !== "idle" && stage !== "Complete";

  useEffect(() => {
    if (focusSearch) searchRef.current?.focus();
  }, [focusSearch]);

  useEffect(() => {
    if (live && videoRef.current && streamRef.current) {
      videoRef.current.srcObject = streamRef.current;
      videoRef.current
        .play()
        .catch(() => setError("The camera preview could not start. Use Take a photo instead."));
    }
  }, [live]);

  useEffect(() => {
    const runRef = run;
    const stream = streamRef;
    const worker = workerRef;
    return () => {
      runRef.current++;
      stream.current?.getTracks().forEach((t) => t.stop());
      void worker.current?.terminate();
    };
  }, []);

  function stopCamera() {
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    setLive(false);
  }

  async function startCamera() {
    setError("");
    try {
      if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia) {
        throw new Error("unsupported");
      }
      stopCamera();
      streamRef.current = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1600 } },
        audio: false,
      });
      setLive(true);
    } catch {
      setError("Live camera is unavailable or permission was denied. Use Take a photo or choose an image from your gallery instead.");
      fileRef.current?.click();
    }
  }

  async function triggerAIPipeline(ocrText: string, imageB64?: string, autoOpen = true) {
    if (!ocrText.trim()) return;
    setAiLoading(true);

    try {
      // Parallel fetch to /identify and /candidates
      const [idRes, candRes] = await Promise.all([
        aiIdentify(ocrText),
        aiCandidates(ocrText, imageB64, 5),
      ]);

      setCandidatesData(candRes);

      let finalMed: Medicine | null = null;
      let matchScore = 0.85;

      if (idRes && idRes.found) {
        setAiResult(idRes);
        const mapped = backendToMedicine(idRes);
        if (mapped) {
          finalMed = mapped;
          setAiMedicine(mapped);
          registerAIMedicines([mapped]);
        }
      } else if (candRes && candRes.found && candRes.candidates.length > 0) {
        const topCand = candRes.candidates[0];
        const catalogMatch = medicines.find(
          (m) => m.activeIngredient.toLowerCase() === topCand.salt.toLowerCase()
        );
        finalMed = catalogMatch || candidateToMedicine(topCand);
        setAiMedicine(finalMed);
        registerAIMedicines([finalMed]);
        matchScore = topCand.probability;
      }

      if (candRes && !candRes.found && candRes.note === "NO_MATCH") {
        setUncertain(true);
      }

      // Check for strong match vs ambiguous match
      const topCandProb = candRes?.candidates?.[0]?.probability ?? 0;
      const isStrongMatch =
        (idRes?.verificationStatus === "verified-online" || topCandProb >= 0.7) &&
        (candRes?.candidates?.length === 1 || topCandProb >= 0.75);

      if (finalMed && autoOpen && isStrongMatch) {
        // Automatically open the medicine popup in confirmation mode for strong matches
        onOpen(finalMed, topCandProb || matchScore);
      }
    } catch (e) {
      console.warn("AI pipeline error:", e);
    } finally {
      setAiLoading(false);
    }
  }

  async function processFile(file: Blob) {
    const current = ++run.current;
    setError("");
    setUncertain(false);
    setCandidate(null);
    setText("");
    setPreviews(null);
    setProgress(0);
    setStage("Captured");
    setAiResult(null);
    setAiMedicine(null);
    setCandidatesData(null);
    setSavedSuccess(false);
    stopCamera();

    try {
      // Convert image to base64 for vision classifier
      let b64Str: string | undefined = undefined;
      try {
        const reader = new FileReader();
        reader.onload = () => {
          if (typeof reader.result === "string") {
            b64Str = reader.result;
            setAiImageB64(reader.result);
          }
        };
        reader.readAsDataURL(file);
      } catch { }

      await new Promise<void>((resolve) => requestAnimationFrame(() => resolve()));
      setStage("Enhancing");
      const processed = await preprocessImage(file);
      if (current !== run.current) return;
      setPreviews(processed);

      if (processed.hash === lastHash.current) {
        throw new Error("This is the same photo as your last capture. Please take a new photo of the printed side.");
      }
      lastHash.current = processed.hash;

      if (isBlurry(processed.variance)) {
        throw new Error("Photo is blurry — please retake with steady hands and clear lighting.");
      }

      setStage("Reading text");
      setOcrStatus("Loading on-device reading engine…");
      const { createWorker, PSM } = await import("tesseract.js");
      const worker = await createWorker("eng", 1, {
        workerPath: "/ocr/worker.min.js",
        corePath: "/ocr",
        langPath: "/ocr",
        workerBlobURL: false,
        logger: (m) => {
          if (current === run.current) {
            setOcrStatus(m.status);
            if (m.status === "recognizing text") {
              setProgress(Math.round(m.progress * 100));
            }
          }
        },
      });

      if (current !== run.current) {
        await worker.terminate();
        return;
      }
      workerRef.current = worker;

      await worker.setParameters({
        tessedit_pageseg_mode: PSM.SPARSE_TEXT,
        preserve_interword_spaces: "1",
      });

      const { data } = await worker.recognize(processed.canvas);
      await worker.terminate();
      workerRef.current = null;

      if (current !== run.current) return;
      const recognizedText = data.text;
      setText(recognizedText);
      setStage("Matching");

      if (/\b(product image|coming soon|no image available|placeholder)\b/i.test(recognizedText)) {
        throw new Error("This looks like a placeholder image. Please take a new photo of your medicine strip.");
      }

      // 1. Run local catalog matcher
      const result = matchMedicines(recognizedText, medicines, data.confidence);
      if (result.multiple) {
        setError("More than one medicine may be visible. Please photograph one strip at a time.");
        setStage("Complete");
        return;
      }

      const top = result.matches[0];
      if (top && confidenceTier(top.score) === "HIGH") {
        setCandidate(top);
        setAiMedicine(top.medicine);
      } else if (top && confidenceTier(top.score) === "MEDIUM") {
        setCandidate(top);
      } else {
        setUncertain(true);
      }

      setStage("Complete");

      // 2. Trigger AI identification & candidate ranking pipeline
      void triggerAIPipeline(recognizedText, b64Str);
    } catch (e) {
      if (current !== run.current) return;
      setError(e instanceof Error ? e.message : "The scan could not finish. Retake the photo or use manual search.");
      setStage("Complete");
      if (workerRef.current) {
        await workerRef.current.terminate().catch(() => undefined);
        workerRef.current = null;
      }
    }
  }

  function capture() {
    const video = videoRef.current;
    if (!video || !video.videoWidth) {
      setError("The camera is not ready yet. Try again or use Take a photo.");
      return;
    }
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth;
    canvas.height = video.videoHeight;
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      setError("Camera capture is unavailable. Use Take a photo instead.");
      return;
    }
    ctx.drawImage(video, 0, 0);
    canvas.toBlob(
      (blob) => {
        if (blob) void processFile(blob);
        else setError("The photo could not be captured. Please try again.");
      },
      "image/jpeg",
      0.95
    );
  }

  function handleSelectCandidate(cand: Candidate) {
    const matched = medicines.find(
      (m) => m.activeIngredient.toLowerCase() === cand.salt.toLowerCase()
    );
    if (matched) {
      setAiMedicine(matched);
      onOpen(matched, cand.probability);
    } else {
      const syntheticMed = candidateToMedicine(cand);
      registerAIMedicines([syntheticMed]);
      setAiMedicine(syntheticMed);
      onOpen(syntheticMed, cand.probability);
      void aiIdentify(cand.salt).then((res) => {
        if (res && res.found) {
          const fullMed = backendToMedicine(res);
          if (fullMed) {
            registerAIMedicines([fullMed]);
            setAiMedicine(fullMed);
          }
        }
      });
    }
  }

  function handleSaveCurrent() {
    if (aiMedicine && onSave) {
      onSave(aiMedicine);
      setSavedSuccess(true);
    }
  }

  const results = searchMedicines(query, medicines);

  return (
    <div className="page-enter">
      <div className="page-heading">
        <div>
          <p className="eyebrow">SMART MEDICINE SCANNER</p>
          <h1>Scan & Identify Your Medicine</h1>
          <p>
            On-device OCR, CRF Named Entity Recognition, and damaged-strip candidate ranking.
          </p>
        </div>
        <span className="pill-badge">
          <ShieldCheck size={16} /> On-device OCR + CRF NER
        </span>
      </div>

      <div className="scan-layout">
        <section className="panel scan-panel">
          <div className="section-title">
            <span className="icon-tile blue">
              <ScanLine size={23} />
            </span>
            <div>
              <h2>Scan a medicine strip</h2>
              <p>Photograph the printed side showing medicine name and strength</p>
            </div>
          </div>

          <input
            ref={fileRef}
            data-testid="capture-input"
            className="visually-hidden"
            type="file"
            accept="image/*"
            capture="environment"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void processFile(f);
            }}
            aria-label="Take a medicine photo"
            disabled={busy}
          />

          <input
            ref={galleryRef}
            data-testid="gallery-input"
            className="visually-hidden"
            type="file"
            accept="image/*"
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) void processFile(f);
            }}
            aria-label="Upload a medicine photo"
            disabled={busy}
          />

          {live ? (
            <div className="live-camera">
              <video
                ref={videoRef}
                autoPlay
                muted
                playsInline
                aria-label="Live rear-camera preview"
              />
              <div className="camera-frame" />
              <div className="camera-controls">
                <button type="button" className="button primary" onClick={capture}>
                  <Camera size={21} /> Capture photo
                </button>
                <button
                  type="button"
                  className="icon-button"
                  aria-label="Close camera"
                  onClick={stopCamera}
                >
                  <X />
                </button>
              </div>
            </div>
          ) : (
            <div className={`upload-zone ${busy ? "is-busy" : ""}`}>
              <div className="scan-visual">
                <span className="scan-corner tl" />
                <span className="scan-corner tr" />
                <span className="scan-corner bl" />
                <span className="scan-corner br" />
                <div className="mini-blister">
                  {Array.from({ length: 6 }, (_, i) => (
                    <i key={i} />
                  ))}
                </div>
              </div>
              <h3>{busy ? "Reading your medicine..." : "A little clarity is one photo away"}</h3>
              <p>Keep the medicine name and strength clearly in view.</p>
              <button
                type="button"
                className="button primary"
                disabled={busy}
                onClick={() => fileRef.current?.click()}
              >
                {busy ? (
                  <LoaderCircle className="spin" size={21} />
                ) : (
                  <Camera size={21} />
                )}
                {busy ? "Processing strip..." : "Take a photo"}
              </button>
              <div className="capture-alternatives">
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => galleryRef.current?.click()}
                >
                  <Upload size={17} /> Upload from gallery
                </button>
                <span>or</span>
                <button
                  type="button"
                  className="text-button"
                  disabled={busy}
                  onClick={() => void startCamera()}
                >
                  <Video size={18} /> Live camera
                </button>
              </div>
            </div>
          )}

          {stage !== "idle" && (
            <div className="pipeline" aria-live="polite">
              <div className="pipeline-stages">
                {stages.map((s, i) => (
                  <span
                    key={s}
                    className={
                      stage === "Complete" || stages.indexOf(stage) > i
                        ? "done"
                        : stage === s
                          ? "current"
                          : ""
                    }
                  >
                    {stage === "Complete" || stages.indexOf(stage) > i ? (
                      <Check size={14} />
                    ) : (
                      <i>{i + 1}</i>
                    )}
                    {s}
                  </span>
                ))}
              </div>
              {stage === "Reading text" && (
                <>
                  <progress max="100" value={progress} aria-label="OCR progress" />
                  <p>
                    {ocrStatus} {progress > 0 ? `${progress}%` : ""}
                  </p>
                </>
              )}
            </div>
          )}

          {error && (
            <div className="notice error" role="alert">
              <AlertCircle size={21} />
              <div>
                <strong>{error}</strong>
                <button
                  type="button"
                  className="text-button"
                  onClick={() => fileRef.current?.click()}
                >
                  <RotateCcw size={16} /> Retake photo
                </button>
              </div>
            </div>
          )}

          {/* AI IDENTIFIED RESULT CARD */}
          {(aiMedicine || aiResult || candidate) && stage === "Complete" && (
            <div className="panel scan-ai-identified-card">
              <div className="ai-identified-header">
                <div>
                  <span className="eyebrow-chip">
                    <Sparkles size={13} /> AI IDENTIFIED MEDICINE
                  </span>
                  <h2>{aiMedicine?.name || aiResult?.canonicalBrand || candidate?.medicine.name}</h2>
                  <p className="ai-active-salt">
                    Active Ingredient:{" "}
                    <strong>
                      {aiMedicine?.activeIngredient ||
                        aiResult?.salt ||
                        candidate?.medicine.activeIngredient}
                    </strong>
                  </p>
                </div>

                <div className="ai-meta-chips">
                  {(aiMedicine?.strength || aiResult?.entities?.find((e) => e.label === "STRENGTH")?.text) && (
                    <span className="strength-chip">
                      {aiMedicine?.strength ||
                        aiResult?.entities?.find((e) => e.label === "STRENGTH")?.text}
                    </span>
                  )}
                  {(aiMedicine?.form || aiResult?.entities?.find((e) => e.label === "FORM")?.text) && (
                    <span className="form-chip">
                      {aiMedicine?.form ||
                        aiResult?.entities?.find((e) => e.label === "FORM")?.text}
                    </span>
                  )}
                  {aiResult?.rxnormId && (
                    <span className="rxnorm-chip" title="RxNorm verified">
                      RxNorm: {aiResult.rxnormId}
                    </span>
                  )}
                </div>
              </div>

              {/* Extracted NER Entities Bar */}
              {aiResult?.entities && aiResult.entities.length > 0 && (
                <div className="ner-entities-box">
                  <span className="ner-title">CRF NER Extracted Entities:</span>
                  <div className="ner-chip-list">
                    {aiResult.entities.map((ent, idx) => (
                      <span key={idx} className={`ner-chip ner-${ent.label.toLowerCase()}`}>
                        <small>{ent.label}</small>
                        <strong>{ent.text}</strong>
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Discrepancy & Uncertainty Alerts */}
              {candidatesData?.uncertainties && candidatesData.uncertainties.length > 0 && (
                <div className="notice warning" role="alert" style={{ margin: "16px 0" }}>
                  <AlertCircle size={20} />
                  <div>
                    <strong>Verification Discrepancies Detected:</strong>
                    <ul style={{ margin: "4px 0 0 16px", padding: 0 }}>
                      {candidatesData.uncertainties.map((u, idx) => (
                        <li key={idx}>{u}</li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}

              {/* Pill Vision Classification Evidence */}
              {candidatesData?.visionEvidence && candidatesData.visionEvidence.length > 0 && (
                <div className="vision-evidence-banner">
                  <Layers size={16} className="text-blue" />
                  <div>
                    <strong>Optional Pill Classifier (Shape/Color only — not packaging evidence):</strong>
                    <span>
                      Detected{" "}
                      {candidatesData.visionEvidence
                        .map(
                          (v) =>
                            `${v.labelPretty || v.label} (${Math.round(v.probability * 100)}%)`
                        )
                        .join(", ")}
                    </span>
                  </div>
                </div>
              )}

              {/* Quick Actions Bar */}
              <div className="scan-actions-grid">
                {aiMedicine && (
                  <button
                    type="button"
                    className="button primary"
                    onClick={() => onOpen(aiMedicine, candidate?.score || 0.9)}
                  >
                    View Medicine Details &amp; Confirm <ArrowRight size={16} />
                  </button>
                )}

                {onCheckSafety && (aiMedicine || aiResult?.salt) && (
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() =>
                      onCheckSafety(
                        aiMedicine ||
                        medicines.find(
                          (m) =>
                            m.activeIngredient.toLowerCase() ===
                            (aiResult?.salt || "").toLowerCase()
                        ) ||
                        medicines[0]
                      )
                    }
                  >
                    <ShieldAlert size={16} /> Check Safety
                  </button>
                )}

                {onCheckPricing && (aiMedicine || aiResult?.salt) && (
                  <button
                    type="button"
                    className="button secondary"
                    onClick={() =>
                      onCheckPricing(
                        aiMedicine ||
                        medicines.find(
                          (m) =>
                            m.activeIngredient.toLowerCase() ===
                            (aiResult?.salt || "").toLowerCase()
                        ) ||
                        medicines[0]
                      )
                    }
                  >
                    <Coins size={16} /> Compare Generic Price
                  </button>
                )}

                {onSave && aiMedicine && (
                  <button
                    type="button"
                    className={`button ${savedSuccess ? "taken-button" : "secondary"}`}
                    onClick={handleSaveCurrent}
                    disabled={savedSuccess}
                  >
                    <BookmarkPlus size={16} />
                    {savedSuccess ? "Saved to Cabinet" : "Save to Cabinet"}
                  </button>
                )}
              </div>

              {/* Verified Sources */}
              {aiResult?.sources && aiResult.sources.length > 0 && (
                <div className="scan-sources-row">
                  <span>Authoritative Sources:</span>
                  {aiResult.sources.slice(0, 3).map((s, idx) => (
                    <a
                      key={idx}
                      href={s.url}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="source-chip-link"
                    >
                      {s.title || "Reference"} <ExternalLink size={11} />
                    </a>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* CANDIDATES LIST FOR DAMAGED STRIPS */}
          {candidatesData?.candidates && candidatesData.candidates.length > 1 && (
            <div className="panel candidates-ranked-card">
              <div className="section-title">
                <span className="icon-tile lilac">
                  <Layers size={20} />
                </span>
                <div>
                  <h3>Proposed Candidates (Damaged-Strip Probability Analysis)</h3>
                  <p>
                    Please select and confirm your medicine below: Packaging text is partially obscured or matches multiple formulations.
                  </p>
                </div>
              </div>

              <div className="candidates-list">
                {candidatesData.candidates.map((cand, idx) => {
                  const probPct = Math.round(cand.probability * 100);
                  return (
                    <div
                      key={idx}
                      className="candidate-row"
                      onClick={() => handleSelectCandidate(cand)}
                      role="button"
                      tabIndex={0}
                    >
                      <div className="cand-info">
                        <strong>{cand.salt}</strong>
                        {cand.matchedBrand && (
                          <small>Matched Brand: {cand.matchedBrand}</small>
                        )}
                        {cand.strengthDetected && (
                          <span className="cand-strength">{cand.strengthDetected}</span>
                        )}
                        <span className="cand-basis">Basis: {cand.basis}</span>
                      </div>

                      <div className="cand-probability-box">
                        <div className="cand-prob-bar-wrapper">
                          <div
                            className="cand-prob-bar-fill"
                            style={{ width: `${probPct}%` }}
                          />
                        </div>
                        <strong className="cand-percent">{probPct}%</strong>
                      </div>

                      <ChevronRight size={16} className="cand-arrow" />
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {candidatesData && !candidatesData.found && candidatesData.note === "NO_MATCH" && !aiLoading && (
            <div className="notice error" role="alert">
              <AlertCircle size={23} />
              <div>
                <strong>No verified Indian medicine found for &quot;{text.slice(0, 40) || "captured strip"}&quot;</strong>
                <p>The text could not be verified against pharmaceutical databases. Check that the medicine name and strength are clearly visible or consult your pharmacist.</p>
              </div>
            </div>
          )}

          {uncertain && !aiLoading && !aiMedicine && (!candidatesData || candidatesData.found) && (
            <div className="notice warning" role="alert">
              <AlertCircle size={23} />
              <div>
                <strong>Low confidence on strip text. Please confirm with your pharmacist.</strong>
                <p>You can also search the reference list by the name printed on your strip.</p>
              </div>
            </div>
          )}

          {previews && (
            <div className="previews">
              <h3>Captured Photo Inspection</h3>
              <div className="preview-grid">
                <figure>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={previews.before} alt="Original captured medicine strip" />
                  <figcaption>
                    <ImageIcon size={16} /> Original photo
                  </figcaption>
                </figure>
                <figure>
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img src={previews.after} alt="Enhanced medicine strip" />
                  <figcaption>
                    <Focus size={16} /> Contrast-enhanced for OCR
                  </figcaption>
                </figure>
              </div>
              <details>
                <summary>View OCR raw details</summary>
                <p>Sharpness (Laplacian variance): {previews.variance.toFixed(1)}.</p>
                <pre>{text || "No text read yet."}</pre>
              </details>
            </div>
          )}

          <div className="scan-privacy">
            <PrivacyLine />
            <span>Images are processed locally and never stored on remote servers.</span>
          </div>
        </section>

        {/* Right Column: Catalog Search */}
        <aside className="scan-side">
          <section className="panel manual-search">
            <span className="icon-tile lilac">
              <Search size={23} />
            </span>
            <h2>Know the name already?</h2>
            <p>Find it in our 40-medicine reference catalog.</p>
            <label className="search-field">
              <Search size={20} />
              <input
                ref={searchRef}
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                placeholder="Search name or ingredient"
                aria-label="Search medicines"
              />
              {query && (
                <button
                  type="button"
                  className="icon-button"
                  onClick={() => {
                    setQuery("");
                    searchRef.current?.focus();
                  }}
                  aria-label="Clear search"
                >
                  <X size={17} />
                </button>
              )}
            </label>
            <div className="search-results">
              {results.slice(0, query || browse ? 40 : 4).map((m) => (
                <button
                  type="button"
                  className="search-result"
                  key={m.id}
                  onClick={() => onOpen(m)}
                >
                  <span>
                    <strong>{m.name}</strong>
                    <small>
                      {m.activeIngredient}
                      {m.activeIngredient2 ? ` + ${m.activeIngredient2}` : ""} · {m.strength}
                    </small>
                  </span>
                  <ChevronRight size={18} />
                </button>
              ))}
              {!results.length && (
                <div className="empty-search">
                  <Search size={25} />
                  <p>Not found in the 40-medicine catalog.</p>
                  <small>Try scanning the strip or searching the salt name above.</small>
                </div>
              )}
            </div>
            {!query && !browse && (
              <button
                type="button"
                className="text-button browse-all"
                onClick={() => setBrowse(true)}
              >
                Browse all 40 medicines <ArrowRight size={17} />
              </button>
            )}
            <small className="reference-note">
              Not a full drug database. Always verify your own packet.
            </small>
          </section>

          <section className="photo-tips">
            <h3>A clearer photo, a better start</h3>
            <p>
              <Sun size={20} />
              <span>Find good, even light. Avoid flash glare.</span>
            </p>
            <p>
              <ScanLine size={20} />
              <span>Photograph one strip, printed side up.</span>
            </p>
            <p>
              <Focus size={20} />
              <span>Hold steady. Keep all letters in focus.</span>
            </p>
          </section>
        </aside>
      </div>
    </div>
  );
}
