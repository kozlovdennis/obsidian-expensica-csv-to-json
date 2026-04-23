from __future__ import annotations

import argparse
import json
from datetime import datetime
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge chequing and credit JSON files and collapse matched transfers."
    )
    parser.add_argument("property1", help="Name of the chequing account.")
    parser.add_argument("property2", help="Name of the credit account.")
    parser.add_argument("chequing_json", type=Path, help="Path to the chequing JSON file.")
    parser.add_argument("credit_json", type=Path, help="Path to the credit JSON file.")
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


def is_credit_transfer_candidate(transaction: dict[str, Any]) -> bool:
    description = normalize_description(str(transaction.get("description", "")))
    return (
        contains_all_terms(description, ("PAYMENT", "THANK"))
        or contains_all_terms(description, ("CASH", "ADVANCE"))
    )


def is_chequing_transfer_candidate(transaction: dict[str, Any]) -> bool:
    description = normalize_description(str(transaction.get("description", "")))
    return (
        contains_all_terms(description, ("TRANSFER",))
        or contains_all_terms(description, ("BANK", "TRANSFER"))
        or contains_all_terms(description, ("INTERNET", "TRANSFER"))
    )


def is_opposite_flow(chequing: dict[str, Any], credit: dict[str, Any]) -> bool:
    chequing_type = str(chequing.get("type", "")).lower()
    credit_type = str(credit.get("type", "")).lower()
    return {chequing_type, credit_type} == {"expense", "income"}


def build_internal_transaction(
    chequing: dict[str, Any],
    credit: dict[str, Any],
    chequing_account: str,
    credit_account: str,
    fallback_time: str,
) -> dict[str, Any]:
    chequing_type = str(chequing["type"]).lower()
    credit_type = str(credit["type"]).lower()

    if chequing_type == "expense" and credit_type == "income":
        description = "TRANSFER TO CREDIT"
        from_account = chequing_account
        to_account = credit_account
    elif chequing_type == "income" and credit_type == "expense":
        description = "TRANSFER TO DEBIT"
        from_account = credit_account
        to_account = chequing_account
    else:
        raise ValueError(
            f"Unsupported transfer flow: chequing={chequing_type!r}, credit={credit_type!r}"
        )

    return {
        "id": chequing["id"],
        "date": chequing["date"],
        "time": str(chequing.get("time") or fallback_time),
        "type": "internal",
        "amount": float(amount_as_decimal(chequing)),
        "description": description,
        "category": "internal",
        "fromAccount": from_account,
        "toAccount": to_account,
    }


def find_matches(
    chequing_transactions: list[dict[str, Any]],
    credit_transactions: list[dict[str, Any]],
    chequing_account: str,
    credit_account: str,
    fallback_time: str,
) -> tuple[list[dict[str, Any]], set[int], set[int]]:
    combined: list[dict[str, Any]] = []
    matched_chequing_indices: set[int] = set()
    matched_credit_indices: set[int] = set()
    candidate_pairs: list[tuple[int, int, int, int]] = []

    for chequing_index, chequing in enumerate(chequing_transactions):
        if not is_chequing_transfer_candidate(chequing):
            continue

        chequing_date = parse_transaction_date(chequing)
        chequing_amount = amount_as_decimal(chequing)

        for credit_index, credit in enumerate(credit_transactions):
            if not is_credit_transfer_candidate(credit):
                continue
            if amount_as_decimal(credit) != chequing_amount:
                continue
            if not is_opposite_flow(chequing, credit):
                continue
            credit_date = parse_transaction_date(credit)
            date_diff = abs((credit_date - chequing_date).days)
            if date_diff > 3:
                continue
            order_diff = abs(credit_index - chequing_index)
            candidate_pairs.append((date_diff, order_diff, chequing_index, credit_index))

    candidate_pairs.sort()

    for _, _, chequing_index, credit_index in candidate_pairs:
        if chequing_index in matched_chequing_indices or credit_index in matched_credit_indices:
            continue

        chequing = chequing_transactions[chequing_index]
        credit = credit_transactions[credit_index]
        combined.append(
            build_internal_transaction(
                chequing,
                credit,
                chequing_account,
                credit_account,
                fallback_time,
            )
        )
        matched_chequing_indices.add(chequing_index)
        matched_credit_indices.add(credit_index)

    return combined, matched_chequing_indices, matched_credit_indices


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
    chequing_transactions: list[dict[str, Any]],
    credit_transactions: list[dict[str, Any]],
    chequing_account: str,
    credit_account: str,
    fallback_time: str,
) -> tuple[list[dict[str, Any]], int]:
    internal_transactions, matched_chequing, matched_credit = find_matches(
        chequing_transactions,
        credit_transactions,
        chequing_account,
        credit_account,
        fallback_time,
    )

    unmatched_chequing = [
        with_account(transaction, chequing_account)
        for index, transaction in enumerate(chequing_transactions)
        if index not in matched_chequing
    ]
    unmatched_credit = [
        with_account(transaction, credit_account)
        for index, transaction in enumerate(credit_transactions)
        if index not in matched_credit
    ]

    return (
        sort_transactions(unmatched_chequing + unmatched_credit + internal_transactions),
        len(internal_transactions),
    )


def write_output(path: Path, transactions: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"transactions": transactions}
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    run_time = datetime.now()

    chequing_transactions = load_transactions(args.chequing_json)
    credit_transactions = load_transactions(args.credit_json)
    combined_transactions, combined_count = combine_transactions(
        chequing_transactions,
        credit_transactions,
        args.property1,
        args.property2,
        f"{run_time:%H:%M:%S}",
    )

    output_path = default_output_path(run_time)
    write_output(output_path, combined_transactions)
    print(f"Combined {combined_count} transfer pairs")
    print(f"Wrote {len(combined_transactions)} transactions to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
