from __future__ import annotations

import argparse
import csv
import json
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from rules import fallback_description, extract_description, infer_category, infer_transaction_type


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Convert CIBC transaction CSV files into obsidian-expensica transactions.json format."
    )
    parser.add_argument("input_csv", type=Path, help="Path to the CIBC CSV export.")
    parser.add_argument(
        "output_json",
        nargs="?",
        type=Path,
        help="Optional path to the output transactions.json file.",
    )
    parser.add_argument(
        "--pretty",
        action="store_true",
        help="Write indented JSON for easier inspection.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print converted JSON to stdout instead of writing the file.",
    )
    return parser


def generate_transaction_id(transaction_date: str, conversion_time: datetime) -> str:
    id_date = transaction_date.replace("-", "")
    return f"{id_date}-{conversion_time:%H%M%S}-{secrets.token_hex(4)}"


def row_to_transaction(row: list[str], conversion_time: datetime) -> dict[str, Any]:
    if len(row) != 4:
        raise ValueError(f"Expected 4 columns, got {len(row)}: {row!r}")

    date_text, raw_description, debit, credit = [cell.strip() for cell in row]
    transaction_type, amount = infer_transaction_type(debit, credit)
    description = extract_description(raw_description)
    if description == "Unknown transaction":
        description = fallback_description(raw_description, transaction_type)
    category = infer_category(transaction_type, raw_description, description)

    return {
        "id": generate_transaction_id(date_text, conversion_time),
        "date": date_text,
        "time": f"{conversion_time:%H:%M:%S}",
        "type": transaction_type,
        "amount": float(amount),
        "description": description,
        "category": category,
    }


def convert_csv(input_csv: Path, conversion_time: datetime) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []

    with input_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        for line_number, row in enumerate(reader, start=1):
            if not row or all(not cell.strip() for cell in row):
                continue

            try:
                transactions.append(row_to_transaction(row, conversion_time))
            except ValueError as exc:
                raise ValueError(f"Failed to parse CSV row {line_number}: {exc}") from exc

    return sorted(transactions, key=lambda transaction: transaction["date"])


def next_incremental_path(path: Path) -> Path:
    for index in range(1, 10_000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate

    raise RuntimeError(f"Could not find an available output filename for {path}")


def default_output_path(conversion_time: datetime) -> Path:
    tool_dir = Path(__file__).resolve().parent
    path = tool_dir / "output" / f"transactions-{conversion_time:%Y%m%d-%H%M%S}.json"
    return path if not path.exists() else next_incremental_path(path)


def resolve_output_path(output_json: Path | None, conversion_time: datetime) -> Path:
    if output_json is None:
        return default_output_path(conversion_time)

    if not output_json.exists():
        return output_json

    while True:
        answer = input(
            f"{output_json} already exists. Overwrite it or write to a new suffixed file? [o/n]: "
        ).strip().lower()

        if answer in {"o", "overwrite"}:
            return output_json
        if answer in {"n", "new"}:
            return next_incremental_path(output_json)

        print("Please enter 'o' to overwrite or 'n' to write a new suffixed file.")


def write_output(
    output_json: Path,
    transactions: list[dict[str, Any]],
    *,
    pretty: bool,
) -> dict[str, Any]:
    payload = {"transactions": transactions}

    output_json.parent.mkdir(parents=True, exist_ok=True)
    indent = 2 if pretty else None
    text = json.dumps(payload, indent=indent, ensure_ascii=False)
    output_json.write_text(text + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    conversion_time = datetime.now()
    transactions = convert_csv(args.input_csv, conversion_time)

    if args.dry_run:
        payload = {"transactions": transactions}
        print(json.dumps(payload, indent=2 if args.pretty else None, ensure_ascii=False))
        return 0

    output_json = resolve_output_path(args.output_json, conversion_time)
    write_output(
        output_json,
        transactions,
        pretty=args.pretty,
    )
    print(f"Converted {len(transactions)} transactions into {output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
