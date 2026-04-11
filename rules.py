from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


EXPENSE_FALLBACK_CATEGORY = "other_expense"
INCOME_FALLBACK_CATEGORY = "other_income"
CategoryKeyword = str | re.Pattern[str]

_PREFIX_PATTERNS = [
    re.compile(r"^Point of Sale - Interac\s+", re.IGNORECASE),
    re.compile(r"^Point of Sale - Visa Debit\s+", re.IGNORECASE),
    re.compile(r"^Electronic Funds Transfer\s+", re.IGNORECASE),
    re.compile(r"^Internet Banking\s+", re.IGNORECASE),
    re.compile(r"^Branch Transaction\s+", re.IGNORECASE),
    re.compile(r"^Automated Banking Machine\s+", re.IGNORECASE),
]

_PHRASE_PATTERNS = [
    re.compile(r"\bINT VISA DEB PURCHASE REVERSAL\b", re.IGNORECASE),
    re.compile(r"\bINTL VISA DEB RETAIL PURCHASE\b", re.IGNORECASE),
    re.compile(r"\bVISA DEBIT PURCHASE REVERSAL\b", re.IGNORECASE),
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
    re.compile(r"\b\d+(?:\.\d+)?\s+[A-Z]{3}\s+@\s+\d+(?:\.\d+)?\s*$", re.IGNORECASE),
]

_DESCRIPTION_CLEANUPS = [
    (re.compile(r"\bSQ \*", re.IGNORECASE), ""),
    (re.compile(r"^[A-Z0-9-]{8,}\s+"), ""),
    (re.compile(r"\$\d+(?:\.\d+)?", re.IGNORECASE), " "),
    (re.compile(r"#\s+(\d+)"), r"#\1"),
    (re.compile(r"\bMCDONALD\s+S\b", re.IGNORECASE), "MCDONALD'S"),
    (re.compile(r"\s+"), " "),
]

_EXPENSE_CATEGORY_RULES = [
    (
        "food",
        (
            "JUICE",
            "TEA",
            "COF",
            "COFF",
            "COFFEE",
            "CAFE",
            "REGRUB",
            "TIM HORTONS",
            "MCDONALD",
            "KFC",
            "A&W",
            "KATSU",
            "CHA",
            "HAYDEN BLOC",
            "REST",
            "RESTA",
            "RESTAU",
            "RESTAURANT",
            "PIZZA",
            "BURGER",
            "UBEREATS",
            "DOORDASH",
            "PUB",
            "TAVER",
            "TAVERN",
            "BREW",
            "BREWERY",
            "COCKTAIL",
            "LOUNGE",
            "EATERY",
            "BULDAK STICK",
            "CACTUS CLUB",
            "NATIONAL 10",
            "SMOKEH",
            "LIQUOR",
            "BANK & BARON",
            "SOUL POCHA",
            "GINGER BEEF",
            "LOCAL 8TH",
            "ORIGINAL JOE'S",
            "CHICKEN OMNIBUS",
            "KERNELS",
            "ANGEL S DRIVE",
            "CALGARY LIFE CH",
            "VIETNA",
            "TST LEOPOLD",
            "CPA - MACHI",
            "PHOCITY",
            "SPICY FUSION RE",
            "FAMOUS WOK",
            "BOURBON",
            "HIDDEN CORN",
            "CHICKEN AVENUE",
            "CRAVE CRUSHER L",
            "RAMEN",
            "KOREA",
            "UKRAIN",
            "JAPAN",
            "WINE",
            "PARLOUR ICE CRE",
            "JIMMY'S",
            "GREEK",
            "BLACKSHEEP",
            "TASTE OF CA",
            "HIGHER GROUND",
            "ANALOG 17TH",
            "BEAVERTAILS",
            "BANFF SWEET SHO",
            "THE BISON RESTA",
            "CORNERSTONE CAT",
            "KITCHEN",
            "GONG CHA",
            "BUMBLINA BAKESH",
            "YOGEN FRUZ",
            "FUWA FUWA",
            "HAVEN HOUSE CAF",
            "TST-Paris Bague",
            "THE LOOPHOLE CO",
            "TST-Salt & Pepp",
            "RANCHMANS COOKH",
        ),
    ),
    (
        "groceries",
        (
            "GROC",
            "FRESHCO",
            "MARKET",
            "SUPERMARKET",
            "GROCERY",
            "RCSS",
            "SS CALGARY 6TH",
            "T&T",
            "WALMART",
            "SAFEWAY",
            "SUPERC",
            "CO-OP GROC",
            "COSTCO",
            "FRESCO",
            "MART",
            "FOOD",
            "SOBEYS",
            "BREAD",
        ),
    ),
    (
        "transportation",
        (
            "GAS",
            "FUEL",
            "PARK",
            "PARKING",
            "UBER",
            "LYFT",
            "TRANSIT",
            "PETRO",
            "SHELL",
            "ESSO",
            "CO-OP GAS",
            "CLAIRMONT HUSKY",
            "PLATES",
            "TRIP",
            "TRAVEL",
            "MECHANIC",
            "WESTJET",
            "AIRPORT",
            "COUNTRY HILLS P",
            "GLOBAL AUTO REP",
            "BOWNESS CAR WAS",
            "MR. LUBE",
        ),
    ),
    (
        "health",
        (
            "DRUGS",
        ),
    ),
    (
        "fitness",
        (
            "GYM",
            "AQUATICS",
            "VIVO FOR HEALTH",
            "SHANE HOMES YMC",
        ),
    ),
    (
        "utilities",
        (
            "ENMAX",
            "UTILITY",
            "UTILITIES",
            "ELECTRIC",
            "WATER",
            "UTIL",
        ),
    ),
    (
        "internet",
        (
            "TELUS",
            "ROGERS",
            "BELL",
            "FIDO",
            "KOODO",
            "MOBILITY",
            "MOBILE",
            "MOBIL",
        ),
    ),
    (
        "entertainment",
        (
            "NETFLIX",
            "SPOTIFY",
            "STEAM",
            "PLAYSTATION",
            "NINTENDO",
            "CANMORE NORDIC",
            "FAMOUS PLAYER",
        ),
    ),
    (
        "insurance",
        (
            "INTACT",
            "INSURANCE",
        ),
    ),
    (
        "subscriptions",
        (
            "SUBSCRIPTION",
            "MIDJOURNEY",
            "CLAUDE.AI",
            "RECURRING",
            "ADOBE",
            "OPENAI",
            "CHATGPT",
        ),
    ),
    (
        "rent",
        (
            "LANDLORD",
            "RENT",
            re.compile(r"\bADA\b", re.IGNORECASE),
            "Antony Sellars",
        ),
    ),
    (
        "education",
        (
            "UDEMY",
            "SCHOOL",
            "COURSE",
            "CHAPTER",
            "BOOK",
            "PAGES BOOKS",
        ),
    ),
    (
        "personal",
        (
            "BARBER",
            "BARB",
        ),
    ),
    (
        "shopping",
        (
            "AMAZON",
            "SHOP",
            "STORE",
            "MALL",
            "SPORT",
            "WINNERS",
            "BEST BUY",
            "FOREVER 21",
            "WWF",
            "CORE",
            "AMZN Mktp",
            "TIP TOP TAILORS",
            "LIDS",
            "NIKE",
            "JOURNEYS #8350",
            "SOFTMOC 89",
            "American Eagle",
            "MOUNTAIN EQUIPM",
            "IKEA",
            "CASELOGIX KIOSK",
            "MINISO",
        ),
    ),
]

_INCOME_CATEGORY_RULES = [
    (
        "salary",
        (
            "PAYROLL",
            "PAY ",
            "WAGE",
            "SALARY",
            "CPL DEPOSIT",
            "DEPOSIT CALGARY PUBLIC",
        ),
    ),
    (
        "gifts_received",
        (
            "GIFT",
        ),
    ),
    (
        "other_income",
        (
            "REFUND",
            "REVERSAL",
            "E-TRANSFER",
            "ETRANSFER",
            "TRANSFER",
        ),
    ),
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


def fallback_description(raw_description: str, transaction_type: str) -> str:
    if re.search(r"\bINTERNET TRANSFER\b", raw_description, re.IGNORECASE):
        direction = "Outgoing" if transaction_type == "expense" else "Incoming"
        reference_match = re.search(r"\b(\d{6,})\b", raw_description)
        if reference_match:
            return f"{direction} Bank Transfer #{reference_match.group(1)[-6:]}"
        return f"{direction} Bank Transfer"

    return "Unknown transaction"


def keyword_matches(keyword: CategoryKeyword, haystack: str) -> bool:
    if isinstance(keyword, str):
        return keyword.upper() in haystack

    return keyword.search(haystack) is not None


def infer_category(transaction_type: str, raw_description: str, description: str) -> str:
    haystack = description.upper()
    rules = _EXPENSE_CATEGORY_RULES if transaction_type == "expense" else _INCOME_CATEGORY_RULES

    for category, keywords in rules:
        if any(keyword_matches(keyword, haystack) for keyword in keywords):
            return category

    return EXPENSE_FALLBACK_CATEGORY if transaction_type == "expense" else INCOME_FALLBACK_CATEGORY
