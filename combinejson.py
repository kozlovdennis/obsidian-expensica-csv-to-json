from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal
from itertools import combinations
from pathlib import Path
from typing import Any


_BANK_REFERENCE = re.compile(
    r"(\b(?:INTERNET TRANSFER|BANK TRANSFER|REFERENCE|REF)\s*(?:#|NO\.?|NUMBER)?\s*)(\d{6,})\b"
)


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


def amount_as_decimal(transaction: dict[str, Any]) -> Decimal:
    return Decimal(str(transaction["amount"]))


def parse_transaction_date(transaction: dict[str, Any]) -> date:
    return datetime.strptime(str(transaction["date"]), "%Y-%m-%d").date()


def transfer_kind(transaction: dict[str, Any]) -> str | None:
    flow = str(transaction.get("type", "")).lower()
    if flow not in {"expense", "income"}:
        return None
    description = normalize_description(str(transaction.get("description", "")))
    # Specific helpers take priority over the bank's generic INTERNET TRANSFER prefix.
    for phrase, expected_flow, kind in (
        (r"\bTO CARD\b", "expense", "card"),
        (r"\bTO ACCOUNT\b", "expense", "bank"),
        (r"\bFROM ACCOUNT\b", "income", "bank"),
        (r"\bPAYMENT THANK YOU\b|\bPAI(?:EMENT|NMENT|EMEN T) MERCI\b", "income", "card"),
        (r"\bCASH ADVANCE\b", "expense", "cash"),
    ):
        if re.search(phrase, description):
            return kind if flow == expected_flow else None
    if re.search(r"\b(?:BANK|INTERNET) TRANSFER\b", description):
        return "generic"
    return None


def is_transfer_candidate(transaction: dict[str, Any]) -> bool:
    return transfer_kind(transaction) is not None


def bank_reference(transaction: dict[str, Any]) -> str | None:
    description = normalize_description(str(transaction.get("description", "")))
    match = _BANK_REFERENCE.search(description)
    return (match.group(2).lstrip("0") or "0") if match else None


def maximum_matching(
    graph: dict[int, set[int]], sources: list[int], excluded: tuple[int, int] | None = None,
) -> dict[int, int]:
    """Find a maximum bipartite matching, optionally excluding one edge."""
    partners: dict[int, int] = {}

    def assign(source: int, visited: set[int]) -> bool:
        for destination in sorted(graph[source]):
            if (source, destination) == excluded or destination in visited:
                continue
            visited.add(destination)
            if destination not in partners or assign(partners[destination], visited):
                partners[destination] = source
                return True
        return False

    for source in sorted(sources):
        assign(source, set())
    return {source: destination for destination, source in partners.items()}


def connected_components(graph: dict[int, set[int]]) -> list[set[int]]:
    pending = {index for index, partners in graph.items() if partners}
    components = []
    while pending:
        component: set[int] = set()
        stack = [min(pending)]
        while stack:
            index = stack.pop()
            if index in component:
                continue
            component.add(index)
            stack.extend(graph[index] - component)
        pending.difference_update(component)
        components.append(component)
    return components


def financial_signature(transaction: dict[str, Any]) -> tuple[Any, ...]:
    # IDs and bank references may differ between otherwise identical repeats.
    description = normalize_description(str(transaction.get("description", "")))
    return (
        transaction["account"], transaction["date"], transaction.get("time", ""),
        str(transaction["type"]).lower(), amount_as_decimal(transaction),
        transaction.get("currency"), _BANK_REFERENCE.sub(r"\1<REFERENCE>", description),
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
    if str(transaction.get("type", "")).lower() != "internal":
        updated["account"] = account_name
    return updated


def default_output_path(run_time: datetime) -> Path:
    tool_dir = Path(__file__).resolve().parent
    return tool_dir / "output" / f"transactions-combined-{run_time:%Y%m%d-%H%M%S}.json"


def combine_transactions(
    accounts: dict[str, list[dict[str, Any]]],
    fallback_time: str,
    *,
    audit: list[dict[str, Any]] | None = None,
    diagnostics: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], int]:
    transactions = sort_transactions([
        with_account(transaction, account_name)
        for account_name, account_transactions in accounts.items()
        for transaction in account_transactions
    ])
    candidates = [
        (index, transaction, kind)
        for index, transaction in enumerate(transactions)
        if (kind := transfer_kind(transaction)) is not None
    ]
    # Infer bank/credit roles from explicit descriptions, never from account labels.
    account_types: dict[str, set[str]] = {name: set() for name in accounts}
    for _, transaction, kind in candidates:
        if kind != "generic":
            is_credit = kind == "cash" or (kind == "card" and transaction["type"].lower() == "income")
            role = "credit" if is_credit else "bank"
            account_types[transaction["account"]].add(role)
    references = {index: bank_reference(transaction) for index, transaction, _ in candidates}
    matches: dict[int, set[int]] = {index: set() for index, _, _ in candidates}
    for (first_index, first, first_kind), (second_index, second, second_kind) in combinations(candidates, 2):
        if first["account"] == second["account"] or not is_opposite_flow(first, second):
            continue
        first_role, second_role = account_types[first["account"]], account_types[second["account"]]
        if len(first_role) > 1 or len(second_role) > 1:
            continue
        if first_kind != second_kind and "generic" not in {first_kind, second_kind}:
            continue
        if str(first["type"]).lower() == "expense":
            source_kind, destination_kind = first_kind, second_kind
            source_role, destination_role = first_role, second_role
        else:
            source_kind, destination_kind = second_kind, first_kind
            source_role, destination_role = second_role, first_role
        if source_role == {"credit"} and (source_kind != "cash" or destination_role == {"credit"}):
            continue
        if destination_role == {"credit"} and (destination_kind != "card" or source_kind not in {"card", "generic"}):
            continue
        if source_kind == "card" and destination_role == {"bank"}:
            continue
        first_reference, second_reference = references[first_index], references[second_index]
        if first_reference is not None and second_reference is not None and first_reference != second_reference:
            continue
        if first.get("currency") != second.get("currency"):
            continue
        if amount_as_decimal(first) != amount_as_decimal(second):
            continue
        date_diff = abs((parse_transaction_date(first) - parse_transaction_date(second)).days)
        if date_diff <= 5:
            matches[first_index].add(second_index)
            matches[second_index].add(first_index)

    # An exact reference takes precedence over weaker edges incident to either entry.
    reference_nodes = {
        index for index, partners in matches.items()
        if references[index] is not None and any(references[index] == references[other] for other in partners)
    }
    matches = {
        index: {
            other for other in partners
            if not ({index, other} & reference_nodes) or references[index] == references[other]
        }
        for index, partners in matches.items()
    }

    sources = [index for index, transaction, _ in candidates if str(transaction["type"]).lower() == "expense"]
    maximum = maximum_matching(matches, sources)
    resolved = []
    for source, destination in sorted(maximum.items()):
        # Only edges present in every maximum matching are logically forced.
        if len(maximum_matching(matches, sources, (source, destination))) < len(maximum):
            same_reference = references[source] is not None and references[source] == references[destination]
            resolved.append((source, destination, "bank_reference" if same_reference else "forced_graph"))
    matched_indices = {index for source, destination, _ in resolved for index in (source, destination)}
    remaining_graph = {
        index: partners - matched_indices
        for index, partners in matches.items() if index not in matched_indices
    }
    for component in connected_components(remaining_graph):
        outgoing = sorted(component & set(sources))
        incoming = component - set(outgoing)
        if len(outgoing) != len(incoming):
            continue
        if len({financial_signature(transactions[index]) for index in outgoing}) != 1:
            continue
        if len({financial_signature(transactions[index]) for index in incoming}) != 1:
            continue
        equivalent = maximum_matching(remaining_graph, outgoing)
        if len(equivalent) == len(outgoing):
            resolved.extend(
                (source, destination, "equivalent_repeats")
                for source, destination in sorted(equivalent.items())
            )
            matched_indices.update(component)

    internal_transactions: list[dict[str, Any]] = []
    for source, destination, method in sorted(resolved):
        outgoing, incoming = transactions[source], transactions[destination]
        internal = build_internal_transaction(outgoing, incoming, fallback_time)
        internal_transactions.append(internal)
        if audit is not None:
            audit.append({
                "internalId": internal["id"], "method": method,
                "reason": {
                    "bank_reference": "Identical bank reference; forced pair in the compatible graph",
                    "forced_graph": "Pair occurs in every maximum matching of compatible transfers",
                    "equivalent_repeats": "Balanced identical repeats; every pairing has the same financial effect",
                }[method],
                "bankReference": references[source] if references[source] == references[destination] else None,
                "dateDifferenceDays": abs((parse_transaction_date(outgoing) - parse_transaction_date(incoming)).days),
                "outgoing": dict(outgoing), "incoming": dict(incoming),
            })

    if diagnostics is not None:
        for index, transaction, _ in candidates:
            if index not in matched_indices:
                partners = matches[index] - matched_indices
                diagnostics.append({
                    "transaction": dict(transaction),
                    "reason": "ambiguous" if partners else "missing_counterpart",
                    "candidateIds": [transactions[other]["id"] for other in sorted(partners)],
                })

    unmatched = [
        transaction for index, transaction in enumerate(transactions) if index not in matched_indices
    ]

    return (
        sort_transactions(unmatched + internal_transactions),
        len(internal_transactions),
    )


def write_output(path: Path, transactions: list[dict[str, Any]]) -> None:
    write_json(path, {"transactions": transactions})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def report_unmerged_transfers(
    transactions: list[dict[str, Any]], diagnostics: list[dict[str, Any]] | None = None,
) -> None:
    unresolved = [transaction for transaction in transactions if is_transfer_candidate(transaction)]
    print(f"Unmerged transfer transactions: {len(unresolved)}")
    if diagnostics is not None:
        counts = Counter(entry["reason"] for entry in diagnostics)
        print(f"Ambiguous: {counts['ambiguous']}; missing compatible counterparts: {counts['missing_counterpart']}")
    reasons = {
        (entry["transaction"]["account"], entry["transaction"]["id"]): entry["reason"]
        for entry in diagnostics or []
    }
    for transaction in unresolved:
        print(
            f"- {transaction['description']} | date={transaction['date']} | id={transaction['id']}"
            f" | account={transaction['account']} | amount={transaction['amount']}"
            f" | reason={reasons.get((transaction['account'], transaction['id']), 'unresolved')}"
        )


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
    audit: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    combined_transactions, combined_count = combine_transactions(
        accounts,
        f"{run_time:%H:%M:%S}",
        audit=audit, diagnostics=diagnostics,
    )

    output_path = default_output_path(run_time)
    write_output(output_path, combined_transactions)
    audit_path = output_path.with_name(f"{output_path.stem}-audit.json")
    write_json(audit_path, {"matchedPairs": audit, "unresolved": diagnostics})
    print(f"Combined {combined_count} transfer pairs")
    methods = Counter(entry["method"] for entry in audit)
    print("Matching methods: " + ", ".join(f"{method}={count}" for method, count in sorted(methods.items())))
    print(f"Wrote {len(combined_transactions)} transactions to {output_path}")
    print(f"Wrote pair audit to {audit_path}")
    report_unmerged_transfers(combined_transactions, diagnostics)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
