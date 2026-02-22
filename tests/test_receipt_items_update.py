import os
import tempfile
import importlib
import unittest


class ReceiptItemUpdateTest(unittest.TestCase):
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

    def test_update_item_name_and_price(self):
        receipt_id = self.database.save_receipt(
            {
                "store_name": "Test",
                "date": "2024-01-01",
                "total": "10.00",
                "items": [
                    {"name": "Item A", "price": "10.00"},
                ],
                "raw_text": "",
            },
            labels=[],
        )

        items = self.database.get_receipt_items(receipt_id)
        self.assertEqual(len(items), 1)
        item_id = items[0]["id"]

        resp = self.client.patch(
            f"/receipts/{receipt_id}/items/{item_id}",
            json={"name": "Item B", "line_total": "12.50"},
        )
        self.assertEqual(resp.status_code, 200)
        payload = resp.get_json()
        self.assertTrue(payload.get("success"))

        updated_items = payload.get("items")
        self.assertEqual(updated_items[0]["name"], "Item B")
        self.assertAlmostEqual(updated_items[0]["line_total"], 12.5)


if __name__ == "__main__":
    unittest.main()
