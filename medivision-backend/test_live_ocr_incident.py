"""Live-incident regression: never identify Prednisolone from Asprole OCR noise.

Uses no external search or paid APIs. Test the general safety invariants
through the actual current pipeline, not the presentation 40-drug UI.
"""
import unittest
from unittest.mock import patch

from app import pipeline, retriever
from app.identity_guard import ingredient_roots, credible_brand_in_ocr


class OCRSafetyIncidentTests(unittest.TestCase):
    def setUp(self):
        patches = [
            patch.object(retriever, "web_search", return_value=[]),
            patch.object(retriever, "rxnorm_verify", return_value=None),
            patch.object(retriever, "openfda_label", return_value=None),
            patch.object(retriever, "dailymed_url", return_value=None),
            patch.object(retriever, "gemini_compose", return_value=None),
            patch.object(retriever, "corroborate_product", return_value=[]),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_weak_ocr_does_not_predict_prednisolone(self):
        out = pipeline.identify("5mg Asp in\ncorey")
        self.assertNotEqual(ingredient_roots(out.get("salt")), {"prednisolone"}, out)
        self.assertNotEqual(out.get("verificationStatus"), "verified-online")
        self.assertFalse(out["found"], out)

    def test_clear_label_identifies_visible_aspirin(self):
        out = pipeline.identify("Cadray Asprole 75 Aspirin Tablets IP 75 mg")
        self.assertTrue(out["found"], out)
        self.assertEqual(ingredient_roots(out.get("salt")), {"aspirin"}, out)
        self.assertEqual(out["strength"], "75 mg")
        self.assertNotEqual(out.get("verificationStatus"), "verified-online")

    def test_unknown_medicine_is_not_guessed(self):
        out = pipeline.identify("corey 5mg asp in")
        self.assertNotEqual(ingredient_roots(out.get("salt")), {"prednisolone"}, out)

    def test_brand_fragment_requires_coherent_evidence(self):
        self.assertFalse(credible_brand_in_ocr("corey", "5mg Asp in corey", False))
        self.assertFalse(credible_brand_in_ocr("Asp in", "5mg Asp in corey", False))
        self.assertTrue(credible_brand_in_ocr("Dolo 650", "Dolo 650 Tablets", False))
        self.assertTrue(credible_brand_in_ocr("A-TRIP-10", "A-TRIP-10 Tablets", False))


if __name__ == "__main__":
    unittest.main()
