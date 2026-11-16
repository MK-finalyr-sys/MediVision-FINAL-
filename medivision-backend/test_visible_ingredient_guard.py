"""Regressions for generic ingredient evidence vs noisy CRF guesses.

Run from medivision-backend: python -m unittest test_visible_ingredient_guard -v
These test matching logic, NOT live deployed accuracy or real camera/OCR images.
"""
import os
import unittest
from unittest.mock import patch

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""

from app import pipeline, retriever
from app.identity_guard import ingredient_roots, visible_ingredients


class VisibleIngredientGuardTests(unittest.TestCase):
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

    def test_visible_aspirin_is_not_prednisolone(self):
        result = pipeline.identify(
            "Cadray Asprole 75 Aspirin Tablets IP 75mg"
        )
        self.assertTrue(result["found"], result)
        self.assertEqual(ingredient_roots(result["salt"]), {"aspirin"})
        self.assertEqual(result["strength"], "75 mg")
        self.assertEqual(result["form"], "Tablet")
        self.assertNotEqual(result["verificationStatus"], "verified-online")
        self.assertNotIn("prednisolone", str(result).casefold())

    def test_wrong_model_guess_cannot_override_visible_aspirin(self):
        with patch.object(
            pipeline,
            "predict_entities",
            return_value={
                "entities": [{"label": "BRAND", "text": "corey"}],
                "salt": "Prednisolone", "brand": "corey",
                "strength": "5 mg", "mappingBasis": "salt-in-text",
                "model": "test-model",
            },
        ):
            result = pipeline.identify("Asprole 75 Aspirin Tablets IP 75 mg")
        self.assertEqual(ingredient_roots(result["salt"]), {"aspirin"})
        self.assertEqual(result["strength"], "75 mg")
        self.assertNotEqual(result["brand"], "corey")
        self.assertNotEqual(result["verificationStatus"], "verified-online")

    def test_multiple_visible_ingredients_require_review(self):
        result = pipeline.identify("Aspirin and Metformin Tablets")
        self.assertFalse(result["found"])
        self.assertEqual(result["note"], "MULTIPLE_INGREDIENTS_REQUIRE_REVIEW")

    def test_no_suffix_identity(self):
        result = pipeline.identify("Hydrochloride Tablets 10 mg")
        self.assertFalse(result["found"])

    def test_exact_ingredient_match_is_word_bounded(self):
        self.assertIn("Aspirin", visible_ingredients("Aspirin Tablets IP 75 mg"))
        self.assertNotIn("Aspirin", visible_ingredients("aspirinq Tablets"))

    def test_multiple_generic_names_match_composition_roots(self):
        self.assertEqual(
            ingredient_roots("Metformin Hydrochloride + Glimepiride"),
            {"metformin", "glimepiride"},
        )


if __name__ == "__main__":
    unittest.main()
