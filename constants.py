"""
Configuration and regex patterns for receipt extraction.

The project currently focuses on German/European retail receipts and noisy OCR.
Keep this module dependency-free (stdlib only) so it can be imported in any
runtime (API worker, batch jobs, tests).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Iterable, Mapping, Pattern, Sequence

# ---------------------------------------------------------------------------
# Store lexicon
# ---------------------------------------------------------------------------

# NOTE: Keep store names in their "human" spelling. The extractor normalizes
# them (casefold + Unicode NFKC + optional accent folding) for matching.
KNOWN_STORES: Final[Sequence[str]] = (
    # Grocery / drugstores
    "rewe",
    "edeka",
    "aldi",
    "lidl",
    "penny",
    "netto",
    "kaufland",
    "real",
    "dm",
    "rossmann",
    "müller",
    "budni",
    # Electronics / DIY
    "ikea",
    "mediamarkt",
    "saturn",
    "obi",
    "bauhaus",
    "hornbach",
    "toom",
    "hagebau",
    # Convenience / food chains
    "späti",
    "spätverkauf",
    "kiosk",
    "trinkhalle",
    "mcdonald",
    "mcdonalds",
    "burger king",
    "subway",
    "starbucks",
    "dunkin",
    "backwerk",
    "ditsch",
    "nordsee",
    "vapiano",
    "dean & david",
    # Fuel
    "tankstelle",
    "aral",
    "shell",
    "esso",
    "jet",
    "totalenergies",
    "total",
    "star",
    # Misc retail
    "apotheke",
    "reformhaus",
    "bio company",
    "denns",
    "alnatura",
    "tk maxx",
    "primark",
    "h&m",
    "zara",
    "c&a",
    "deichmann",
    "foot locker",
    "expert",
    "euronics",
    "conrad",
    "action",
    "tedi",
    "woolworth",
    "nanu nana",
    "depot",
)

# German legal suffixes often appear in store headers but are not store names.
LEGAL_SUFFIXES: Final[Sequence[str]] = (
    "gmbh",
    "gmbh & co. kg",
    "ag",
    "kg",
    "ohg",
    "gbr",
    "ug",
    "e.k.",
    "ek",
    "e.v.",
)

# ---------------------------------------------------------------------------
# Keywords used by classifiers/extractors
# ---------------------------------------------------------------------------

TOTAL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "summe",
        "gesamt",
        "endsumme",
        "betrag",
        "zu zahlen",
        "zu bezahlen",
        "total",
        "amount",
        "gesamtbetrag",
    }
)

SUBTOTAL_KEYWORDS: Final[frozenset[str]] = frozenset({"zwischensumme", "subtotal"})

TAX_KEYWORDS: Final[frozenset[str]] = frozenset({"mwst", "ust", "steuer", "tax", "vat"})

DISCOUNT_KEYWORDS: Final[frozenset[str]] = frozenset(
    {"rabatt", "discount", "nachlass", "gutschein", "coupon", "aktion", "bonus"}
)

PAYMENT_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "bar",
        "cash",
        "bargeld",
        "ec",
        "ec-karte",
        "girocard",
        "maestro",
        "visa",
        "mastercard",
        "kreditkarte",
        "karte",
        "card",
        "contactless",
        "kontaktlos",
    }
)

DATE_KEYWORDS: Final[frozenset[str]] = frozenset({"datum", "date", "uhrzeit", "zeit"})

TECHNICAL_KEYWORDS: Final[frozenset[str]] = frozenset(
    {
        "tse",
        "seriennr",
        "tse-seriennr",
        "signatur",
        "signaturzähler",
        "prüfwert",
        "pruefwert",
        "transaktionsnr",
        "transaktion",
        "kassennr",
        "filiale",
        "bediener",
        "kasse",
        "terminal",
        "trace",
        "auth",
    }
)

# Blocked/meta words for filtering "non-item" lines. This list is intentionally
# broad and used as a heuristic signal (not a hard block) in the new pipeline.
BLOCKED_WORDS: Final[Sequence[str]] = (
    # Totals & taxes
    *sorted(TOTAL_KEYWORDS | SUBTOTAL_KEYWORDS | TAX_KEYWORDS),
    # Payments / change
    "change",
    "rückgeld",
    "rueckgeld",
    "wechselgeld",
    "gegeben",
    "zurück",
    "zurueck",
    *sorted(PAYMENT_KEYWORDS),
    # Receipt meta
    "bon",
    "beleg",
    "kassenbon",
    "quittung",
    "rechnung",
    "pfand",
    "leergut",
    *sorted(TECHNICAL_KEYWORDS | DATE_KEYWORDS),
    *sorted(DISCOUNT_KEYWORDS),
)

# ---------------------------------------------------------------------------
# OCR normalization helpers
# ---------------------------------------------------------------------------

# Confusable characters commonly produced by OCR. These are applied selectively
# (e.g. only to numeric-ish tokens) by the extractor.
# Expanded with more common OCR errors for better accuracy.
OCR_DIGIT_SUBSTITUTIONS: Final[Mapping[str, str]] = {
    # Zero confusables
    "O": "0",
    "o": "0",
    "Q": "0",
    "D": "0",
    # One confusables
    "I": "1",
    "l": "1",
    "|": "1",
    "!": "1",
    # Two confusables
    "Z": "2",
    "z": "2",
    # Three confusables
    "E": "3",
    # Five confusables
    "S": "5",
    "s": "5",
    # Six confusables
    "G": "6",
    "b": "6",
    # Eight confusables
    "B": "8",
    # Nine confusables
    "g": "9",
    "q": "9",
}

# Reverse confusables for text tokens (used by the normalizer).
# Keep this intentionally small and conservative.
OCR_ALPHA_SUBSTITUTIONS: Final[Mapping[str, str]] = {
    "0": "o",
    "1": "i",
    "5": "s",
    "8": "b",
}

# Used for store matching/fuzzy keys (rn↔m, vv↔w are common).
# Extended with more bigram and letter confusables.
OCR_TEXT_BIGRAM_SUBSTITUTIONS: Final[Mapping[str, str]] = {
    "rn": "m",
    "vv": "w",
    "ii": "n",
    "nn": "m",
    "cl": "d",
}

# Letter substitutions for text matching (avoid over-aggressive corrections)
OCR_LETTER_SUBSTITUTIONS: Final[Mapping[str, str]] = {
    "u": "v",
    "v": "u",
}

# Currency normalization (token-level).
CURRENCY_TOKENS_TO_SYMBOL: Final[Mapping[str, str]] = {
    "eur": "€",
    "euro": "€",
    "€": "€",
    "$": "$",
    "usd": "$",
    "chf": "CHF",
    "gbp": "£",
    "£": "£",
}

DEFAULT_CURRENCY_SYMBOL: Final[str] = "€"

# ---------------------------------------------------------------------------
# Validation constants for sanity checks
# ---------------------------------------------------------------------------

# Reasonable ranges for receipt amounts (in major currency units)
MIN_REASONABLE_TOTAL: Final[float] = 0.01
MAX_REASONABLE_TOTAL: Final[float] = 10000.0
MIN_REASONABLE_ITEM_PRICE: Final[float] = -500.0  # Allow discounts
MAX_REASONABLE_ITEM_PRICE: Final[float] = 1000.0

# Item name constraints
MIN_ITEM_NAME_LENGTH: Final[int] = 2
MAX_ITEM_NAME_LENGTH: Final[int] = 100

# Date validation
MIN_RECEIPT_YEAR: Final[int] = 2000
MAX_FUTURE_DAYS: Final[int] = 2  # Receipts should not be dated in the future

# Performance limits
MAX_LINES_TO_PROCESS: Final[int] = 6000
MAX_ITEMS_PER_RECEIPT: Final[int] = 500


# ---------------------------------------------------------------------------
# Regex patterns (kept for compatibility + compiled variants for performance)
# ---------------------------------------------------------------------------

# Broad money token matching. Parsing/validation happens in `extractor.py`.
#
# Supports:
# - 1.234,56 / 1,234.56 / 1234.56 / 1234,56
# - ,99 / .99
# - optional currency before/after
# - optional sign
MONEY_TOKEN_PATTERN: Final[str] = (
    r"(?P<sign>[+-])?\s*"
    r"(?:(?P<currency_prefix>€|\$|£|chf|gbp|usd|eur|euro)\s*)?"
    r"(?P<number>(?:\d{1,3}(?:[.,\s]\d{3})+[.,]\d{2}|\d+[.,]\d{2}|[.,]\d{2}|\d+))"
    r"\s*(?:(?P<currency_suffix>€|\$|£|chf|gbp|usd|eur|euro))?"
)

# Precompiled match-any money token.
RE_MONEY_TOKEN: Final[Pattern[str]] = re.compile(MONEY_TOKEN_PATTERN, re.IGNORECASE)

# Payment method patterns (compatibility: list of (pattern_str, label))
PAYMENT_PATTERNS: Final[Sequence[tuple[str, str]]] = (
    (r"\b(bar|cash|bargeld)\b", "Cash"),
    (r"\b(ec|ec-karte|maestro|girocard)\b", "EC"),
    (r"\b(kreditkarte|credit)\b", "Card"),
    (r"\b(visa)\b", "Visa"),
    (r"\b(mastercard|mc)\b", "Mastercard"),
    (r"\b(karte|card)\b", "Card"),
)

# Date patterns (compatibility: list[str])
DATE_PATTERNS: Final[Sequence[str]] = (
    r"\b(\d{2}[./]\d{2}[./]\d{4})\b",  # DD.MM.YYYY or DD/MM/YYYY
    r"\b(\d{1,2}[./]\d{1,2}[./]\d{2})\b",  # D.M.YY or DD.MM.YY
    r"\b(\d{4}-\d{2}-\d{2})\b",  # YYYY-MM-DD
    r"\b(\d{2}-\d{2}-\d{4})\b",  # DD-MM-YYYY
    r"\b(\d{1,2}-\d{1,2}-\d{2})\b",  # D-M-YY
)

# Total amount patterns (compatibility: list[str])
TOTAL_PATTERNS: Final[Sequence[str]] = (
    r"(?:total|summe|gesamt|zu zahlen|endsumme|betrag|amount|gesamtbetrag)[:\s]*([€$]?\s*\d+[.,]\d{2})",
    r"(?:total|summe|gesamt|zu zahlen|endsumme)[:\s]*\**\s*([€$]?\s*\d+[.,]\d{2})",
    r"([€$]\s*\d+[.,]\d{2})\s*$",
    r"(\d+[.,]\d{2})\s*(?:€|EUR|USD|\$)",
)

RECEIPT_NUMBER_PATTERN: Final[str] = (
    r"\b(?:receipt|beleg|bon|kassenbon|nr|nr\.|no|no\.|belegnr|beleg-nr|receipt no|bonnr|bon-nr|transaktionsnr|transaktion)"
    r"[.:\s-]*([A-Za-z0-9-]+)"
)

ITEM_PATTERN: Final[str] = r"^(.+?)\s+(\d+[.,]\d{2})\s*€?$"

QUANTITY_PATTERN: Final[str] = r"^\s*(\d+)\s*(?:[xX]|×)\b\s*"


def _compile(pattern: str, *, flags: int = re.IGNORECASE) -> Pattern[str]:
    return re.compile(pattern, flags)


@dataclass(frozen=True)
class PaymentRule:
    pattern: Pattern[str]
    label: str


PAYMENT_RULES: Final[Sequence[PaymentRule]] = tuple(
    PaymentRule(_compile(p), label) for p, label in PAYMENT_PATTERNS
)

RE_RECEIPT_NUMBER: Final[Pattern[str]] = _compile(RECEIPT_NUMBER_PATTERN)

RE_POSTAL_CITY: Final[Pattern[str]] = _compile(
    r"\b(?:D[-\s]?)?(?P<postal>\d{5})\s+(?P<city>[A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s.-]{2,})\b",
    flags=re.IGNORECASE,
)

RE_QUANTITY_PREFIX: Final[Pattern[str]] = _compile(QUANTITY_PATTERN)

RE_WEIGHT: Final[Pattern[str]] = _compile(
    r"(?P<qty>\d+(?:[.,]\d+)?)\s*(?P<unit>kg|g)\b", flags=re.IGNORECASE
)


def normalize_store_token(token: str) -> str:
    """
    Lightweight normalization used for store lexicon keys.

    The heavy text normalization lives in `extractor.py` so it can be configured
    without creating import cycles.
    """

    token = token.casefold().strip()
    token = re.sub(r"\s+", " ", token)
    token = token.replace("&", "and")
    for bigram, repl in OCR_TEXT_BIGRAM_SUBSTITUTIONS.items():
        token = token.replace(bigram, repl)
    return token


NORMALIZED_KNOWN_STORES: Final[tuple[str, ...]] = tuple(
    sorted({normalize_store_token(s) for s in KNOWN_STORES})
)


def iter_legal_suffix_tokens() -> Iterable[str]:
    for suffix in LEGAL_SUFFIXES:
        yield normalize_store_token(suffix)
