import { afterEach, describe, expect, it, vi } from "vitest";
import actual from "./fixtures/identify-atrip.json";
import { aiIdentify, aiCandidates, backendToMedicine, canAutoOpenIdentification, parseIdentification } from "../src/lib/ai-backend";
import { needsIdentityConfirmation } from "../src/lib/contracts";

afterEach(() => vi.unstubAllGlobals());
describe("scan identification contract", () => {
  it("requires an explicit match result and preserves safety evidence strictly", () => {
    expect(() => parseIdentification({ salt: "Amitriptyline" })).toThrow();
    expect(() => parseIdentification({ ...actual, conflicts: "invalid" })).toThrow();
    const result = parseIdentification(actual);
    expect(backendToMedicine(result)?.identification?.identityEvidence).toEqual(result.identityEvidence);
  });
  it("requires agreement before a high ranking can open the proposal", () => {
    const result = parseIdentification(actual);
    expect(canAutoOpenIdentification(result, { found: true, candidates: [{ salt: result.salt!, strengthDetected: "10", probability: 0.9, basis: "indian-brand-index" }] })).toBe(true);
    expect(canAutoOpenIdentification(result, { found: true, candidates: [{ salt: result.salt!, strengthDetected: "25 mg", probability: 0.99, basis: "indian-brand-index" }] })).toBe(false);
  });
  it("distinguishes candidate network failures from malformed JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));
    await expect(aiCandidates("A-TRIP-10")).rejects.toMatchObject({ code: "unavailable" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not json")));
    await expect(aiCandidates("A-TRIP-10")).rejects.toMatchObject({ code: "parse" });
  });
  it("parses the captured backend card including model and caveats", () => {
    const result = parseIdentification(actual);
    expect(result.card?.model).toBeTypeOf("string");
    expect(result.card?.caveats).toBeInstanceOf(Array);
    expect(result.salt).toBe("Amitriptyline Hydrochloride");
  });
  it("preserves identity and reports malformed optional card metadata", () => {
    const result = parseIdentification({ ...actual, card: { model: 123 } });
    expect(result.salt).toBe(actual.salt);
    expect(result.metadataWarnings).toHaveLength(1);
  });
  it("maps the received formulation without substituting a catalog medicine", () => {
    const result = parseIdentification({ ...actual, strength: "25 mg", form: "Injection", requiresManualReview: true, verificationStatus: "conflicting-identification", conflicts: [{ field: "strength", observed: "25 mg", proposed: "10 mg" }] });
    const medicine = backendToMedicine(result)!;
    expect(medicine.name).toBe("A-TRIP-10");
    expect(medicine.strength).toBe("25 mg");
    expect(medicine.form).toBe("Injection");
    expect(medicine.identification?.conflicts).toHaveLength(1);
    expect(needsIdentityConfirmation(medicine)).toBe(true);
    expect(canAutoOpenIdentification(result, null)).toBe(false);
  });
  it("parses the backend no-match null fields", () => {
    const result = parseIdentification({ found: false, salt: null, brand: null, strength: null, form: null, verificationStatus: "none" });
    expect(backendToMedicine(result)).toBeNull();
  });
  it("surfaces invalid core API data", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(Response.json({ found: true, salt: 123 })));
    await expect(aiIdentify("A-TRIP-10")).rejects.toMatchObject({ code: "parse" });
  });
  it("surfaces browser timeout", async () => {
    vi.stubGlobal("fetch", vi.fn((_url, options) => new Promise((_resolve, reject) => {
      options.signal.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    })));
    await expect(aiIdentify("A-TRIP-10", 5)).rejects.toMatchObject({ code: "timeout" });
  });
});
