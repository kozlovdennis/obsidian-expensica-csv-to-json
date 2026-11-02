import contextlib
import io
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from cleanup import clean_transaction, main
from combinejson import combine_transactions
from convert import row_to_transaction


class ConversionAndCleanupTests(unittest.TestCase):
    def test_conversion_preserves_description_and_defers_category_rules(self):
        raw = "  Point of Sale - Interac RETAIL PURCHASE 123456789 CADENCE COFFEE  "
        transaction = row_to_transaction(["2026-10-01", raw, "15.25", ""], datetime(2026, 11, 1))
        self.assertEqual(transaction["description"], raw)
        self.assertEqual(transaction["category"], "other_expense")
        self.assertEqual(transaction["amount"], 15.25)
        cleaned = clean_transaction(transaction)
        self.assertEqual(cleaned["description"], "CADENCE COFFEE")
        self.assertEqual(cleaned["category"], "food")
        for key in ("id", "date", "time", "amount", "type"):
            self.assertEqual(cleaned[key], transaction[key])
        self.assertEqual(transaction["description"], raw)

    def test_raw_conversion_merges_before_cleanup(self):
        now = datetime(2026, 11, 1)
        outgoing = row_to_transaction([
            "2026-10-01", "Internet Banking INTERNET TRANSFER 123456 To card ****2028", "100", "",
        ], now)
        incoming = row_to_transaction([
            "2026-10-06", "Payment thank you/PAIEMEN T MERCI", "", "100",
        ], now)
        combined, count = combine_transactions({"debit": [outgoing], "credit": [incoming]}, "12:00:00")
        self.assertEqual(count, 1)
        self.assertEqual(combined[0]["type"], "internal")
        self.assertEqual(clean_transaction(combined[0]), combined[0])

    def test_cleanup_retains_transfer_fallback(self):
        transaction = row_to_transaction([
            "2026-10-01", "Internet Banking INTERNET TRANSFER 123456", "100", "",
        ], datetime(2026, 11, 1))
        self.assertEqual(clean_transaction(transaction)["description"], "OUTGOING BANK TRANSFER #123456")


class CleanupCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "transactions.json"
        self.internal = {
            "id": "transfer-1", "date": "2026-10-01", "type": "internal", "amount": 100,
            "description": "TRANSFER TO SAVING", "category": "internal",
            "fromAccount": "debit", "toAccount": "saving",
        }
        self.payload = {
            "metadata": {"keep": True},
            "transactions": [
                {
                    "id": "purchase-1", "date": "2026-10-01", "type": "expense", "amount": 15,
                    "description": "Point of Sale - Interac RETAIL PURCHASE 123456 CADENCE COFFEE",
                    "category": "other_expense", "account": "debit", "notes": "keep me",
                },
                self.internal,
            ],
        }
        self.path.write_text(json.dumps(self.payload), encoding="utf-8")

    def run_cleanup(self, answers):
        with patch("sys.argv", ["cleanup.py", str(self.path)]), patch("builtins.input", side_effect=answers):
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(), 0)

    def test_yes_updates_file_and_preserves_metadata_and_internal_transactions(self):
        self.run_cleanup(["y"])
        actual = json.loads(self.path.read_text(encoding="utf-8"))
        expected = json.loads(json.dumps(self.payload))
        expected["transactions"][0].update(description="CADENCE COFFEE", category="food")
        self.assertEqual(actual, expected)

    def test_no_keeps_file_byte_for_byte(self):
        before = self.path.read_bytes()
        self.run_cleanup(["n"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_answer_reprompts_without_writing(self):
        before = self.path.read_bytes()
        self.run_cleanup(["maybe", "n"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_eof_cancels_without_writing(self):
        before = self.path.read_bytes()
        self.run_cleanup(EOFError)
        self.assertEqual(self.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
