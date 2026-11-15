import { z } from "zod";

export const dynamic = "force-dynamic";
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const PROXY_TIMEOUT_MS = 30000;

const bodySchema = z.object({
  message: z.string().min(1).max(2000),
  language: z.enum(["en", "ta", "hi"]).default("en"),
  medicineContext: z.record(z.string(), z.unknown()).optional(),
  history: z.array(z.object({ message: z.string(), reply: z.string() })).default([]),
});

export async function POST(request: Request) {
  let body: z.infer<typeof bodySchema>;
  try { body = bodySchema.parse(await request.json()); }
  catch { return Response.json({ ok: false, available: false, reply: "", reason: "invalid body" }, { status: 400 }); }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
  try {
    const res = await fetch(`${BACKEND_URL}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`backend responded ${res.status}`);
    const data = await res.json();
    return Response.json({ ...data, available: true });
  } catch {
    const lang = body.language;
    const fallback = lang === "ta"
      ? "என்னால் இப்போது பதிலளிக்க முடியவில்லை. மருந்து பற்றிய கேள்விகளுக்கு உங்கள் மருத்துவரிடம் கேட்கவும்."
      : lang === "hi"
      ? "अभी मैं उत्तर नहीं दे पा रहा। दवा से जुड़े प्रश्नों के लिए अपने डॉक्टर से पूछें."
      : "I cannot answer right now. Please ask your doctor about medicine-related questions.";
    return Response.json({
      ok: false, available: false, reply: fallback, speakableText: fallback,
      language: lang, model: "client-fallback",
      disclaimer: "Information from public medicine references. Not medical advice.",
      flagged: false, flagReason: null,
    });
  } finally { clearTimeout(timer); }
}
