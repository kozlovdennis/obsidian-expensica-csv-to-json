from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


EXPENSE_FALLBACK_CATEGORY = "other_expense"
INCOME_FALLBACK_CATEGORY = "other_income"

_PREFIX_PATTERNS = [
    re.compile(r"^Point of Sale - Interac\s+", re.IGNORECASE),
    re.compile(r"^Point of Sale - Visa Debit\s+", re.IGNORECASE),
    re.compile(r"^Electronic Funds Transfer\s+", re.IGNORECASE),
    re.compile(r"^Internet Banking\s+", re.IGNORECASE),
    re.compile(r"^Branch Transaction\s+", re.IGNORECASE),
    re.compile(r"^Automated Banking Machine\s+", re.IGNORECASE),
]

_PHRASE_PATTERNS = [
    re.compile(r"\bINTL VISA DEB RETAIL PURCHASE\b", re.IGNORECASE),
    re.compile(r"\bVISA DEBIT RETAIL PURCHASE\b", re.IGNORECASE),
    re.compile(r"\bRETAIL PURCHASE\b", re.IGNORECASE),
    re.compile(r"\bPREAUTHORIZED DEBIT\b", re.IGNORECASE),
    re.compile(r"\bINTERNET BILL PAY\b", re.IGNORECASE),
    re.compile(r"\bINTERNET TRANSFER\b", re.IGNORECASE),
    re.compile(r"\bE-TRANSFER\b", re.IGNORECASE),
    re.compile(r"\bSERVICE CHARGE\b", re.IGNORECASE),
    re.compile(r"\bPAY\b", re.IGNORECASE),
]

_TRAILING_PATTERNS = [
    re.compile(r"\b\d+(?:\.\d+)?\s+USD\s+@\s+\d+(?:\.\d+)?\s*$", re.IGNORECASE),
]

_DESCRIPTION_CLEANUPS = [
    (re.compile(r"\bSQ \*", re.IGNORECASE), ""),
    (re.compile(r"^[A-Z0-9-]{8,}\s+"), ""),
    (re.compile(r"\$\d+(?:\.\d+)?", re.IGNORECASE), " "),
    (re.compile(r"\s+"), " "),
]

_EXPENSE_CATEGORY_RULES = [
    ("food", ("COFF", "COFFEE", "CAFE", "TIM HORTONS", "A&W", "KATSU", "CHA HOUSE", "HAYDEN BLOC", "RESTAURANT", "PIZZA", "BURGER", "UBEREATS", "DOORDASH", "BAR", "EATERY")),
    ("groceries", ("GROC", "MARKET", "SUPERMARKET", "GROCERY", "T&T", "WALMART", "SAFEWAY", "SUPERC", "CO-OP GROC", "COSTCO", "FRESCO")),
    ("transportation", ("GAS", "FUEL", "PARKING", "UBER", "LYFT", "TRANSIT", "PETRO", "SHELL", "ESSO", "CO-OP GAS")),
    ("utilities", ("ENMAX", "UTILITY", "UTILITIES", "ELECTRIC", "WATER")),
    ("internet", ("TELUS", "ROGERS", "BELL", "FIDO", "KOODO", "MOBILITY", "MOBILE", "INTERNET")),
    ("entertainment", ("NETFLIX", "SPOTIFY", "STEAM", "PLAYSTATION", "NINTENDO")),
    ("insurance", ("INTACT", "INSURANCE")),
    ("subscriptions", ("SUBSCRIPTION", "MIDJOURNEY", "CLAUDE.AI", "RECURRING", "ADOBE", "OPENAI", "CHATGPT")),
    ("shopping", ("AMAZON", "SHOP", "STORE", "MALL")),
]

_INCOME_CATEGORY_RULES = [
    ("salary", ("PAYROLL", "PAY ", "DEPOSIT", "WAGE", "SALARY", "E-TRANSFER", "ETRANSFER")),
    ("gifts_received", ("GIFT")),
    ("other_income", ("REFUND", "REVERSAL")),
]


def parse_amount(value: str) -> Decimal | None:
    text = value.strip()
    if not text:
        return None

    normalized = text.replace(",", "").replace("$", "")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid amount: {value!r}") from exc


def infer_transaction_type(debit: str, credit: str) -> tuple[str, Decimal]:
    debit_amount = parse_amount(debit)
    credit_amount = parse_amount(credit)

    if debit_amount is not None and credit_amount is None:
        return "expense", debit_amount
    if credit_amount is not None and debit_amount is None:
        return "income", credit_amount
    if debit_amount is None and credit_amount is None:
        raise ValueError("Row has no amount in either debit or credit column")
    raise ValueError("Row has amounts in both debit and credit columns")


def extract_description(raw_description: str) -> str:
    description = raw_description.strip()

    for pattern in _PREFIX_PATTERNS:
        description = pattern.sub("", description)

    for pattern in _TRAILING_PATTERNS:
        description = pattern.sub("", description)

    for pattern in _PHRASE_PATTERNS:
        description = pattern.sub(" ", description)

    description = re.sub(r"\b\d{6,}\b", " ", description)

    for pattern, replacement in _DESCRIPTION_CLEANUPS:
        description = pattern.sub(replacement, description)

    description = description.strip(" -.,")
    return description or "Unknown transaction"


def infer_category(transaction_type: str, raw_description: str, description: str) -> str:
    haystack = description.upper()
    rules = _EXPENSE_CATEGORY_RULES if transaction_type == "expense" else _INCOME_CATEGORY_RULES

    for category, keywords in rules:
        if any(keyword in haystack for keyword in keywords):
            return category

    return EXPENSE_FALLBACK_CATEGORY if transaction_type == "expense" else INCOME_FALLBACK_CATEGORY
