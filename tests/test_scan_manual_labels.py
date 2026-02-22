import io
import os
import tempfile
import importlib
import unittest
from unittest.mock import patch


class ScanManualLabelsTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["BONSCANNER_DB_PATH"] = os.path.join(self.tmpdir.name, "test.db")

        # Reload modules to pick up the new DB path.
        import database
        import app as app_module

        importlib.reload(database)
        importlib.reload(app_module)
        self.app_module = app_module
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_manual_labels_skip_auto_categorization(self):
        sample_result = {
            "store_name": "obi",
            "date": "2024-02-05",
            "total": "12.50",
            "items": [],
            "raw_text": "OBI receipt",
        }

        with patch("server.routes.receipts.ocr_image_file", return_value="raw"), \
            patch("server.routes.receipts.extract_receipt_data", return_value=sample_result), \
            patch("server.routes.receipts.apply_auto_categorization") as auto_mock:
            auto_mock.return_value = ["Haushalt"]

            data = {
                "image": (io.BytesIO(b"img"), "receipt.png"),
                "labels": "Elektronik",
            }
            resp = self.client.post(
                "/scan",
                data=data,
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn("id", payload)
        self.assertEqual(payload.get("labels"), ["Elektronik"])
        auto_mock.assert_not_called()

    def test_auto_categorization_runs_without_labels(self):
        sample_result = {
            "store_name": "obi",
            "date": "2024-02-05",
            "total": "12.50",
            "items": [],
            "raw_text": "OBI receipt",
        }

        with patch("server.routes.receipts.ocr_image_file", return_value="raw"), \
            patch("server.routes.receipts.extract_receipt_data", return_value=sample_result), \
            patch("server.routes.receipts.apply_auto_categorization") as auto_mock:
            auto_mock.return_value = ["Haushalt"]

            data = {
                "image": (io.BytesIO(b"img"), "receipt.png"),
            }
            resp = self.client.post(
                "/scan",
                data=data,
                content_type="multipart/form-data",
            )

        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertIn("id", payload)
        self.assertEqual(payload.get("labels"), ["Haushalt"])
        self.assertEqual(auto_mock.call_count, 1)


if __name__ == "__main__":
    unittest.main()
