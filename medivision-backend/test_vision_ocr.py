"""No-network tests for optional photo transcription and /identify integration."""
import base64
import json
import os
import unittest
from unittest.mock import patch

os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["GEMINI_API_KEY"] = ""
os.environ["GOOGLE_API_KEY"] = ""

from app import vision_ocr
from app.main import IdentifyIn, identify


class VisionRescueTests(unittest.TestCase):
    def test_disabled_never_calls_google(self):
        with patch.dict(os.environ, {"MV_ENABLE_GEMINI_VISION": "0"}), patch.object(vision_ocr.httpx, "post") as req:
            self.assertIsNone(vision_ocr.read_printed_text("data:image/jpeg;base64," + base64.b64encode(b"image").decode()))
            req.assert_not_called()

    def test_invalid_image_rejected(self):
        with patch.dict(os.environ, {"MV_ENABLE_GEMINI_VISION": "1"}), patch("app.retriever.get_gemini_key", return_value="test-secret-key-123456"):
            self.assertIsNone(vision_ocr.read_printed_text("not an image"))

    def test_mocked_photo_transcription(self):
        photo = "data:image/jpeg;base64," + base64.b64encode(b"test image bytes").decode()
        response = {
            "candidates": [{
                "content": {
                    "parts": [{"text": json.dumps({"printedText": "Aspirin Tablets IP 75 mg"})}]
                }
            }]
        }
        with (
            patch.dict(os.environ, {"MV_ENABLE_GEMINI_VISION": "1"}),
            patch("app.retriever.get_gemini_key", return_value="test-secret-key-123456"),
            patch.object(vision_ocr.httpx, "post") as request,
        ):
            request.return_value.status_code = 200
            request.return_value.json.return_value = response
            self.assertEqual(vision_ocr.read_printed_text(photo), "Aspirin Tablets IP 75 mg")
            request.assert_called_once()

    def test_primary_identification_prefers_visual_text_when_available(self):
        with (
            patch.object(vision_ocr, "read_printed_text", return_value="Aspirin Tablets IP 75 mg"),
            patch("app.main.pipeline.identify", return_value={
                "found": True, "salt": "Aspirin", "strength": "75 mg",
                "verificationStatus": "candidate-needs-confirmation",
            }) as ident,
        ):
            result = identify(IdentifyIn(
                ocrText="5mg Asp in", imageB64="data:image/jpeg;base64,YWJj"
            ))
        ident.assert_called_once_with("Aspirin Tablets IP 75 mg")
        self.assertTrue(result["visionAssisted"])
        self.assertEqual(result["originalOcrText"], "5mg Asp in")
        self.assertEqual(result["verificationStatus"], "candidate-needs-confirmation")

    def test_text_path_still_functions_without_image(self):
        with (
            patch.object(vision_ocr, "read_printed_text", return_value=None),
            patch("app.main.pipeline.identify", return_value={
                "found": False, "verificationStatus": "none",
            }) as ident,
        ):
            result = identify(IdentifyIn(ocrText="unknown"))
        ident.assert_called_once_with("unknown")
        self.assertFalse(result["visionAssisted"])


if __name__ == "__main__":
    unittest.main()
