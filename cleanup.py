from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from rules import extract_description, fallback_description, infer_category


def clean_transaction(transaction: dict[str, Any]) -> dict[str, Any]:
    updated = dict(transaction)
    transaction_type = str(transaction.get("type", "")).lower()
    if transaction_type not in {"expense", "income"}:
        return updated

    raw_description = str(transaction.get("description", ""))
    description = extract_description(raw_description)
    if description == "Unknown transaction":
        description = fallback_description(raw_description, transaction_type)
    updated["description"] = description.upper()
    updated["category"] = infer_category(transaction_type, raw_description, description)
    return updated


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Clean transaction descriptions and assign categories in an existing JSON file."
    )
    parser.add_argument("input_json", type=Path, help="JSON file to update in place after confirmation.")
    args = parser.parse_args()

    payload = json.loads(args.input_json.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict) or not isinstance(payload.get("transactions"), list):
        parser.error("Expected a JSON object with a 'transactions' list")
    original = payload["transactions"]
    cleaned = [clean_transaction(transaction) for transaction in original]
    changed = sum(before != after for before, after in zip(original, cleaned))
    payload["transactions"] = cleaned
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    while True:
        try:
            answer = input(
                f"Clean {changed} transactions in {args.input_json} and overwrite this file? [y/n]: "
            ).strip().lower()
        except EOFError:
            answer = "n"
        if answer == "n":
            print("Cancelled; file unchanged.")
            return 0
        if answer == "y":
            break
        print("Please enter 'y' or 'n'.")

    args.input_json.write_text(text, encoding="utf-8")
    print(f"Cleaned {changed} transactions in {args.input_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
