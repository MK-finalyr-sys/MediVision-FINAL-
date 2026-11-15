import { z } from "zod";

export const dynamic = "force-dynamic";
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const PROXY_TIMEOUT_MS = 20000;   // DDInter + OpenFDA can take a few seconds

const bodySchema = z.object({
  salt: z.string().min(1),
  brand: z.string().optional(),
  patient: z.object({
    age: z.number().int().min(0).max(130).optional(),
    conditions: z.array(z.string()).default([]),
    currentMeds: z.array(z.string()).default([]),
    allergens: z.array(z.string()).default([]),
  }).default({ conditions: [], currentMeds: [], allergens: [] }),
});

export async function POST(request: Request) {
  let body: z.infer<typeof bodySchema>;
  try { body = bodySchema.parse(await request.json()); }
  catch { return Response.json({ ok: false, available: false, reason: "invalid body" }, { status: 400 }); }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
  try {
    const res = await fetch(`${BACKEND_URL}/recommend`, {
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
      ok: false, available: false, warnings: [], shouldConsultDoctor: false,
      summary: "Patient-aware analysis is unavailable right now. The medicine card is still shown — follow the label and ask your pharmacist.",
      disclaimer: "Information from public medicine references. Not medical advice.",
    });
  } finally { clearTimeout(timer); }
}
