import { z } from "zod";

export const dynamic = "force-dynamic";
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const PROXY_TIMEOUT_MS = 60000;

const bodySchema = z.object({
  audioB64: z.string().min(10),
  language: z.enum(["en", "ta", "hi"]).default("ta"),
});

export async function POST(request: Request) {
  let body: z.infer<typeof bodySchema>;
  try { body = bodySchema.parse(await request.json()); }
  catch { return Response.json({ ok: false, text: "", reason: "invalid body" }, { status: 400 }); }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
  try {
    const res = await fetch(`${BACKEND_URL}/transcribe`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`backend responded ${res.status}`);
    const data = await res.json();
    return Response.json({ ...data, available: true });
  } catch {
    return Response.json({
      ok: false, available: false, text: "",
      reason: "backend or Indic STT unavailable; use Web Speech API instead",
    });
  } finally { clearTimeout(timer); }
}
