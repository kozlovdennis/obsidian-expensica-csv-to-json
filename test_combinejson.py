import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from combinejson import combine_transactions, main


def transaction(identifier, kind, amount=100, date="2026-10-01", description="BANK TRANSFER"):
    return {
        "id": identifier,
        "date": date,
        "type": kind,
        "amount": amount,
        "description": description,
        "category": f"other_{kind}",
    }


class CombineTransactionsTests(unittest.TestCase):
    def test_three_accounts_and_both_savings_directions(self):
        purchase = transaction("purchase", "expense", 15, description="COFFEE")
        accounts = {
            "debit": [
                transaction("to-savings", "expense", 100),
                transaction("from-savings", "income", 50),
                transaction("to-credit", "expense", 200),
                purchase,
            ],
            "savings": [
                transaction("deposit", "income", 100),
                transaction("withdrawal", "expense", 50),
            ],
            "credit": [transaction("payment", "income", 200, description="PAYMENT THANK YOU")],
        }

        combined, count = combine_transactions(accounts, "12:00:00")

        self.assertEqual(count, 3)
        self.assertEqual(len(combined), 4)
        internal = [item for item in combined if item["type"] == "internal"]
        self.assertEqual(
            {(item["fromAccount"], item["toAccount"], item["amount"]) for item in internal},
            {("debit", "savings", 100), ("savings", "debit", 50), ("debit", "credit", 200)},
        )
        for item in internal:
            self.assertEqual(item["description"], f"TRANSFER TO {item['toAccount']}".upper())
            self.assertEqual(item["category"], "internal")
            self.assertEqual(item["time"], "12:00:00")
            self.assertNotIn("account", item)
        self.assertIn(dict(purchase, account="debit"), combined)
        self.assertNotIn("account", purchase)

    def test_two_accounts_cash_advance_and_source_metadata(self):
        source = transaction("advance", "expense", date="2026-10-02", description="CASH/ADVANCE")
        source["time"] = "09:30:00"
        combined, count = combine_transactions({
            "debit": [transaction("deposit", "income")], "credit": [source],
        }, "12:00:00")
        self.assertEqual(count, 1)
        self.assertEqual(combined[0]["fromAccount"], "credit")
        self.assertEqual(combined[0]["toAccount"], "debit")
        for key in ("id", "date", "time"):
            self.assertEqual(combined[0][key], source[key])

    def test_closest_date_wins_globally_and_each_entry_is_used_once(self):
        combined, count = combine_transactions({
            "debit": [transaction("out", "expense", date="2026-10-03")],
            "savings": [transaction("farther", "income")],
            "credit": [transaction("closest", "income", date="2026-10-03")],
        }, "12:00:00")
        self.assertEqual(count, 1)
        self.assertEqual(len(combined), 2)
        internal = next(item for item in combined if item["type"] == "internal")
        self.assertEqual(internal["toAccount"], "credit")
        self.assertEqual(combined[0]["id"], "farther")

    def test_nonmatching_entries_are_preserved(self):
        cases = [
            ("same account", "debit", transaction("in", "income")),
            ("same flow", "savings", transaction("in", "expense")),
            ("different amount", "savings", transaction("in", "income", 100.01)),
            ("outside date window", "savings", transaction("in", "income", date="2026-10-05")),
            ("ordinary income", "savings", transaction("in", "income", description="SALARY")),
            ("already internal", "savings", transaction("in", "internal")),
        ]
        for label, account, incoming in cases:
            with self.subTest(label=label):
                outgoing = transaction("out", "expense")
                accounts = {"debit": [outgoing], "savings": []}
                accounts[account].append(incoming)
                combined, count = combine_transactions(accounts, "12:00:00")
                self.assertEqual(count, 0)
                self.assertCountEqual(combined, [
                    dict(outgoing, account="debit"), dict(incoming, account=account),
                ])

    def test_three_day_boundary_and_decimal_amounts(self):
        combined, count = combine_transactions({
            "debit": [transaction("out", "expense", "100.10")],
            "savings": [transaction("in", "income", 100.1, date="2026-10-04")],
        }, "12:00:00")
        self.assertEqual(count, 1)
        self.assertEqual(combined[0]["amount"], 100.1)


class CommandLineTests(unittest.TestCase):
    def test_reads_three_files_and_writes_combined_payload(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "transactions.json"
            arguments = ["combinejson.py"]
            for alias, (name, items) in zip(("--account", "--acc", "-a"), {
                "debit": [transaction("out", "expense")],
                "savings": [transaction("in", "income")],
                "credit": [],
            }.items()):
                path = Path(directory) / f"{name}.json"
                path.write_text(json.dumps({"transactions": items}), encoding="utf-8")
                arguments.extend([alias, name, str(path)])
            with patch("sys.argv", arguments), patch("combinejson.default_output_path", return_value=output):
                with contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(main(), 0)
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["transactions"]), 1)
            self.assertEqual(payload["transactions"][0]["toAccount"], "savings")

    def test_rejects_missing_or_duplicate_accounts_before_reading_files(self):
        for arguments in (
            [],
            ["--account", "debit", "missing.json"],
            ["--account", "debit", "a.json", "--account", "debit", "b.json"],
        ):
            with self.subTest(arguments=arguments), patch("sys.argv", ["combinejson.py", *arguments]):
                with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                    main()
                self.assertEqual(error.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
