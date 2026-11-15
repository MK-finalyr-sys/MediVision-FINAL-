import { z } from "zod";

export const dynamic = "force-dynamic";
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const PROXY_TIMEOUT_MS = 120000;

const bodySchema = z.object({
  ocrText: z.string().optional(),
  text: z.string().optional(),
  imageB64: z.string().optional(),
  topK: z.number().int().min(1).max(10).optional(),
});

export async function POST(request: Request) {
  let body: z.infer<typeof bodySchema>;
  try { body = bodySchema.parse(await request.json()); }
  catch { return Response.json({ available: false, found: false, reason: "invalid body" }, { status: 400 }); }
  const ocrText = (body.ocrText ?? body.text ?? "").trim();
  if (!ocrText) return Response.json({ available: false, found: false, reason: "no text" }, { status: 400 });
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
  try {
    const res = await fetch(`${BACKEND_URL}/candidates`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ocrText, imageB64: body.imageB64, topK: body.topK ?? 5 }),
      signal: controller.signal,
    });
    if (!res.ok) {
      return Response.json({ available: false, found: false, error: { code: "api" } }, { status: 502 });
    }
    let data: unknown;
    try { data = await res.json(); }
    catch {
      return Response.json({ available: false, found: false, error: { code: "parse" } }, { status: 502 });
    }
    if (!data || typeof data !== "object" || Array.isArray(data)) {
      return Response.json({ available: false, found: false, error: { code: "parse" } }, { status: 502 });
    }
    return Response.json({ ...data, available: true, engine: "backend-ner" });
  } catch {
    const timeout = controller.signal.aborted;
    return Response.json({ available: false, found: false, error: { code: timeout ? "timeout" : "unavailable" } }, { status: timeout ? 504 : 503 });
  } finally { clearTimeout(timer); }
}
