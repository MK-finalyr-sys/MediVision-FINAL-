// MediVision AI — backend client + adapter (FULLY INTEGRATED v3).
// Talks to the Phase-4 FastAPI backend through same-origin proxies under
// /api/ai/* and converts results into THIS app's Medicine contract so every
// AI match renders through the existing cards and storage untouched.
import { z } from "zod";
import { medicineSchema, identificationSchema, type Medicine } from "./contracts";
import { normalizeIngredients } from "./engine";
import { medicines, findCatalogSaltMatchHelper } from "./catalog";

// ---------- backend response (lenient — backend may be offline) ----------
const languageCardSchema = z.object({
  uses: z.string().optional(), beforeYouTake: z.array(z.string()).optional(),
  sideEffects: z.string().optional(), stopAndGetHelp: z.array(z.string()).optional(),
  preChecklist: z.array(z.string()).optional(),
});
const cardSchema = z.object({
  en: languageCardSchema.optional(), ta: languageCardSchema.optional(), hi: languageCardSchema.optional(),
  model: z.string().optional(), caveats: z.array(z.string()).optional(),
});
export const aiBackendResultSchema = z.object({
  available: z.boolean().optional(),
  found: z.boolean(),
  query: z.string().optional(),
  salt: z.string().nullable().optional(),
  brand: z.string().nullable().optional(),
  usName: z.string().nullable().optional(),
  strength: z.string().nullable().optional(),
  form: z.string().nullable().optional(),
  rxnormId: z.string().nullable().optional(),
  brandExamples: z.string().nullable().optional(),
  manufacturer: z.string().nullable().optional(),
  mappingBasis: z.string().optional(),
  canonicalBrand: z.string().nullable().optional(),
  canonicalSalt: z.string().nullable().optional(),
  nerModel: z.string().optional(),
  engine: z.string().optional(),
  entities: z.array(z.object({ label: z.string(), text: z.string(), start: z.number().optional(), end: z.number().optional() })).optional(),
  label: z.object({ uses: z.string().optional(), warnings: z.string().optional(), sideEffects: z.string().optional() }).optional(),
  genericPricing: z.record(z.string(), z.unknown()).nullable().optional(),
  webEvidence: z.array(z.object({ title: z.string().optional(), url: z.string(), snippet: z.string().optional(), host: z.string().optional() })).optional(),
  sources: z.array(z.object({ title: z.string().optional(), url: z.string(), sourceType: z.string().optional() })).optional(),
  card: cardSchema.nullable().optional(),
  ...identificationSchema.shape,
  verificationStatus: identificationSchema.shape.verificationStatus.default("candidate-needs-confirmation"),
  metadataWarnings: z.array(z.string()).optional(),
  note: z.string().optional(),
  uncertainties: z.array(z.string()).optional(),
});
export type AIBackendResult = z.infer<typeof aiBackendResultSchema>;

// ---------- client: /identify ----------
export class IdentificationError extends Error {
  constructor(public code: "timeout" | "unavailable" | "api" | "parse", message: string, public details: string[] = []) {
    super(message);
    this.name = "IdentificationError";
  }
}

async function identificationResponseError(response: Response): Promise<IdentificationError> {
  const envelope = z.object({ error: z.object({ code: z.enum(["timeout", "unavailable", "api", "parse"]) }) });
  const parsed = envelope.safeParse(await response.json().catch(() => null));
  const code = parsed.success ? parsed.data.error.code : response.status === 504 ? "timeout" : response.status === 503 ? "unavailable" : "api";
  const messages = {
    timeout: "Medicine identification timed out. Please retry.",
    unavailable: "The identification backend is unavailable. Please retry.",
    api: "The identification service returned an error. Please retry.",
    parse: "The identification service returned unreadable data. Please retry.",
  };
  return new IdentificationError(code, messages[code]);
}

export function parseIdentification(data: unknown): AIBackendResult {
  const raw = z.record(z.string(), z.unknown()).safeParse(data);
  if (!raw.success) throw new IdentificationError("parse", "The identification response is not an object.");
  const sanitized = { ...raw.data };
  const metadataWarnings: string[] = [];
  // Invalid optional presentation data must not discard a valid identity.
  // Verification fields remain strict and are never removed by this recovery.
  const metadataFields = ["card", "label", "genericPricing", "entities", "sources", "webEvidence",
    "manufacturer", "brandExamples", "nerModel", "engine", "uncertainties"] as const;
  for (const field of metadataFields) {
    if (!aiBackendResultSchema.shape[field].safeParse(sanitized[field]).success) {
      delete sanitized[field];
      metadataWarnings.push(`Optional ${field} information could not be read. Review the package identity below.`);
    }
  }
  const parsed = aiBackendResultSchema.safeParse(sanitized);
  if (!parsed.success) {
    throw new IdentificationError("parse", "The identification response could not be read. Please retry.",
      parsed.error.issues.map(issue => issue.path.join(".")));
  }
  if (parsed.data.found && !parsed.data.salt?.trim()) {
    throw new IdentificationError("parse", "The identification response is missing its active ingredient.");
  }
  parsed.data.metadataWarnings = metadataWarnings;
  return parsed.data;
}

export async function aiIdentify(ocrText: string, imageOrTimeout?: string | number, timeoutMs = 125000): Promise<AIBackendResult | null> {
  // Existing callers pass a numeric timeout as argument #2. Photo-based
  // callers pass compressed image data in that position.
  const imageB64 = typeof imageOrTimeout === "string" ? imageOrTimeout : undefined;
  const actualTimeout = typeof imageOrTimeout === "number" ? imageOrTimeout : timeoutMs;
  const text = ocrText.trim();
  if (!text) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), actualTimeout);
  try {
    const res = await fetch("/api/ai/identify", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ocrText: text, imageB64 }), signal: controller.signal });
    if (!res.ok) throw await identificationResponseError(res);
    let data: unknown;
    try { data = await res.json(); }
    catch { throw new IdentificationError("parse", "The identification service returned unreadable data."); }
    const result = parseIdentification(data);
    if (result.available === false) throw new IdentificationError("unavailable", "The identification backend is unavailable. Please retry.");
    return result;
  } catch (error) {
    if (error instanceof IdentificationError) throw error;
    throw new IdentificationError(controller.signal.aborted ? "timeout" : "unavailable",
      controller.signal.aborted ? "Medicine identification timed out. Please retry." : "Could not reach the identification service. Check your connection and retry.");
  } finally { clearTimeout(timer); }
}

export function candidateAgreesWithIdentification(result: AIBackendResult, candidate: Candidate): boolean {
  const normalize = (value: string) => value.toLowerCase().replace(/\s+/g, " ").trim();
  const salts = [result.salt, result.canonicalSalt, result.usName].filter((value): value is string => !!value);
  if (!salts.some(salt => normalize(salt) === normalize(candidate.salt))) return false;
  if (candidate.strengthDetected && result.strength) {
    const rankedStrength = candidate.strengthDetected.toLowerCase().replace(/\s/g, "");
    const identifiedStrength = result.strength.toLowerCase().replace(/\s/g, "");
    const comparable = /^\d+(?:\.\d+)?$/.test(rankedStrength)
      ? identifiedStrength.match(/^\d+(?:\.\d+)?/)?.[0]
      : identifiedStrength;
    if (rankedStrength !== comparable) return false;
  }
  return true;
}

export function canAutoOpenIdentification(result: AIBackendResult, ranked: CandidatesResult | null): boolean {
  if (!result.found || result.requiresManualReview || result.conflicts.length || result.verificationStatus === "conflicting-identification") return false;
  const first = ranked?.candidates[0];
  if (first && !candidateAgreesWithIdentification(result, first)) return false;
  return result.verificationStatus === "verified-online" || result.mappingBasis === "indian-brand-index" || (!!first && first.probability >= 0.75);
}

// ---------- backend -> THIS app's Medicine ----------
const BEFORE_FALLBACK = ["Check the expiry date printed on the strip.", "Ask a pharmacist before combining it with other medicines.", "Tell your doctor about allergies and other health conditions."];
const HELP_FALLBACK = ["Signs of a serious allergic reaction, such as swelling of the face, lips or throat.", "Difficulty breathing, severe dizziness or fainting.", "Any severe or unusual symptom after taking your medicine."];
const CHECK_FALLBACK = ["The name and strength on your packet match this page.", "Your doctor or pharmacist has not told you to avoid this medicine.", "The packet is within its expiry date."];

function bulletize(text: string, min: number, max: number, fallback: string[]): string[] {
  const parts = (text || "").split(/(?<=[.;])\s+|;\s*/).map(s => s.trim().replace(/^[-•*\d.)\s]+/, "")).filter(s => s.length >= 8);
  const out = parts.slice(0, max);
  for (const f of fallback) { if (out.length >= min) break; if (!out.some(o => o.toLowerCase() === f.toLowerCase())) out.push(f); }
  return out.slice(0, max);
}

function sourceTypeFor(url: string): "label" | "government" | "medical-reference" {
  const u = url.toLowerCase();
  if (u.includes("fda.gov") || u.includes("dailymed")) return "label";
  if (u.includes(".gov") || u.includes(".nih.")) return "government";
  return "medical-reference";
}

function cleanStrength(raw: string | undefined): string {
  const s = (raw || "").replace(/(\d)(mg|mcg|g|iu|ml)\b/gi, (_m, n, u) => `${n} ${u.toLowerCase()}`).trim();
  return s || "as printed on packet";
}

function titleForm(raw: string | undefined): string {
  const f = (raw || "").trim();
  return f ? f[0].toUpperCase() + f.slice(1).toLowerCase() : "Not read";
}

function contentBlock(result: AIBackendResult, lang: "en" | "ta" | "hi", en: { uses: string; beforeYouTake: string[]; sideEffects: string; stopAndGetHelp: string[]; preChecklist: string[] }) {
  const card = result.card?.[lang] as Partial<Medicine["en"]> | undefined;
  if (!card || typeof card.uses !== "string" || card.uses.trim().length < 10) return en;
  const arr = (v: unknown, fb: string[]) => Array.isArray(v) ? v.filter((s): s is string => typeof s === "string" && s.trim().length > 3) : fb;
  return {
    uses: card.uses.trim(),
    beforeYouTake: bulletize(arr(card.beforeYouTake, en.beforeYouTake).join("; "), 3, 5, en.beforeYouTake),
    sideEffects: typeof card.sideEffects === "string" && card.sideEffects.trim().length >= 5 ? card.sideEffects.trim() : en.sideEffects,
    stopAndGetHelp: bulletize(arr(card.stopAndGetHelp, en.stopAndGetHelp).join("; "), 2, 4, en.stopAndGetHelp),
    preChecklist: bulletize(arr(card.preChecklist, en.preChecklist).join("; "), 2, 4, en.preChecklist),
  };
}

export function backendToMedicine(result: AIBackendResult): Medicine | null {
  const salt = (result.salt || "").trim();
  if (!result.found || !salt) return null;
  const brand = result.brand || result.canonicalBrand || result.entities?.find(e => e.label === "BRAND")?.text?.trim() || "";
  const strengthEntity = result.strength || result.entities?.find(e => e.label === "STRENGTH")?.text || "";
  const formEntity = result.form || result.entities?.find(e => e.label === "FORM")?.text || "";
  const en = {
    uses: (result.label?.uses || "").length >= 10 ? result.label!.uses!
      : (result.webEvidence?.map(w => w.snippet || "").find(s => s.trim().length >= 10) || `${salt} is listed in public medicine references. Confirm its use with your pharmacist.`),
    beforeYouTake: bulletize(result.label?.warnings || "", 3, 5, BEFORE_FALLBACK),
    sideEffects: (result.label?.sideEffects || "").length >= 5 ? result.label!.sideEffects!
      : "Public label data had no side-effect summary for this salt. See your medicine leaflet for the full list.",
    stopAndGetHelp: bulletize(result.label?.warnings || "", 2, 4, HELP_FALLBACK),
    preChecklist: CHECK_FALLBACK,
  };
  const seen = new Set<string>();
  const sources = [...(result.sources || []), ...(result.webEvidence || []).map(w => ({ title: w.title || w.host || "Web source", url: w.url })), { title: `Drugs.com search — ${salt}`, url: `https://www.drugs.com/search.php?searchterm=${encodeURIComponent(salt)}` }]
    .filter(s => s.url.startsWith("https://") && !seen.has(s.url) && seen.add(s.url))
    .slice(0, 4)
    .map(s => ({ title: (s.title || "Reference").slice(0, 110), url: s.url, sourceType: sourceTypeFor(s.url) }));
  const candidate: Medicine = {
    id: `ai-${([brand || salt, salt, strengthEntity, formEntity].join("-")).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`,
    name: brand || result.canonicalBrand || salt,
    aliases: [result.brandExamples, result.manufacturer, result.usName].filter((v): v is string => !!v),
    activeIngredient: salt,
    activeIngredient2: null,
    strength: cleanStrength(strengthEntity),
    form: titleForm(formEntity),
    category: result.mappingBasis || "AI identified",
    tags: ["all"],
    verified: false,
    identification: identificationSchema.parse(result),
    identityConfirmed: false,
    sources,
    en: contentBlock(result, "en", en),
    ta: contentBlock(result, "ta", en),
    hi: contentBlock(result, "hi", en),
  };
  try { return medicineSchema.parse(candidate); } catch { return null; }
}

export function candidateToMedicine(cand: Candidate): Medicine {
  const salt = cand.salt.trim();
  const brand = cand.matchedBrand || salt;
  const strength = cand.strengthDetected ? cleanStrength(cand.strengthDetected) : "as prescribed";
  const en = {
    uses: `${salt} is an active pharmaceutical substance identified from packaging analysis. Consult your doctor or pharmacist for prescribed indications.`,
    beforeYouTake: BEFORE_FALLBACK,
    sideEffects: "Consult your doctor or package leaflet for possible side effects.",
    stopAndGetHelp: HELP_FALLBACK,
    preChecklist: CHECK_FALLBACK,
  };
  const candidate: Medicine = {
    id: `cand-${(brand || salt).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "")}`,
    name: brand,
    aliases: [cand.usName, cand.matchedToken].filter((v): v is string => !!v),
    activeIngredient: salt,
    activeIngredient2: null,
    strength,
    form: "Tablet / Capsule",
    category: cand.basis || "Candidate Analysis",
    tags: ["all"],
    verified: false,
    sources: [
      {
        title: `Drugs.com — ${salt}`,
        url: `https://www.drugs.com/search.php?searchterm=${encodeURIComponent(salt)}`,
        sourceType: "medical-reference",
      },
    ],
    en,
    ta: {
      uses: `இந்த ${salt} மருந்து மருத்துவப் பரிந்துரையின்படி பயன்படுத்தப்படுகிறது. உங்கள் மருத்துவர் அல்லது மருந்தாளுனரிடம் ஆலோசனை பெறவும்.`,
      beforeYouTake: [
        "மருந்தை எடுக்கும் முன் காலாவதி தேதியை சரிபார்க்கவும்.",
        "ஒவ்வாமை அல்லது பிற நோய்கள் இருந்தால் மருத்துவரிடம் தெரிவிக்கவும்.",
        "மருந்தாளுனரிடம் கேட்காமல் மற்ற மருந்துகளுடன் சேர்த்து எடுக்க வேண்டாம்.",
      ],
      sideEffects: "அசாதாரண பக்க விளைவுகள் ஏற்பட்டால் மருத்துவரிடம் ஆலோசனை பெறவும்.",
      stopAndGetHelp: [
        "தீவிர ஒவ்வாமை: முக வீக்கம், அரிப்பு அல்லது மூச்சுத் திணறல்.",
        "மயக்கம் அல்லது தீவிர உடல் அசௌகரியம் ஏற்பட்டால் உடனே மருத்துவ உதவி பெறவும்.",
      ],
      preChecklist: CHECK_FALLBACK,
    },
    hi: {
      uses: `यह ${salt} दवा डॉक्टर के परामर्श के अनुसार उपयोग की जाती है। सही खुराक के लिए फार्मासिस्ट से पूछें।`,
      beforeYouTake: [
        "दवा लेने से पहले समाप्ति तिथि (expiry date) अवश्य जांचें।",
        "यदि एलर्जी या अन्य बीमारियां हैं तो डॉक्टर को बताएं।",
        "बिना डॉक्टर या फार्मासिस्ट की सलाह के अन्य दवाओं के साथ न लें।",
      ],
      sideEffects: "यदि कोई असामान्य दुष्प्रभाव दिखे तो तुरंत डॉक्टर से संपर्क करें।",
      stopAndGetHelp: [
        "गंभीर एलर्जी के लक्षण: चेहरे पर सूजन, लाल चकत्ते या सांस लेने में परेशानी।",
        "अत्यधिक चक्कर या सीने में तकलीफ होने पर आपातकालीन मदद लें।",
      ],
      preChecklist: CHECK_FALLBACK,
    },
  };
  return candidate;
}

export function findCatalogSaltMatch(m: Medicine): Medicine | null {
  return findCatalogSaltMatchHelper(m);
}

export function aiEvidence(result: AIBackendResult): string[] {
  return (result.entities || []).map(e => `${e.label}: ${e.text}`);
}
export function aiNote(result: AIBackendResult, fromCatalog: boolean): string {
  const parts = [
    result.nerModel ? `Model ${result.nerModel}` : "Trained NER model",
    fromCatalog ? "matched to your reference list" : "identified from public label data",
  ];
  if (result.rxnormId) parts.push(`RxNorm ${result.rxnormId} verified`);
  return parts.join(" · ");
}
export function aiScore(result: AIBackendResult): number {
  if (result.rxnormId) return result.mappingBasis === "salt-in-text" ? 0.91 : 0.8;
  if (result.mappingBasis === "brand-hint") return 0.62;
  return 0.5;
}
export { medicines as catalogMedicines };

// ===========================================================================
// Feature 1 — /candidates (damaged-strip probability + pill image classifier)
// ===========================================================================

export const candidateSchema = z.object({
  salt: z.string(),
  usName: z.string().optional(),
  probability: z.number(),
  basis: z.string(),
  matchedToken: z.string().nullable().optional(),
  matchedBrand: z.string().nullable().optional(),
  brandScore: z.number().optional(),
  saltScore: z.number().optional(),
  nerTagged: z.boolean().optional(),
  strengthDetected: z.string().nullable().optional(),
  visionMatched: z.boolean().optional(),
});

export const visionEvidenceSchema = z.object({
  label: z.string(),
  labelPretty: z.string().optional(),
  probability: z.number(),
  salt: z.string().nullable().optional(),
  strength: z.string().nullable().optional(),
});

export const candidatesResultSchema = z.object({
  available: z.boolean().optional(),
  found: z.boolean().default(false),
  query: z.string().optional(),
  candidates: z.array(candidateSchema).default([]),
  entities: z.array(z.object({ label: z.string(), text: z.string() }).passthrough()).optional(),
  nerModel: z.string().optional(),
  note: z.string().optional(),
  uncertainties: z.array(z.string()).optional(),
  webEvidence: z.array(z.object({ title: z.string().optional(), url: z.string(), snippet: z.string().optional() })).optional(),
  visionEvidence: z.array(visionEvidenceSchema).optional(),
  visionError: z.string().optional(),
  engine: z.string().optional(),
});
export type CandidatesResult = z.infer<typeof candidatesResultSchema>;
export type Candidate = z.infer<typeof candidateSchema>;
export type VisionEvidence = z.infer<typeof visionEvidenceSchema>;

export async function aiCandidates(
  ocrText: string,
  imageB64?: string,
  topK = 5,
  timeoutMs = 125000,
): Promise<CandidatesResult | null> {
  const text = ocrText.trim();
  if (!text) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch("/api/ai/candidates", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ocrText: text, imageB64, topK }),
      signal: controller.signal,
    });
    if (!res.ok) throw await identificationResponseError(res);
    let data: unknown;
    try { data = await res.json(); }
    catch { throw new IdentificationError("parse", "Ranked candidates returned unreadable data."); }
    const parsed = candidatesResultSchema.safeParse(data);
    if (!parsed.success) throw new IdentificationError("parse", "Ranked candidates could not be read.");
    if (parsed.data.available === false) throw new IdentificationError("unavailable", "Ranked candidates are unavailable.");
    return parsed.data;
  } catch (error) {
    if (error instanceof IdentificationError) throw error;
    throw new IdentificationError(controller.signal.aborted ? "timeout" : "unavailable", "Ranked candidate retrieval failed. Retry to see candidates.");
  } finally { clearTimeout(timer); }
}

// ===========================================================================
// Feature 2 — /recommend (patient-aware safety with DDInter + OpenFDA + rules)
// ===========================================================================

export const warningSchema = z.object({
  severity: z.enum(["CRITICAL", "WARN", "INFO"]),
  title: z.string(),
  detail: z.string(),
  action: z.string(),
  source: z.string(),
  kind: z.string().optional(),
  conflictingSalts: z.array(z.string()).optional(),
  allergen: z.string().optional(),
  matchedConditions: z.array(z.string()).optional(),
  database: z.string().optional(),
});
export type SafetyWarning = z.infer<typeof warningSchema>;

export const recommendResultSchema = z.object({
  available: z.boolean().optional(),
  ok: z.boolean().default(false),
  salt: z.string().optional(),
  brand: z.string().nullable().optional(),
  patient: z.object({
    age: z.number().nullable().optional(),
    conditions: z.array(z.string()),
    currentMeds: z.array(z.string()),
    allergens: z.array(z.string()),
    mappedSalts: z.array(z.string()),
  }).passthrough().optional(),
  warnings: z.array(warningSchema).default([]),
  shouldConsultDoctor: z.boolean().default(false),
  summary: z.string(),
  disclaimer: z.string().optional(),
});
export type RecommendResult = z.infer<typeof recommendResultSchema>;

export interface PatientProfile {
  age?: number;
  conditions?: string[];
  currentMeds?: string[];
  allergens?: string[];
}

export async function aiRecommend(
  salt: string,
  brand: string | undefined,
  patient: PatientProfile,
  timeoutMs = 18000,
): Promise<RecommendResult | null> {
  if (!salt) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch("/api/ai/recommend", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ salt, brand, patient }),
      signal: controller.signal,
    });
    if (!res.ok) return null;
    const parsed = recommendResultSchema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch { return null; } finally { clearTimeout(timer); }
}

// ===========================================================================
// Feature 3 — /chat (Meditron > Gemini > rule-based)
// ===========================================================================

export const chatResultSchema = z.object({
  available: z.boolean().optional(),
  ok: z.boolean().default(false),
  reply: z.string(),
  speakableText: z.string().optional(),
  language: z.enum(["en", "ta", "hi"]).default("en"),
  model: z.string().optional(),
  provider: z.string().optional(),
  providerStatus: z.string().optional(),
  isFallback: z.boolean().optional(),
  fallbackNotice: z.string().optional(),
  disclaimer: z.string().optional(),
  flagged: z.boolean().default(false),
  flagReason: z.string().nullable().optional(),
  timestamp: z.number().optional(),
});
export type ChatResult = z.infer<typeof chatResultSchema>;

export interface ChatMessage { message: string; reply: string }
export interface MedicineChatContext {
  salt?: string;
  brand?: string;
  strength?: string;
  form?: string;
  uses?: string;
  sideEffects?: string;
  warnings?: string;
  sources?: string;
}

export async function aiChat(
  message: string,
  language: "en" | "ta" | "hi",
  medicineContext?: MedicineChatContext,
  history: ChatMessage[] = [],
  timeoutMs = 25000,
): Promise<ChatResult | null> {
  const msg = (message || "").trim();
  if (!msg) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch("/api/ai/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: msg, language, medicineContext, history }),
      signal: controller.signal,
    });
    if (!res.ok) return null;
    const parsed = chatResultSchema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch { return null; } finally { clearTimeout(timer); }
}

// ===========================================================================
// /transcribe — Indic STT (AI4Bharat conformer) for Tamil/Hindi voice input
// ===========================================================================

export const transcribeResultSchema = z.object({
  available: z.boolean().optional(),
  ok: z.boolean().default(false),
  text: z.string().default(""),
  reason: z.string().optional(),
  language: z.enum(["en", "ta", "hi"]).default("ta"),
  model: z.string().nullable().optional(),
});
export type TranscribeResult = z.infer<typeof transcribeResultSchema>;

export async function aiTranscribe(
  audioB64: string,
  language: "en" | "ta" | "hi" = "ta",
  timeoutMs = 60000,
): Promise<TranscribeResult | null> {
  if (!audioB64) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch("/api/ai/transcribe", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audioB64, language }),
      signal: controller.signal,
    });
    if (!res.ok) return null;
    const parsed = transcribeResultSchema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch { return null; } finally { clearTimeout(timer); }
}

// ===========================================================================
// /pricing — PMBJP generic price lookup
// ===========================================================================

export const pricingResultSchema = z.object({
  available: z.boolean().optional(),
  ok: z.boolean().default(false),
  salt: z.string().optional(),
  best: z.object({
    salt: z.string(),
    brand: z.string(),
    strength: z.string(),
    mrp: z.string(),
    unit: z.string(),
    source: z.string(),
  }).nullable().optional(),
  alternatives: z.array(z.object({
    brand: z.string(),
    strength: z.string(),
    mrp: z.string(),
    unit: z.string(),
  })).default([]),
  source: z.string().optional(),
  reason: z.string().optional(),
});
export type PricingResult = z.infer<typeof pricingResultSchema>;

export async function aiPricing(
  salt: string,
  strength?: string,
  timeoutMs = 8000,
): Promise<PricingResult | null> {
  if (!salt) return null;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch("/api/ai/pricing", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ salt, strength }),
      signal: controller.signal,
    });
    if (!res.ok) return null;
    const parsed = pricingResultSchema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch { return null; } finally { clearTimeout(timer); }
}

// ===========================================================================
// /health — capability probe (drives the "AI model backend connected" badge)
// ===========================================================================

export const healthResultSchema = z.object({
  status: z.string(),
  ner: z.string().nullable().optional(),
  gemini: z.boolean().default(false),
  geminiModel: z.string().nullable().optional(),
  geminiStatus: z.string().optional(),
  geminiMessage: z.string().optional(),
  integrations: z.record(z.string(), z.record(z.string(), z.unknown())).default({}),
  integrationSummary: z.string().optional(),
  features: z.object({
    identify: z.boolean().default(false),
    candidates: z.boolean().default(false),
    recommend: z.boolean().default(false),
    chat: z.boolean().default(false),
    transcribe: z.boolean().default(false),
    pricing: z.boolean().default(false),
    chatLLM: z.string().default("none"),
  }),
});
export type HealthResult = z.infer<typeof healthResultSchema>;

export async function aiHealth(timeoutMs = 3000): Promise<HealthResult | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch("/api/ai/health", { signal: controller.signal });
    if (!res.ok) return null;
    const parsed = healthResultSchema.safeParse(await res.json());
    return parsed.success ? parsed.data : null;
  } catch { return null; } finally { clearTimeout(timer); }
}
