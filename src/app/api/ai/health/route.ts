import { z } from "zod";

export const dynamic = "force-dynamic";
const BACKEND_URL = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/+$/, "");
const PROXY_TIMEOUT_MS = 3000;
const CACHE_TTL_MS = 30_000;
let _cache: { ts: number; data: unknown } | null = null;

export async function GET() {
  if (_cache && Date.now() - _cache.ts < CACHE_TTL_MS) {
    return Response.json(_cache.data);
  }
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), PROXY_TIMEOUT_MS);
  try {
    const res = await fetch(`${BACKEND_URL}/health`, { signal: controller.signal });
    if (!res.ok) throw new Error(`backend responded ${res.status}`);
    const data = await res.json();
    _cache = { ts: Date.now(), data };
    return Response.json(data);
  } catch {
    return Response.json({
      status: "offline",
      ner: null,
      gemini: false,
      integrations: {},
      features: { identify: false, candidates: false, recommend: false, chat: false, transcribe: false, pricing: false, chatLLM: "none" },
    });
  } finally { clearTimeout(timer); }
}
