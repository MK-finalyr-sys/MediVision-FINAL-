"""Unverified same-source online discovery regression tests."""
import os
import unittest
from unittest.mock import patch

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""

from app import pipeline, retriever
from app.search_candidate import discover


SOURCE = {
    "title": "Asprole 75 Aspirin tablets",
    "snippet": "Asprole 75 tablet: aspirin 75 mg. Medicine tablet pack.",
    "url": "https://example.org/asprole-75",
}


class OnlineCandidateTests(unittest.TestCase):
    def test_same_source_identity_without_false_verification(self):
        candidate = discover("Asprole 75 Tablet", [SOURCE])
        self.assertIsNotNone(candidate)
        self.assertEqual(candidate["salt"].casefold(), "aspirin")
        self.assertEqual(candidate["brand"], "Asprole")
        self.assertEqual(candidate["strength"], None)

    def test_unrelated_source_is_not_a_match(self):
        bad = {**SOURCE, "title": "Unrelated Aspirin 75", "snippet": "Aspirin 75 mg tablets medicine."}
        self.assertIsNone(discover("Asprole 75 Tablet", [bad]))

    def test_conflicting_strength_cannot_pass(self):
        bad = {**SOURCE, "snippet": "Asprole 50 mg is an aspirin tablet medicine."}
        self.assertIsNone(discover("Asprole 75 mg", [bad]))

    def test_unfounded_unknown_does_not_become_drug(self):
        self.assertIsNone(discover("zxqvfoobar 100 mg", [SOURCE]))

    def test_pipeline_uses_unverified_online_discovery(self):
        fake_ner = {
            "entities": [], "salt": None, "brand": None,
            "strength": None, "mappingBasis": "none",
            "model": "test",
        }
        patches = [
            patch.object(pipeline, "predict_entities", return_value=fake_ner),
            patch("app.integrations.brand_salt_lookup.lookup_brand_details", return_value=None),
            patch.object(retriever, "web_search", return_value=[SOURCE]),
            patch.object(retriever, "rxnorm_verify", return_value=None),
            patch.object(retriever, "openfda_label", return_value=None),
            patch.object(retriever, "dailymed_url", return_value=None),
            patch.object(retriever, "gemini_compose", return_value=None),
            patch.object(retriever, "corroborate_product", return_value=[]),
        ]
        for obj in patches:
            obj.start()
            self.addCleanup(obj.stop)
        result = pipeline.identify("Asprole 75 Tablet")
        self.assertTrue(result["found"], result)
        self.assertEqual(result["salt"].casefold(), "aspirin")
        self.assertEqual(result["brand"], "Asprole")
        self.assertEqual(result["mappingBasis"], "online-search-candidate")
        self.assertEqual(result["verificationStatus"], "candidate-needs-confirmation")
        self.assertEqual(result["identityEvidence"], [])
        self.assertTrue(result["webEvidence"])
        self.assertNotEqual(result["verificationStatus"], "verified-online")


if __name__ == "__main__":
    unittest.main()
