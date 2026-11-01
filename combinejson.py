from __future__ import annotations

import argparse
import json
from datetime import datetime
from datetime import date
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge account JSON files and collapse matched transfers."
    )
    parser.add_argument(
        "--account",
        "--acc",
        "-a",
        action="append",
        nargs=2,
        required=True,
        metavar=("NAME", "FILE"),
        help="Account name and JSON path. Repeat for each account (at least two).",
    )
    return parser


def load_transactions(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    transactions = payload.get("transactions")
    if not isinstance(transactions, list):
        raise ValueError(f"Expected 'transactions' list in {path}")
    return transactions


def normalize_description(description: str) -> str:
    return " ".join(description.upper().replace("/", " ").split())


def contains_all_terms(description: str, terms: tuple[str, ...]) -> bool:
    return all(term in description for term in terms)


def amount_as_decimal(transaction: dict[str, Any]) -> Decimal:
    return Decimal(str(transaction["amount"]))


def parse_transaction_date(transaction: dict[str, Any]) -> date:
    return datetime.strptime(str(transaction["date"]), "%Y-%m-%d").date()


def is_transfer_candidate(transaction: dict[str, Any]) -> bool:
    description = normalize_description(str(transaction.get("description", "")))
    return (
        "TRANSFER" in description
        or contains_all_terms(description, ("PAYMENT", "THANK"))
        or contains_all_terms(description, ("CASH", "ADVANCE"))
    )


def is_opposite_flow(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return {str(first.get("type", "")).lower(), str(second.get("type", "")).lower()} == {
        "expense", "income"
    }


def build_internal_transaction(
    first: dict[str, Any],
    second: dict[str, Any],
    fallback_time: str,
) -> dict[str, Any]:
    if not is_opposite_flow(first, second):
        raise ValueError("Internal transfers require an expense and an income")
    source, destination = (first, second) if str(first["type"]).lower() == "expense" else (second, first)

    return {
        "id": source["id"],
        "date": source["date"],
        "time": str(source.get("time") or fallback_time),
        "type": "internal",
        "amount": float(amount_as_decimal(source)),
        "description": f"TRANSFER TO {destination['account']}".upper(),
        "category": "internal",
        "fromAccount": source["account"],
        "toAccount": destination["account"],
    }


def sort_transactions(transactions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        transactions,
        key=lambda transaction: (
            str(transaction.get("date", "")),
            str(transaction.get("time", "")),
            str(transaction.get("id", "")),
        ),
    )


def with_account(transaction: dict[str, Any], account_name: str) -> dict[str, Any]:
    updated = dict(transaction)
    updated["account"] = account_name
    return updated


def default_output_path(run_time: datetime) -> Path:
    tool_dir = Path(__file__).resolve().parent
    return tool_dir / "output" / f"transactions-combined-{run_time:%Y%m%d-%H%M%S}.json"


def combine_transactions(
    accounts: dict[str, list[dict[str, Any]]],
    fallback_time: str,
) -> tuple[list[dict[str, Any]], int]:
    transactions = [
        with_account(transaction, account_name)
        for account_name, account_transactions in accounts.items()
        for transaction in account_transactions
    ]
    candidates = [
        (index, transaction)
        for index, transaction in enumerate(transactions)
        if is_transfer_candidate(transaction)
    ]
    candidate_pairs: list[tuple[int, int, int]] = []
    for (first_index, first), (second_index, second) in combinations(candidates, 2):
        if first["account"] == second["account"] or not is_opposite_flow(first, second):
            continue
        if amount_as_decimal(first) != amount_as_decimal(second):
            continue
        date_diff = abs((parse_transaction_date(first) - parse_transaction_date(second)).days)
        if date_diff <= 3:
            candidate_pairs.append((date_diff, first_index, second_index))

    matched_indices: set[int] = set()
    internal_transactions: list[dict[str, Any]] = []
    for _, first_index, second_index in sorted(candidate_pairs):
        if first_index in matched_indices or second_index in matched_indices:
            continue
        internal_transactions.append(
            build_internal_transaction(
                transactions[first_index], transactions[second_index], fallback_time
            )
        )
        matched_indices.update((first_index, second_index))

    unmatched = [
        transaction for index, transaction in enumerate(transactions) if index not in matched_indices
    ]

    return (
        sort_transactions(unmatched + internal_transactions),
        len(internal_transactions),
    )


def write_output(path: Path, transactions: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"transactions": transactions}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if len(args.account) < 2:
        parser.error("Provide at least two --account NAME FILE arguments")
    account_names = [name for name, _ in args.account]
    if len(set(account_names)) != len(account_names):
        parser.error("Account names must be unique")
    run_time = datetime.now()

    accounts = {name: load_transactions(Path(path)) for name, path in args.account}
    combined_transactions, combined_count = combine_transactions(
        accounts,
        f"{run_time:%H:%M:%S}",
    )

    output_path = default_output_path(run_time)
    write_output(output_path, combined_transactions)
    print(f"Combined {combined_count} transfer pairs")
    print(f"Wrote {len(combined_transactions)} transactions to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
