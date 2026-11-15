import { z } from "zod";

export const dynamic = "force-dynamic";
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const PROXY_TIMEOUT_MS = 8000;

const bodySchema = z.object({
  salt: z.string().min(1),
  strength: z.string().optional(),
});

export async function POST(request: Request) {
  let body: z.infer<typeof bodySchema>;
  try { body = bodySchema.parse(await request.json()); }
  catch { return Response.json({ ok: false, reason: "invalid body" }, { status: 400 }); }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
  try {
    const res = await fetch(`${BACKEND_URL}/pricing`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!res.ok) throw new Error(`backend responded ${res.status}`);
    const data = await res.json();
    return Response.json({ ...data, available: true });
  } catch {
    return Response.json({ ok: false, available: false, reason: "pricing catalog unavailable" });
  } finally { clearTimeout(timer); }
}
