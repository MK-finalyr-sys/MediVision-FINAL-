import rawMedicines from "@/data/medicines.json";
import rawTips from "@/data/tips.json";
import { medicineSchema, tipSchema } from "./contracts";
import type { Medicine } from "./contracts";
import { keys, loadStored, persist } from "./storage";

export const medicines = medicineSchema.array().length(40).parse(rawMedicines);
export const tips = tipSchema.array().parse(rawTips);

// ----- AI-identified medicine registry (additive — not part of the 40-list) -----
// AI-identified medicines are stored under a separate localStorage key so the
// 40-medicine reference list stays byte-for-byte as the project shipped it.
// This module owns the registry so the engine, scan view, and My Meds view
// can all read from one place.

const aiSchema = medicineSchema.array();
let _aiCache: Medicine[] | null = null;

function loadAI(): Medicine[] {
  if (_aiCache !== null) return _aiCache;
  _aiCache = loadStored(keys.aiMeds, aiSchema, []);
  return _aiCache;
}

function saveAI(list: Medicine[]) {
  aiSchema.parse(list);
  _aiCache = list;
  persist(keys.aiMeds, aiSchema, list);
}

/** Register an AI-identified medicine (dedup by id). Returns the merged list. */
export function registerAIMedicines(items: Medicine[]): Medicine[] {
  if (!items.length) return loadAI();
  const existing = loadAI();
  const seen = new Set(existing.map(m => m.id));
  const merged = [...existing];
  for (const m of items) {
    if (!seen.has(m.id)) {
      merged.push(m);
      seen.add(m.id);
    }
  }
  saveAI(merged);
  return merged;
}

/** Drop the AI registry (used by the Privacy & data reset flow). */
export function clearAIMedicines() {
  saveAI([]);
}

/** All AI-identified medicines seen so far this session. */
export function aiMedicines(): Medicine[] {
  return loadAI();
}

/** Hydrate the AI registry from localStorage on app boot — call once in the root component. */
export function hydrateAIMedicines(): void {
  loadAI();
}

// ----- catalog-salt match helper (used by scan-view + ai-backend) -----
// If an AI-identified medicine's salt is already covered by the curated
// 40-medicine reference list, prefer THAT entry (real translations, existing
// behaviour) instead of the AI-generated card.
export function findCatalogSaltMatchHelper(m: Medicine): Medicine | null {
  const aiSalt = (m.activeIngredient || "").toLowerCase().trim();
  if (!aiSalt) return null;
  // exact salt match
  for (const c of medicines) {
    if ((c.activeIngredient || "").toLowerCase().trim() === aiSalt) return c;
  }
  // second-salt match (for combination medicines)
  for (const c of medicines) {
    if (c.activeIngredient2 && c.activeIngredient2.toLowerCase().trim() === aiSalt) return c;
  }
  return null;
}
