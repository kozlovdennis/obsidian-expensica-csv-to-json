import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from itertools import permutations
from decimal import Decimal
from unittest.mock import patch

from combinejson import bank_reference, combine_transactions, load_transactions, main, report_unmerged_transfers


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
    def test_bank_reference_extraction_excludes_card_and_account_numbers(self):
        for description, expected in (
            ("Internet Banking INTERNET TRANSFER 000000138567", "138567"),
            ("OUTGOING BANK TRANSFER #138567", "138567"),
            ("BANK TRANSFER REFERENCE #000000138567", "138567"),
            ("TO CARD 45000000138567", None),
            ("FROM ACCOUNT 03090/138567", None),
        ):
            with self.subTest(description=description):
                self.assertEqual(bank_reference(transaction("id", "expense", description=description)), expected)

    def test_identical_reference_precedes_an_unreferenced_candidate(self):
        audit, diagnostics = [], []
        combined, count = combine_transactions({
            "debit": [transaction("out", "expense", description="INTERNET TRANSFER 000000138567")],
            "saving": [transaction("bank-in", "income", description="BANK TRANSFER #138567")],
            "credit": [transaction("card-in", "income", description="Payment thank you")],
        }, "12:00:00", audit=audit, diagnostics=diagnostics)
        self.assertEqual(count, 1)
        self.assertEqual(len(combined), 2)
        self.assertEqual(audit[0]["incoming"]["id"], "bank-in")
        self.assertEqual(audit[0]["method"], "bank_reference")
        self.assertEqual(audit[0]["bankReference"], "138567")
        self.assertEqual(diagnostics[0]["transaction"]["id"], "card-in")
        self.assertEqual(diagnostics[0]["reason"], "missing_counterpart")

    def test_conflicting_references_are_not_matched(self):
        combined, count = combine_transactions({
            "debit": [transaction("out", "expense", description="BANK TRANSFER #138567")],
            "saving": [transaction("in", "income", description="BANK TRANSFER #138568")],
        }, "12:00:00")
        self.assertEqual(count, 0)
        self.assertEqual(len(combined), 2)

    def test_identical_references_do_not_override_compatibility(self):
        prefix = "INTERNET TRANSFER 000000138567 "
        for incoming in (
            transaction("in", "income", 101, description=prefix),
            transaction("in", "expense", description=prefix),
            transaction("in", "income", date="2026-10-07", description=prefix),
            transaction("in", "income", description=prefix + "Payment thank you"),
        ):
            with self.subTest(incoming=incoming):
                combined, count = combine_transactions({
                    "debit": [transaction("out", "expense", description=prefix + "To account ****096")],
                    "other": [incoming],
                }, "12:00:00")
                self.assertEqual(count, 0)
                self.assertEqual(len(combined), 2)

    def test_inferred_account_types_restrict_generic_descriptions(self):
        for outgoing, incoming, evidence in (
            ("To card ****2028", "BANK TRANSFER", "From account ****096"),
            ("BANK TRANSFER", "BANK TRANSFER", "Payment thank you"),
        ):
            with self.subTest(outgoing=outgoing, evidence=evidence):
                accounts = {
                    "source": [transaction("out", "expense", description=outgoing)],
                    "destination": [
                        transaction("in", "income", description=incoming),
                        transaction("role-evidence", "income", 999, description=evidence),
                    ],
                }
                self.assertEqual(combine_transactions(accounts, "12:00:00")[1], 0)

    def test_graph_resolves_forced_pairs_with_overlapping_date_windows(self):
        audit = []
        combined, count = combine_transactions({
            "debit": [
                transaction("out-1", "expense", date="2025-08-05", description="To card ****2028"),
                transaction("out-2", "expense", date="2025-08-08", description="To card ****2028"),
            ],
            "credit": [
                transaction("in-1", "income", date="2025-08-06", description="Payment thank you"),
                transaction("in-2", "income", date="2025-08-11", description="Payment thank you"),
            ],
        }, "12:00:00", audit=audit)
        self.assertEqual((count, len(combined)), (2, 2))
        self.assertEqual(
            {(entry["outgoing"]["id"], entry["incoming"]["id"]) for entry in audit},
            {("out-1", "in-1"), ("out-2", "in-2")},
        )
        self.assertTrue(all(entry["method"] == "forced_graph" for entry in audit))

    def test_equivalent_repeats_are_balanced_and_deterministic(self):
        accounts = {
            "debit": [
                transaction("out-1", "expense", 400, description="INTERNET TRANSFER 000000114917"),
                transaction("out-2", "expense", 400, description="INTERNET TRANSFER 000000102870"),
            ],
            "credit": [
                transaction("in-1", "income", 400, description="Payment thank you"),
                transaction("in-2", "income", 400, description="Payment thank you"),
            ],
        }
        first_audit, reversed_audit = [], []
        first, count = combine_transactions(accounts, "12:00:00", audit=first_audit)
        reversed_accounts = {name: list(reversed(rows)) for name, rows in reversed(list(accounts.items()))}
        second, second_count = combine_transactions(reversed_accounts, "12:00:00", audit=reversed_audit)
        self.assertEqual((count, second_count), (2, 2))
        self.assertEqual(first, second)
        self.assertEqual(first_audit, reversed_audit)
        self.assertTrue(all(entry["method"] == "equivalent_repeats" for entry in first_audit))
        self.assertEqual(len({entry["incoming"]["id"] for entry in first_audit}), 2)
        accounts["credit"].pop()
        self.assertEqual(combine_transactions(accounts, "12:00:00")[1], 0)

    def test_forced_pair_resolves_without_consuming_ambiguous_neighbors(self):
        audit, diagnostics = [], []
        combined, count = combine_transactions({
            "debit-1": [transaction("out-1", "expense")],
            "debit-2": [transaction("out-2", "expense")],
            "debit-3": [transaction("out-3", "expense", date="2026-10-07")],
            "saving": [
                transaction("in-1", "income"),
                transaction("in-2", "income", date="2026-10-04"),
                transaction("in-3", "income", date="2026-10-10"),
            ],
        }, "12:00:00", audit=audit, diagnostics=diagnostics)
        self.assertEqual((count, len(combined)), (1, 5))
        self.assertEqual((audit[0]["outgoing"]["id"], audit[0]["incoming"]["id"]), ("out-3", "in-3"))
        self.assertEqual(len(diagnostics), 4)
        self.assertTrue(all(entry["reason"] == "ambiguous" for entry in diagnostics))

    def test_repeats_with_different_dates_or_card_targets_remain_ambiguous(self):
        for changed in ("date", "description", "currency"):
            accounts = {
                "debit": [
                    transaction("out-1", "expense", description="To card ****2028"),
                    transaction("out-2", "expense", description="To card ****2028"),
                ],
                "credit": [
                    transaction("in-1", "income", description="Payment thank you"),
                    transaction("in-2", "income", description="Payment thank you"),
                ],
            }
            if changed == "date":
                accounts["credit"][1]["date"] = "2026-10-02"
            elif changed == "description":
                accounts["debit"][1]["description"] = "To card ****9999"
            else:
                # Currency mismatches must not even become graph edges.
                for row in accounts["debit"]:
                    row["currency"] = "CAD"
                for row in accounts["credit"]:
                    row["currency"] = "USD"
            with self.subTest(changed=changed):
                combined, count = combine_transactions(accounts, "12:00:00")
                self.assertEqual((count, len(combined)), (0, 4))

    def test_three_accounts_and_both_savings_directions(self):
        purchase = transaction("purchase", "expense", 15, description="COFFEE")
        accounts = {
            "debit": [
                transaction("to-savings", "expense", 100, description="To account 12345/****096"),
                transaction("from-savings", "income", 50, description="From account 12345/****096"),
                transaction("to-credit", "expense", 200, description="To card ****2028"),
                purchase,
            ],
            "savings": [
                transaction("deposit", "income", 100, description="From account 12345/****596"),
                transaction("withdrawal", "expense", 50, description="To account 12345/****596"),
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

    def test_ambiguity_on_either_side_is_preserved_regardless_of_order_or_date(self):
        for first_flow, other_flow in (("expense", "income"), ("income", "expense")):
            accounts = {
                "debit": [transaction("first", first_flow, date="2026-10-03")],
                "savings": [transaction("farther", other_flow)],
                "credit": [transaction("closest", other_flow, date="2026-10-03")],
            }
            for order in permutations(accounts.items()):
                with self.subTest(first_flow=first_flow, order=[name for name, _ in order]):
                    combined, count = combine_transactions(dict(order), "12:00:00")
                    self.assertEqual(count, 0)
                    self.assertCountEqual(combined, [
                        dict(item, account=name) for name, items in accounts.items() for item in items
                    ])

    def test_same_amount_savings_to_debit_to_card_chain(self):
        prefix = "Internet Banking INTERNET TRANSFER 123456 "
        combined, count = combine_transactions({
            "debit": [
                transaction("bank-in", "income", 700, description=prefix + "From account ****096"),
                transaction("card-out", "expense", 700, description=prefix + "To card ****2028"),
            ],
            "saving": [transaction("bank-out", "expense", 700, description=prefix + "To account ****596")],
            "credit": [transaction("card-in", "income", 700, description="Payment thank you/PAIEMEN T MERCI")],
        }, "12:00:00")
        self.assertEqual(count, 2)
        self.assertEqual(
            {(item["fromAccount"], item["toAccount"]) for item in combined},
            {("saving", "debit"), ("debit", "credit")},
        )

    def test_incompatible_helpers_and_ordinary_eft_do_not_merge(self):
        for outgoing, incoming in (
            ("To account ****596", "Payment thank you"),
            ("To card ****2028", "From account ****096"),
            ("From account ****096", "To account ****596"),
            ("Electronic Funds Transfer RENT", "Electronic Funds Transfer PAYROLL"),
            ("E-TRANSFER TO A FRIEND", "E-TRANSFER FROM A FRIEND"),
        ):
            with self.subTest(outgoing=outgoing, incoming=incoming):
                combined, count = combine_transactions({
                    "one": [transaction("out", "expense", description=outgoing)],
                    "two": [transaction("in", "income", description=incoming)],
                }, "12:00:00")
                self.assertEqual(count, 0)
                self.assertEqual(len(combined), 2)

    def test_french_card_payment_variants(self):
        for description in ("PAIEMENT MERCI", "painment merci", "PAIEMEN T MERCI"):
            with self.subTest(description=description):
                combined, count = combine_transactions({
                    "debit": [transaction("out", "expense", description="To card ****2028")],
                    "credit": [transaction("in", "income", description=description)],
                }, "12:00:00")
                self.assertEqual(count, 1)
                self.assertEqual(combined[0]["toAccount"], "credit")

    def test_nonmatching_entries_are_preserved(self):
        cases = [
            ("same account", "debit", transaction("in", "income")),
            ("same flow", "savings", transaction("in", "expense")),
            ("different amount", "savings", transaction("in", "income", 100.01)),
            ("outside date window", "savings", transaction("in", "income", date="2026-10-07")),
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
                expected_incoming = incoming if incoming["type"] == "internal" else dict(incoming, account=account)
                self.assertCountEqual(combined, [dict(outgoing, account="debit"), expected_incoming])

    def test_five_day_boundary_and_decimal_amounts(self):
        combined, count = combine_transactions({
            "debit": [transaction("out", "expense", "100.10")],
            "savings": [transaction("in", "income", 100.1, date="2026-10-06")],
        }, "12:00:00")
        self.assertEqual(count, 1)
        self.assertEqual(combined[0]["amount"], 100.1)

    def test_report_lists_ambiguous_and_unmatched_transfers_only(self):
        diagnostics = []
        combined, count = combine_transactions({
            "debit": [
                transaction("ambiguous-out", "expense", description="To card ****2028"),
                transaction("missing-out", "expense", 99, description="To account ****096"),
                transaction("ordinary", "expense", 15, description="COFFEE"),
            ],
            "credit": [
                transaction("ambiguous-in-1", "income", description="Payment thank you"),
                transaction("ambiguous-in-2", "income", description="Payment thank you"),
            ],
        }, "12:00:00", diagnostics=diagnostics)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            report_unmerged_transfers(combined, diagnostics)
        report = output.getvalue()
        self.assertEqual(count, 0)
        self.assertIn("Unmerged transfer transactions: 4", report)
        self.assertIn("Ambiguous: 3; missing compatible counterparts: 1", report)
        self.assertIn("reason=ambiguous", report)
        self.assertIn("reason=missing_counterpart", report)
        for item in combined:
            if item["id"] == "ordinary":
                self.assertNotIn("COFFEE", report)
            else:
                for key in ("id", "date", "description"):
                    self.assertIn(item[key], report)


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
                output_log = io.StringIO()
                with contextlib.redirect_stdout(output_log):
                    self.assertEqual(main(), 0)
                self.assertIn("Unmerged transfer transactions: 0", output_log.getvalue())
            payload = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["transactions"]), 1)
            self.assertEqual(payload["transactions"][0]["toAccount"], "savings")
            run_log = output.with_suffix(".txt").read_text(encoding="utf-8")
            self.assertIn(output_log.getvalue(), run_log)
            self.assertIn(str(output), run_log)
            self.assertIn("id=out <- incoming_id=in | forced_graph", run_log)
            self.assertIn("forced_graph: Pair occurs in every maximum matching", run_log)
            self.assertNotIn("BANK TRANSFER", run_log)
            self.assertNotIn('"matchedPairs"', run_log)
            self.assertFalse(output.with_name("transactions-audit.json").exists())
            self.assertIn("Matching methods: forced_graph=1", output_log.getvalue())

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

    def test_text_log_preserves_report_and_ambiguous_candidate_references(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            outgoing = transaction("out", "expense", description="To card ****2028")
            incoming = [transaction(f"in-{number}", "income", description="Payment thank you") for number in (1, 2)]
            (root / "debit.json").write_text(json.dumps({"transactions": [outgoing]}), encoding="utf-8")
            (root / "credit.json").write_text(json.dumps({"transactions": incoming}), encoding="utf-8")
            arguments = ["combinejson.py", "-a", "debit", str(root / "debit.json"),
                         "-a", "credit", str(root / "credit.json")]
            output = root / "transactions.json"
            report = io.StringIO()
            with patch("sys.argv", arguments), patch("combinejson.default_output_path", return_value=output):
                with contextlib.redirect_stdout(report):
                    self.assertEqual(main(), 0)
            log = output.with_suffix(".txt").read_text(encoding="utf-8")
            self.assertIn(report.getvalue(), log)
            self.assertIn("Ambiguous: 3; missing compatible counterparts: 0", log)
            self.assertIn("id=out | candidates=in-1, in-2", log)
            self.assertNotIn('"transactions"', log)
            self.assertFalse(list(root.glob("*-audit.json")))


class LocalInputRegressionTests(unittest.TestCase):
    @unittest.skipUnless(
        all((Path(__file__).parent.parent / "input" / f"{name}.json").exists() for name in ("debit", "saving", "credit")),
        "Local bank input files are not available",
    )
    def test_available_three_account_inputs(self):
        accounts = {
            name: load_transactions(Path(__file__).parent.parent / "input" / f"{name}.json")
            for name in ("debit", "saving", "credit")
        }
        before = json.dumps(accounts, sort_keys=True)
        audit, diagnostics = [], []
        combined, count = combine_transactions(accounts, "12:00:00", audit=audit, diagnostics=diagnostics)
        self.assertEqual((count, len(combined), len(diagnostics)), (100, 1297, 2))
        self.assertEqual(
            {(entry["transaction"]["date"], entry["transaction"]["amount"], entry["reason"]) for entry in diagnostics},
            {("2026-10-30", 300, "missing_counterpart"), ("2026-10-30", 100, "missing_counterpart")},
        )
        self.assertEqual(len(audit), count)
        original_ids = {row["id"] for rows in accounts.values() for row in rows}
        consumed_ids = [entry[flow]["id"] for entry in audit for flow in ("outgoing", "incoming")]
        self.assertEqual(len(set(consumed_ids)), 2 * count)
        self.assertTrue(set(consumed_ids) <= original_ids)
        self.assertEqual(before, json.dumps(accounts, sort_keys=True))
        before_balances = {
            name: sum(
                (Decimal(str(row["amount"])) * (1 if row["type"] == "income" else -1) for row in rows),
                Decimal(0),
            )
            for name, rows in accounts.items()
        }
        after_balances = dict.fromkeys(accounts, Decimal(0))
        for row in combined:
            amount = Decimal(str(row["amount"]))
            if row["type"] == "internal":
                after_balances[row["fromAccount"]] -= amount
                after_balances[row["toAccount"]] += amount
            else:
                after_balances[row["account"]] += amount if row["type"] == "income" else -amount
        self.assertEqual(before_balances, after_balances)


if __name__ == "__main__":
    unittest.main()
