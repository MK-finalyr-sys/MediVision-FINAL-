# Task 2 checkpoint — 2026-11-15

Status: frontend repairs implemented; real-image acceptance NOT met.

Preserved the existing Task 1 backend verification gate without further backend edits.
Resumed the existing Task 2 diff: explicit response schemas, structured errors, asynchronous
scan completion, real backend candidates, conflict display, explicit confirmation, and
persistence/navigation of confirmed scanned medicines. Optional presentation metadata
cannot erase a valid identity; malformed identity/evidence fields remain errors.

Validation on the final source:
- TypeScript, ESLint and production build passed. A restricted rebuild initially hit
  EPERM in generated .next output; the permitted rebuild passed.
- Vitest: 62 passed, including actual Tesseract photograph processing. Those OCR unit
  assertions measure processing/safe local matching, not successful backend identification.
- Backend: 8 mocked verification-gate tests and 8 existing TestClient regressions passed.
  Existing regressions used live external retrieval with Gemini credentials disabled.
- Production browser (Edge): 7 passed, 2 failed. Live A-TRIP OCR fixture reached the real
  proxy/backend, opened the unconfirmed popup, blocked saving/chat, and enabled profile,
  cabinet and assistant navigation after explicit confirmation. Conflict/no-match/timeout/
  parsing/unavailable/disagreement cases use mocked HTTP responses. The initial run had
  ambiguous alert selectors; these were corrected and all seven passed on rerun.
- Genuine Pan-40 and Dolo-650 photo tests used actual browser OCR and backend requests.
  Both FAILED identity assertions and remain failing tests, not skipped or weakened.
  Pan-40 OCR led to Itraconazole; Dolo-650 OCR led to Ofloxacin + Ornidazole.
  Both backend responses were candidate-needs-confirmation, not verified-online.
  This is an OCR-to-matcher accuracy blocker; no matcher rewrite was attempted.
- Original A-TRIP photograph unavailable: its passing test is explicitly an OCR fixture.
  No physical phone/camera acceptance or Gemini response quality test was performed.

Actual A-TRIP response subset:
```json
{"brand":"A-TRIP-10","salt":"Amitriptyline Hydrochloride","strength":"10 mg","form":"Tablet","verificationStatus":"candidate-needs-confirmation","identityEvidence":[],"conflicts":[],"requiresManualReview":false}
```

Evidence is local and ignored: test-results/playwright.json, scan-unconfirmed.png,
actual-identification.json, pan-40-identification.json, dolo-650-identification.json,
and browser-artifacts/. Photo provenance is tests/fixtures/provenance.json;
copyrighted downloaded photographs are excluded from Git. Re-running image tests
requires these local photographs plus the existing OCR/model/data assets.

Changed frontend files: src/lib/{ai-backend,contracts,catalog}.ts;
src/components/{scan-view,medicine-card,medivision,care-views}.tsx;
src/app/api/ai/{identify,candidates}/route.ts. Tests: tests/scan-identification.test.ts,
tests/browser/scan.spec.ts and captured tests/fixtures/identify-atrip.json.

The checkpoint preserves in-progress work and documented failures. It is not a release
or a declaration that Smart Scan meets real-image acceptance. Unrelated existing
untracked documentation/configuration/assets remain in the working tree.
