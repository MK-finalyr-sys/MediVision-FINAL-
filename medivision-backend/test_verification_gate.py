"""Backend verification regressions. HTTP retrieval is mocked at the transport boundary."""
import os
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""

import json
import unittest
from contextlib import ExitStack
from unittest.mock import patch
from app import pipeline, retriever
from app.integrations import ddinter


class VerificationTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        for name, result in (
            ("web_search", []), ("rxnorm_verify", None), ("openfda_label", None),
            ("dailymed_url", None), ("gemini_compose", None),
        ):
            self.stack.enter_context(patch.object(retriever, name, return_value=result))
        self.http = self.stack.enter_context(patch.object(retriever.httpx, "get"))
        self.http.return_value.status_code = 503

    def record(self, **changes):
        record = {
            "product_ndc": "fixture-001",
            "brand_name": "A-TRIP-10",
            "dosage_form": "TABLET",
            "active_ingredients": [{"name": "AMITRIPTYLINE HYDROCHLORIDE", "strength": "10 mg/1"}],
        }
        record.update(changes)
        self.http.return_value.status_code = 200
        self.http.return_value.json.return_value = {"results": [record]}

    def test_a_local_candidate(self):
        result = pipeline.identify("A-TRIP-10")
        self.assertEqual(result["salt"], "Amitriptyline Hydrochloride")
        self.assertEqual(result["verificationStatus"], "candidate-needs-confirmation")
        self.assertEqual(result["identityEvidence"], [])

    def test_b_conflicting_package(self):
        result = pipeline.identify("A-TRIP-10 25 mg Injection")
        self.assertEqual(result["verificationStatus"], "conflicting-identification")
        self.assertTrue(result["requiresManualReview"])
        self.assertEqual(result["strength"], "25 mg")
        self.assertEqual(result["form"], "Injection")
        self.assertEqual({c["field"] for c in result["conflicts"]}, {"strength", "form"})
        self.assertEqual(result["proposedIdentity"]["strength"], "10 mg")
        self.assertIsNone(result["genericPricing"])

    def test_c_suffix_only(self):
        result = pipeline.identify("Hydrochloride Tablets 10 mg")
        self.assertFalse(result["found"])
        self.assertEqual(result["verificationStatus"], "none")

    def test_d_unknown(self):
        result = pipeline.identify("xyz999foobar completely unknown text 12345")
        self.assertFalse(result["found"])
        self.assertEqual(result["sources"], [])

    def test_e_metadata_and_ingredient_are_insufficient(self):
        with patch.object(retriever, "rxnorm_verify", return_value="123"):
            result = pipeline.identify("A-TRIP-10")
        self.assertTrue(any(s["sourceType"] == "manufacturer" for s in result["sources"]))
        self.assertEqual(result["verificationStatus"], "candidate-needs-confirmation")

    def test_f_fetched_response_with_provenance(self):
        self.record()
        result = pipeline.identify("A-TRIP-10")
        self.assertEqual(result["verificationStatus"], "verified-online")
        evidence = result["identityEvidence"][0]
        self.assertEqual(set(evidence["supportedFields"]), {"brand", "salt", "strength", "form"})
        self.assertIn("api.fda.gov/drug/ndc.json", evidence["url"])
        self.assertTrue(evidence["retrievedAt"])
        self.assertEqual(evidence["recordId"], "fixture-001")
        self.http.assert_called_once()

    def test_g_unrelated_incomplete_or_mismatched_response(self):
        for changes in (
            {"brand_name": "UNRELATED"}, {"dosage_form": "INJECTION"},
            {"active_ingredients": [{"name": "AMITRIPTYLINE HYDROCHLORIDE", "strength": "25 mg/1"}]},
            {"active_ingredients": [{"name": "TRAMADOL", "strength": "10 mg/1"}]},
            {"active_ingredients": []}, {"product_ndc": None},
        ):
            with self.subTest(changes=changes):
                self.record(**changes)
                self.assertEqual(pipeline.identify("A-TRIP-10")["verificationStatus"], "candidate-needs-confirmation")

    def test_h_existing_identities_and_ddinter(self):
        for text, salt, strength in (
            ("nitine Hydrochloride Tablets I.P. 10 mg A-TRIP-10", "Amitriptyline", "10 mg"),
            ("Dolo 650 Tablet", "Paracetamol", "650 mg"),
            ("P.ntopra 40", "Pantoprazole", "40 mg"),
        ):
            with self.subTest(text=text):
                result = pipeline.identify(text)
                self.assertTrue(result["found"])
                self.assertIn(salt, result["salt"])
                self.assertEqual(result["strength"], strength)
    def test_i_ddinter_only_when_database_installed(self):
        # SQLite is a separately provisioned licensed dataset, intentionally
        # not committed to GitHub. Do not fake or assume interactions in CI.
        if not ddinter.available():
            self.skipTest("DDInter database not provisioned in this runner")
        self.assertIsNotNone(ddinter.check_pair("aspirin", "warfarin"))


if __name__ == "__main__":
    unittest.main()
