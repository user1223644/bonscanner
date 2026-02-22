import os
import tempfile
import importlib
import unittest


class PatchLabelsTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        os.environ["BONSCANNER_DB_PATH"] = os.path.join(self.tmpdir.name, "test.db")

        import database
        import app as app_module

        importlib.reload(database)
        importlib.reload(app_module)
        self.database = database
        self.client = app_module.app.test_client()

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_patch_labels_allows_empty(self):
        receipt_id = self.database.save_receipt(
            {
                "store_name": "Test",
                "date": "2024-01-01",
                "total": "5.00",
                "items": [],
                "raw_text": "",
            },
            labels=["Auto"],
        )

        resp = self.client.patch(
            f"/receipts/{receipt_id}/labels",
            json={"labels": []},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertEqual(payload.get("labels"), [])


if __name__ == "__main__":
    unittest.main()
