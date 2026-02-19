"""
Receipt data extraction from noisy OCR text.

This module is designed for German/European retail receipts and aims to be
production-grade (robust, explainable, testable) while staying dependency-free.

Pipeline architecture:
normalize → preprocess → classify → extract → validate → postprocess
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from difflib import SequenceMatcher
from enum import Enum
from typing import Iterable, Optional, Sequence

from constants import (
    BLOCKED_WORDS,
    CURRENCY_TOKENS_TO_SYMBOL,
    DATE_KEYWORDS,
    DEFAULT_CURRENCY_SYMBOL,
    DISCOUNT_KEYWORDS,
    KNOWN_STORES,
    MAX_FUTURE_DAYS,
    MAX_ITEMS_PER_RECEIPT,
    MAX_LINES_TO_PROCESS,
    MAX_REASONABLE_ITEM_PRICE,
    MAX_REASONABLE_TOTAL,
    MAX_ITEM_NAME_LENGTH,
    MIN_RECEIPT_YEAR,
    MIN_ITEM_NAME_LENGTH,
    MIN_REASONABLE_ITEM_PRICE,
    MIN_REASONABLE_TOTAL,
    NORMALIZED_KNOWN_STORES,
    OCR_ALPHA_SUBSTITUTIONS,
    OCR_DIGIT_SUBSTITUTIONS,
    OCR_TEXT_BIGRAM_SUBSTITUTIONS,
    PAYMENT_KEYWORDS,
    PAYMENT_RULES,
    RE_MONEY_TOKEN,
    RE_POSTAL_CITY,
    RE_QUANTITY_PREFIX,
    RE_RECEIPT_NUMBER,
    RE_WEIGHT,
    SUBTOTAL_KEYWORDS,
    TAX_KEYWORDS,
    TECHNICAL_KEYWORDS,
    TOTAL_KEYWORDS,
    iter_legal_suffix_tokens,
    normalize_store_token,
)

_MIN_TOTAL_AMOUNT = Decimal(str(MIN_REASONABLE_TOTAL))
_MAX_TOTAL_AMOUNT = Decimal(str(MAX_REASONABLE_TOTAL))
_MIN_ITEM_AMOUNT = Decimal(str(MIN_REASONABLE_ITEM_PRICE))
_MAX_ITEM_AMOUNT = Decimal(str(MAX_REASONABLE_ITEM_PRICE))

_RE_WHITESPACE = re.compile(r"[ \t\u00a0]+")
_RE_NON_WORD = re.compile(r"[^\w\s]+", re.UNICODE)
_RE_ADDRESS = re.compile(
    r"(?:straße|strasse|str\.|weg|platz|allee|ring|gasse|damm)\b",
    re.IGNORECASE,
)
_RE_PHONE = re.compile(r"\b(?:tel|telefon|phone)\b", re.IGNORECASE)
_RE_IBAN = re.compile(r"\b[a-z]{2}\d{2}[a-z0-9]{10,}\b", re.IGNORECASE)
_RE_LONG_CODE = re.compile(r"\b[A-Z0-9]{8,}\b")
_RE_COLON_CODE = re.compile(r":\s*[A-Z0-9]{5,}", re.IGNORECASE)
_RE_DATE_DMY = re.compile(
    r"\b(?P<d>\d{1,2})[./-](?P<m>\d{1,2})[./-](?P<y>\d{2,4})\b"
)
_RE_DATE_YMD = re.compile(r"\b(?P<y>\d{4})[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})\b")
_RE_WORD_TOKEN = re.compile(r"[a-z0-9äöüß]+")
_RE_RECEIPT_NUMBER_STRICT = re.compile(
    r"\b(?:"
    r"beleg(?:-?nr|-?nummer)?|"
    r"bon(?:-?nr)?|"
    r"kassenbon(?:-?nr)?|"
    r"transaktions(?:-?nr)?|"
    r"transaktion(?:s)?nr|"
    r"receipt(?:\s*(?:no|nr)|[-\s]*(?:no|nr))?"
    r")\b[.:\s-]*"
    r"(?P<id>[a-z0-9-]{3,})",
    re.IGNORECASE,
)
_RE_TAX_RATE = re.compile(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%")


@dataclass(frozen=True)
class KeywordSet:
    words: frozenset[str]
    phrases: tuple[str, ...]

    def matches(self, text: str, tokens: frozenset[str]) -> bool:
        if self.words and (self.words & tokens):
            return True
        return any(p in text for p in self.phrases)


def _build_keyword_set(keywords: Iterable[str]) -> KeywordSet:
    words: set[str] = set()
    phrases: list[str] = []
    for kw in keywords:
        kw_n = (kw or "").casefold().strip()
        if not kw_n:
            continue
        if re.fullmatch(r"[a-z0-9äöüß]+", kw_n):
            words.add(kw_n)
        else:
            phrases.append(kw_n)
    return KeywordSet(words=frozenset(words), phrases=tuple(sorted(set(phrases))))


_KW_TOTAL = _build_keyword_set(TOTAL_KEYWORDS)
_KW_SUBTOTAL = _build_keyword_set(SUBTOTAL_KEYWORDS)
_KW_TAX = _build_keyword_set(TAX_KEYWORDS)
_KW_DISCOUNT = _build_keyword_set(DISCOUNT_KEYWORDS)
_KW_PAYMENT = _build_keyword_set(PAYMENT_KEYWORDS)
_KW_DATE = _build_keyword_set(DATE_KEYWORDS)
_KW_TECHNICAL = _build_keyword_set(TECHNICAL_KEYWORDS)
_KW_BLOCKED = _build_keyword_set(BLOCKED_WORDS)

_STORE_CANONICAL_BY_NORM = {normalize_store_token(s): s for s in KNOWN_STORES}

_STORE_CONFUSABLES_TRANS = str.maketrans(
    {
        "0": "o",
        "1": "l",
        "5": "s",
        "8": "b",
        "i": "l",
        "l": "l",
        "o": "o",
        "s": "s",
        "b": "b",
    }
)


def _fold_store_confusables(text: str) -> str:
    # Used for store matching only; do not apply globally (would break keywords like "visa").
    return text.translate(_STORE_CONFUSABLES_TRANS)


class LineLabel(str, Enum):
    STORE_HEADER = "STORE_HEADER"
    ITEM = "ITEM"
    TOTAL = "TOTAL"
    PAYMENT = "PAYMENT"
    DATE = "DATE"
    META = "META"
    TECHNICAL = "TECHNICAL"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class NormalizationConfig:
    unicode_nfkc: bool = True
    casefold: bool = True
    normalize_whitespace: bool = True
    currency_normalization: bool = True
    ocr_numeric_corrections: bool = True
    ocr_bigram_corrections_for_matching: bool = True
    strip_accents_for_matching: bool = True


@dataclass(frozen=True)
class ExtractionConfig:
    normalization: NormalizationConfig = NormalizationConfig()
    default_currency_symbol: str = DEFAULT_CURRENCY_SYMBOL
    prefer_day_first: bool = True  # German receipts
    min_year: int = MIN_RECEIPT_YEAR
    max_future_days: int = MAX_FUTURE_DAYS
    store_fuzzy_threshold: float = 0.82
    store_min_score: float = 0.55
    item_min_confidence: float = 0.55
    total_min_score: float = 0.6
    max_lines: int = MAX_LINES_TO_PROCESS
    max_items_per_receipt: int = MAX_ITEMS_PER_RECEIPT
    # Note: MIN/MAX_ITEM_NAME_LENGTH and MIN/MAX_REASONABLE_* constants
    # are used directly in extraction functions rather than via config


@dataclass(frozen=True)
class Money:
    amount: Decimal
    currency: str


@dataclass(frozen=True)
class MoneyToken:
    raw: str
    money: Money
    start: int
    end: int


@dataclass(frozen=True)
class LineClassification:
    label: LineLabel
    confidence: float


@dataclass(frozen=True)
class ReceiptLine:
    index: int
    raw: str
    norm: str
    money: tuple[MoneyToken, ...]
    dates: tuple[date, ...]
    classification: LineClassification


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _normalize_currency_token(token: str) -> str:
    if not token:
        return ""
    mapped = CURRENCY_TOKENS_TO_SYMBOL.get(token.casefold(), token)
    return mapped


def _is_numericish_token(token: str) -> bool:
    if any(ch.isdigit() for ch in token):
        return True
    if any(sym in token for sym in ("€", "$", "£")):
        return True
    # Leading decimals without a leading zero: ",99" / ".99"
    return bool(re.match(r"^[.,]\d{1,3}$", token))


class TextNormalizer:
    def __init__(self, config: NormalizationConfig) -> None:
        self._config = config
        self._digit_trans = str.maketrans(OCR_DIGIT_SUBSTITUTIONS)
        self._alpha_trans = str.maketrans(OCR_ALPHA_SUBSTITUTIONS)

    def normalize_text(self, text: str) -> str:
        if self._config.unicode_nfkc:
            text = unicodedata.normalize("NFKC", text)
        # Preserve line breaks, normalize everything else.
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if self._config.casefold:
            text = text.casefold()
        if self._config.normalize_whitespace:
            text = "\n".join(_RE_WHITESPACE.sub(" ", ln).strip() for ln in text.split("\n"))
        if self._config.currency_normalization:
            text = self._normalize_currency_symbols(text)
        if self._config.ocr_numeric_corrections:
            text = self._correct_ocr_noise(text)
        return text

    def _normalize_currency_symbols(self, text: str) -> str:
        # Replace standalone tokens only (avoid touching words like "euroshop").
        for token, symbol in CURRENCY_TOKENS_TO_SYMBOL.items():
            if token == symbol:
                continue
            text = re.sub(rf"\b{re.escape(token)}\b", symbol.casefold(), text, flags=re.IGNORECASE)
        return text

    def _correct_ocr_noise(self, text: str) -> str:
        """
        Correct common OCR confusables in a token-aware way.

        - Numeric-ish tokens: map letters that look like digits (O→0, l→1, …)
        - Text-ish tokens: map digits that look like letters (8→b, 0→o, …)
        """

        parts: list[str] = []
        for ln in text.split("\n"):
            tokens = ln.split(" ")
            fixed: list[str] = []
            for t in tokens:
                if not t:
                    continue
                letters = sum(ch.isalpha() for ch in t)
                digits = sum(ch.isdigit() for ch in t)

                if digits and letters:
                    # Mixed tokens are common in OCR (e.g., "8AR", "2O.0l.2026").
                    # But long mixed tokens are often identifiers (TSE ids, receipt numbers).
                    if len(t) >= 6 and letters >= 2 and digits >= 2 and re.fullmatch(r"[a-z0-9-]+", t):
                        fixed.append(t)
                        continue
                    if letters >= digits:
                        fixed.append(t.translate(self._alpha_trans))
                    else:
                        fixed.append(self._translate_numeric_token(t))
                    continue

                if _is_numericish_token(t):
                    fixed.append(self._translate_numeric_token(t))
                else:
                    fixed.append(t)
            parts.append(" ".join(fixed))
        return "\n".join(parts)

    def _translate_numeric_token(self, token: str) -> str:
        # Preserve unit suffixes like "kg", "g", "l" to avoid turning them into digits.
        m = re.match(r"^(?P<core>.*?)(?P<suffix>[a-z]{1,3})$", token)
        if m and any(ch.isdigit() for ch in m.group("core")):
            core = m.group("core").translate(self._digit_trans)
            return core + m.group("suffix")
        return token.translate(self._digit_trans)

    def build_match_key(self, text: str) -> str:
        """
        Extra normalization used for fuzzy matching (store detection).

        This is intentionally more aggressive than `normalize_text`.
        """

        key = text
        if self._config.strip_accents_for_matching:
            key = _strip_accents(key)
        key = _RE_NON_WORD.sub(" ", key)
        key = _RE_WHITESPACE.sub(" ", key).strip()
        if self._config.ocr_bigram_corrections_for_matching:
            for bigram, repl in OCR_TEXT_BIGRAM_SUBSTITUTIONS.items():
                key = key.replace(bigram, repl)
        return key


def _parse_decimal_number(
    token: str, *, allow_implicit_cents: bool, max_decimals: int = 2
) -> Optional[Decimal]:
    raw = token.strip().replace(" ", "")
    if raw.startswith((",", ".")):
        raw = f"0{raw}"

    if raw.count(",") and raw.count("."):
        last_comma = raw.rfind(",")
        last_dot = raw.rfind(".")
        decimal_sep = "," if last_comma > last_dot else "."
        thousand_sep = "." if decimal_sep == "," else ","
        raw = raw.replace(thousand_sep, "").replace(decimal_sep, ".")
    elif raw.count(","):
        if raw.count(",") > 1:
            # Treat all but the last comma as thousand separators.
            head, tail = raw.rsplit(",", 1)
            raw = head.replace(",", "") + "." + tail
        else:
            head, tail = raw.split(",", 1)
            if len(tail) == 2:
                raw = head + "." + tail
            else:
                # Could be a thousands separator; fall back to removing commas.
                raw = raw.replace(",", "")
    elif raw.count("."):
        if raw.count(".") > 1:
            head, tail = raw.rsplit(".", 1)
            raw = head.replace(".", "") + "." + tail
        else:
            head, tail = raw.split(".", 1)
            if len(tail) == 2:
                raw = head + "." + tail
            else:
                raw = raw.replace(".", "")
    else:
        if allow_implicit_cents and raw.isdigit() and 3 <= len(raw) <= 6:
            raw = raw[:-2] + "." + raw[-2:]

    try:
        dec = Decimal(raw)
    except InvalidOperation:
        return None

    # Normalize to currency scale by default.
    quant = Decimal(10) ** (-max_decimals)
    return dec.quantize(quant, rounding=ROUND_HALF_UP)


def _extract_money_tokens(line: str, *, default_currency: str) -> tuple[MoneyToken, ...]:
    tokens: list[MoneyToken] = []
    date_spans = [(m.start(), m.end()) for m in _RE_DATE_DMY.finditer(line)]
    date_spans.extend((m.start(), m.end()) for m in _RE_DATE_YMD.finditer(line))

    def overlaps_date_span(start: int, end: int) -> bool:
        return any(start < ds_end and end > ds_start for ds_start, ds_end in date_spans)

    for m in RE_MONEY_TOKEN.finditer(line):
        if date_spans and overlaps_date_span(m.start(), m.end()):
            continue
        number = m.group("number") or ""
        if not number:
            continue
        has_currency = bool(m.group("currency_prefix") or m.group("currency_suffix"))
        has_decimal_sep = ("," in number) or ("." in number)
        # Guardrail: bare integers match too many things (postal codes, ids, etc).
        if not has_currency and not has_decimal_sep:
            continue
        currency_raw = m.group("currency_prefix") or m.group("currency_suffix") or default_currency
        currency = _normalize_currency_token(currency_raw) or default_currency
        sign = m.group("sign") or ""
        allow_implicit = has_currency
        amount = _parse_decimal_number(number, allow_implicit_cents=allow_implicit)
        if amount is None:
            continue
        if sign == "-":
            amount = -amount
        tokens.append(MoneyToken(raw=m.group(0), money=Money(amount=amount, currency=currency), start=m.start(), end=m.end()))
    return tuple(tokens)


def _parse_two_digit_year(year: int) -> int:
    # Receipts are overwhelmingly 20xx. Keep a conservative pivot.
    return 2000 + year if year <= 79 else 1900 + year


def _extract_dates(line: str, *, config: ExtractionConfig) -> tuple[date, ...]:
    candidates: list[date] = []
    today = date.today()
    max_date = today + timedelta(days=config.max_future_days)

    def add_candidate(d: int, m: int, y: int) -> None:
        if y < 100:
            y = _parse_two_digit_year(y)
        if y < config.min_year:
            return
        try:
            dt = date(y, m, d)
        except ValueError:
            return
        if dt > max_date:
            return
        candidates.append(dt)

    for match in _RE_DATE_YMD.finditer(line):
        add_candidate(int(match.group("d")), int(match.group("m")), int(match.group("y")))

    for match in _RE_DATE_DMY.finditer(line):
        d = int(match.group("d"))
        m = int(match.group("m"))
        y = int(match.group("y"))
        if config.prefer_day_first:
            add_candidate(d, m, y)
        else:
            # If ambiguous, prefer month-first. If unambiguous (one part > 12), use that.
            if d > 12 and m <= 12:
                add_candidate(d, m, y)
            elif m > 12 and d <= 12:
                add_candidate(m, d, y)
            else:
                add_candidate(m, d, y)

    # Deduplicate, keep stable ordering.
    seen: set[date] = set()
    out: list[date] = []
    for dt in candidates:
        if dt in seen:
            continue
        seen.add(dt)
        out.append(dt)
    return tuple(out)

def _tokenize(text: str) -> frozenset[str]:
    return frozenset(_RE_WORD_TOKEN.findall(text))


def _looks_technical(line: str) -> bool:
    if _RE_LONG_CODE.search(line):
        return True
    if _RE_COLON_CODE.search(line):
        return True
    if _KW_TECHNICAL.matches(line, _tokenize(line)):
        return True
    return False


def _classify_lines(
    norm_lines: Sequence[str],
    raw_lines: Sequence[str],
    *,
    config: ExtractionConfig,
    normalizer: TextNormalizer,
) -> list[ReceiptLine]:
    total = max(1, len(norm_lines))
    out: list[ReceiptLine] = []

    store_lexicon = tuple(NORMALIZED_KNOWN_STORES)
    store_pairs = tuple((s, _fold_store_confusables(s)) for s in store_lexicon)
    legal_suffixes = tuple(iter_legal_suffix_tokens())
    legal_suffixes_folded = tuple(_fold_store_confusables(s) for s in legal_suffixes)

    for idx, (raw, norm) in enumerate(zip(raw_lines, norm_lines)):
        pos = idx / max(1, total - 1)
        tokens = _tokenize(norm)
        money = _extract_money_tokens(norm, default_currency=config.default_currency_symbol)
        dates = _extract_dates(norm, config=config)

        # Precompute basic signals.
        has_money = bool(money)
        has_date = bool(dates)
        has_letters = bool(re.search(r"[a-zäöüß]", norm))
        has_digits = any(ch.isdigit() for ch in norm)
        technical = _looks_technical(norm)

        total_kw = _KW_TOTAL.matches(norm, tokens)
        subtotal_kw = _KW_SUBTOTAL.matches(norm, tokens)
        tax_kw = _KW_TAX.matches(norm, tokens)
        payment_kw = _KW_PAYMENT.matches(norm, tokens)
        discount_kw = _KW_DISCOUNT.matches(norm, tokens)
        date_kw = _KW_DATE.matches(norm, tokens)
        meta_kw = _KW_BLOCKED.matches(norm, tokens)

        # Store match signal (cheap).
        store_ratio = 0.0
        if idx <= 20 and has_letters:
            key = normalizer.build_match_key(norm)
            key_folded = _fold_store_confusables(key)
            key_no_suffix = " ".join(w for w in key_folded.split() if w not in legal_suffixes_folded)
            for _store_norm, store in store_pairs:
                if not store:
                    continue
                if store in key_no_suffix:
                    store_ratio = 1.0
                    break
                # Compare against compact forms for OCR "missing space" cases.
                compact_line = re.sub(r"[^a-z0-9]+", "", key_no_suffix)
                compact_store = re.sub(r"[^a-z0-9]+", "", store)
                if compact_store and compact_store in compact_line:
                    store_ratio = max(store_ratio, 0.98)
                    continue
                # Token-level fuzzy.
                for tok in key_no_suffix.split():
                    if len(tok) < 3 or len(store) < 3:
                        continue
                    store_ratio = max(store_ratio, SequenceMatcher(None, tok, store).ratio())

        # Score-based classification with position features.
        scores: dict[LineLabel, float] = {LineLabel.UNKNOWN: 0.05}

        if technical:
            scores[LineLabel.TECHNICAL] = 0.95

        if has_date:
            scores[LineLabel.DATE] = max(scores.get(LineLabel.DATE, 0.0), 0.75 + (0.1 if date_kw else 0.0))

        if payment_kw:
            scores[LineLabel.PAYMENT] = 0.6 + (0.2 if has_money else 0.0) + (0.1 if pos > 0.6 else 0.0)

        if total_kw:
            scores[LineLabel.TOTAL] = 0.65 + (0.2 if has_money else 0.0) + (0.15 if pos > 0.65 else 0.0)

        if has_money and not technical:
            # Items are usually mid-receipt; totals are bottom-heavy.
            mid_weight = 1.0 - abs(pos - 0.5) * 2.0  # 1 in middle, 0 at extremes
            scores[LineLabel.ITEM] = max(scores.get(LineLabel.ITEM, 0.0), 0.35 + 0.25 * _clamp01(mid_weight))
            total_base = 0.25 + 0.35 * _clamp01(pos)
            if (
                has_letters
                and pos < 0.7
                and not total_kw
                and not subtotal_kw
                and not tax_kw
                and not payment_kw
            ):
                total_base -= 0.15
            scores[LineLabel.TOTAL] = max(scores.get(LineLabel.TOTAL, 0.0), total_base)
            if has_letters and not total_kw and not subtotal_kw and not tax_kw and not payment_kw:
                scores[LineLabel.ITEM] = max(scores.get(LineLabel.ITEM, 0.0), scores.get(LineLabel.ITEM, 0.0) + 0.15)

        if idx <= 20 and has_letters and not technical:
            top_boost = 0.25 * (1.0 - pos)
            scores[LineLabel.STORE_HEADER] = 0.25 + top_boost
            if store_ratio >= config.store_fuzzy_threshold:
                scores[LineLabel.STORE_HEADER] = max(scores[LineLabel.STORE_HEADER], 0.55 + 0.4 * store_ratio)
            if has_money or has_date:
                scores[LineLabel.STORE_HEADER] -= 0.25
            if meta_kw or tax_kw or subtotal_kw:
                scores[LineLabel.STORE_HEADER] -= 0.15

        if meta_kw or tax_kw or subtotal_kw or discount_kw:
            scores[LineLabel.META] = max(scores.get(LineLabel.META, 0.0), 0.55 + (0.1 if pos < 0.3 else 0.0))

        # Penalize unlikely mixes.
        if total_kw or subtotal_kw or tax_kw:
            scores[LineLabel.ITEM] = scores.get(LineLabel.ITEM, 0.0) - 0.35
        if payment_kw:
            scores[LineLabel.ITEM] = scores.get(LineLabel.ITEM, 0.0) - 0.15
        if has_digits and not has_letters and has_money:
            # "amount-only" lines are usually totals/payments, not items.
            scores[LineLabel.ITEM] = scores.get(LineLabel.ITEM, 0.0) - 0.3

        # Select best label.
        sorted_scores = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        best_label, best_score = sorted_scores[0]
        second = sorted_scores[1][1] if len(sorted_scores) > 1 else 0.0
        confidence = _clamp01(best_score - 0.35 * max(0.0, second))

        out.append(
            ReceiptLine(
                index=idx,
                raw=raw,
                norm=norm,
                money=money,
                dates=dates,
                classification=LineClassification(label=best_label, confidence=confidence),
            )
        )

    return out


def _format_money(money: Money) -> str:
    # German-friendly formatting: thousands "." and decimals ",".
    q = money.amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if q.is_signed() else ""
    q_abs = -q if q.is_signed() else q
    whole, frac = f"{q_abs:.2f}".split(".")
    whole_with_sep = ""
    for i, ch in enumerate(reversed(whole)):
        if i and i % 3 == 0:
            whole_with_sep = "." + whole_with_sep
        whole_with_sep = ch + whole_with_sep
    return f"{sign}{whole_with_sep},{frac} {money.currency}".strip()


def _score_store_candidate(
    line: ReceiptLine,
    *,
    normalizer: TextNormalizer,
    config: ExtractionConfig,
    store_lexicon: Sequence[str],
    legal_suffixes: Sequence[str],
    total_lines: int,
) -> tuple[float, Optional[str], Optional[str], float]:
    idx = line.index
    pos = idx / max(1, total_lines - 1)
    if idx > 25:
        return 0.0, None, None, 0.0

    key = normalizer.build_match_key(line.norm)
    if not key or not re.search(r"[a-zäöüß]", key):
        return 0.0, None, None, 0.0

    # Strip legal suffix tokens from the end to produce a cleaner header.
    words = key.split()
    while words and words[-1] in legal_suffixes:
        words.pop()
    clean_key = " ".join(words).strip()

    has_money = bool(line.money)
    has_date = bool(line.dates)
    technical = line.classification.label == LineLabel.TECHNICAL

    if technical or has_money or has_date:
        # Hard guardrails; these are almost never the store header itself.
        penalty = 0.35 if (has_money or has_date) else 0.0
        return max(0.0, 0.15 - penalty), None, None, 0.0

    # Base score from position (top-heavy).
    score = 0.35 + 0.35 * (1.0 - pos)

    # Penalize address/contact lines.
    if _RE_ADDRESS.search(clean_key) or RE_POSTAL_CITY.search(clean_key) or _RE_PHONE.search(clean_key) or _RE_IBAN.search(clean_key):
        score -= 0.25

    # Penalize meta-heavy lines (tax, totals, etc).
    if _KW_BLOCKED.matches(clean_key, _tokenize(clean_key)):
        score -= 0.15

    # Store lexicon match: substring + fuzzy (with confusable folding).
    best_ratio = 0.0
    best_store: Optional[str] = None
    match_key = _fold_store_confusables(clean_key)
    compact_line = re.sub(r"[^a-z0-9]+", "", match_key)
    for store_norm in store_lexicon:
        store = _fold_store_confusables(store_norm)
        if store in match_key:
            best_ratio = 1.0
            best_store = store_norm
            break
        compact_store = re.sub(r"[^a-z0-9]+", "", store)
        if compact_store and compact_store in compact_line:
            best_ratio = max(best_ratio, 0.98)
            best_store = store_norm
            continue
        for tok in match_key.split():
            if len(tok) < 3 or len(store) < 3:
                continue
            ratio = SequenceMatcher(None, tok, store).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_store = store_norm

    if best_ratio >= config.store_fuzzy_threshold:
        score += 0.55 * best_ratio
    else:
        score += 0.15 * best_ratio

    return score, clean_key if clean_key else None, best_store, best_ratio


def _extract_store(lines: Sequence[ReceiptLine], *, config: ExtractionConfig, normalizer: TextNormalizer) -> Optional[str]:
    store_lexicon = tuple(NORMALIZED_KNOWN_STORES)
    legal_suffixes = tuple(iter_legal_suffix_tokens())
    best_score = 0.0
    best: Optional[str] = None
    best_store: Optional[str] = None
    best_ratio: float = 0.0
    total_lines = len(lines)

    for ln in lines[:30]:
        score, candidate, store_norm, ratio = _score_store_candidate(
            ln,
            normalizer=normalizer,
            config=config,
            store_lexicon=store_lexicon,
            legal_suffixes=legal_suffixes,
            total_lines=total_lines,
        )
        if candidate and score > best_score:
            best_score, best, best_store, best_ratio = score, candidate, store_norm, ratio

    if best_score < config.store_min_score:
        return None
    if best_store and best_ratio >= config.store_fuzzy_threshold:
        return _STORE_CANONICAL_BY_NORM.get(best_store, best_store)
    return best


def _extract_location(lines: Sequence[ReceiptLine]) -> tuple[Optional[str], Optional[str]]:
    # Prefer early matches (addresses are near the top).
    for idx, ln in enumerate(lines[:40]):
        m = RE_POSTAL_CITY.search(ln.raw) or RE_POSTAL_CITY.search(ln.norm)
        if not m:
            continue
        postal = m.group("postal")
        city = m.group("city").strip()
        # Try to join the street line above.
        street = None
        if idx > 0 and _RE_ADDRESS.search(lines[idx - 1].norm):
            street = lines[idx - 1].raw.strip()
        location = f"{street}, {postal} {city}".strip(", ") if street else f"{postal} {city}".strip()
        return location, postal
    return None, None


def _extract_receipt_number(lines: Sequence[ReceiptLine]) -> Optional[str]:
    best: Optional[str] = None
    best_score = 0.0
    stopwords = {"nr", "no", "beleg", "bon", "receipt", "id"}

    for ln in lines:
        candidates: list[tuple[str, float]] = []

        m_strict = _RE_RECEIPT_NUMBER_STRICT.search(ln.norm)
        if m_strict:
            cand = (m_strict.group("id") or "").strip()
            candidates.append((cand, 0.85))

        m = RE_RECEIPT_NUMBER.search(ln.norm)
        if m:
            cand = (m.group(1) or "").strip()
            candidates.append((cand, 0.65))

        for candidate, base in candidates:
            if not candidate:
                continue
            if candidate.casefold() in stopwords:
                continue
            if not re.search(r"\d", candidate):
                continue
            score = base
            if ln.index < 25:
                score += 0.05
            if len(candidate) >= 8:
                score += 0.05
            if ln.classification.label in {LineLabel.TECHNICAL, LineLabel.META}:
                score += 0.05
            if score > best_score:
                best_score, best = score, candidate

    return best


def _extract_payment_method(lines: Sequence[ReceiptLine]) -> Optional[str]:
    best = None
    best_score = 0.0
    for ln in lines:
        for rule in PAYMENT_RULES:
            if rule.pattern.search(ln.norm):
                score = 0.6 + (0.1 if ln.index / max(1, len(lines) - 1) > 0.6 else 0.0)
                if ln.classification.label == LineLabel.PAYMENT:
                    score += 0.15
                if score > best_score:
                    best_score, best = score, rule.label
    return best


def _score_date_candidate(ln: ReceiptLine, dt: date, *, total_lines: int) -> float:
    pos = ln.index / max(1, total_lines - 1)
    score = 0.55
    if ln.classification.label == LineLabel.DATE:
        score += 0.25 * ln.classification.confidence
    if _KW_DATE.matches(ln.norm, _tokenize(ln.norm)):
        score += 0.1
    # Receipts usually print the date in the upper half.
    score += 0.15 * (1.0 - pos)
    # Prefer "today-ish" dates slightly.
    days_ago = (date.today() - dt).days
    if 0 <= days_ago <= 7:
        score += 0.05
    return score


def _extract_best_date(lines: Sequence[ReceiptLine]) -> Optional[date]:
    best_dt: Optional[date] = None
    best_score = 0.0
    total_lines = len(lines)
    for ln in lines:
        for dt in ln.dates:
            score = _score_date_candidate(ln, dt, total_lines=total_lines)
            if score > best_score:
                best_score, best_dt = score, dt
    return best_dt


def _score_total_candidate(ln: ReceiptLine, *, total_lines: int) -> float:
    if not ln.money:
        return 0.0
    pos = ln.index / max(1, total_lines - 1)
    score = 0.2 + 0.55 * _clamp01(pos)
    if ln.classification.label == LineLabel.TOTAL:
        score += 0.25 * ln.classification.confidence
    tokens = _tokenize(ln.norm)
    if _KW_TOTAL.matches(ln.norm, tokens):
        score += 0.35
    if _KW_SUBTOTAL.matches(ln.norm, tokens) or _KW_TAX.matches(ln.norm, tokens):
        score -= 0.25
    if _KW_DISCOUNT.matches(ln.norm, tokens):
        score -= 0.15
    if ln.classification.label == LineLabel.ITEM:
        score -= 0.25
    if ln.classification.label == LineLabel.PAYMENT or _KW_PAYMENT.matches(ln.norm, tokens):
        score -= 0.25
    if not re.search(r"[a-zäöüß]", ln.norm):
        score += 0.2
    return score


def _total_closeness_boost(amount: Decimal, expected: Decimal) -> float:
    diff = (amount - expected).copy_abs()
    if diff <= Decimal("0.02"):
        return 0.35
    if diff <= Decimal("0.05"):
        return 0.25
    if diff <= Decimal("0.10"):
        return 0.15
    if diff <= max(Decimal("0.25"), expected.copy_abs() * Decimal("0.01")):
        return 0.05
    return 0.0


def _extract_total_money(
    lines: Sequence[ReceiptLine],
    *,
    config: ExtractionConfig,
    expected_total: Optional[Decimal] = None,
) -> Optional[Money]:
    total_lines = len(lines)

    # Two-line patterns: "SUMME" followed by "12,34 €".
    for i in range(len(lines) - 2, -1, -1):
        ln = lines[i]
        if _KW_TOTAL.matches(ln.norm, _tokenize(ln.norm)) and not ln.money:
            nxt = lines[i + 1]
            if nxt.money and not re.search(r"[a-zäöüß]", nxt.norm):
                money = nxt.money[-1].money
                if expected_total is None:
                    return money
                if _total_closeness_boost(money.amount, expected_total) >= 0.15:
                    return money

    candidates: list[tuple[float, Money]] = []
    for ln in reversed(lines):
        score = _score_total_candidate(ln, total_lines=total_lines)
        if score <= 0.0:
            continue
        candidate_money = ln.money[-1].money
        if expected_total is not None:
            score += _total_closeness_boost(candidate_money.amount, expected_total)
        candidates.append((score, candidate_money))
        if len(candidates) >= 12:
            break

    if not candidates:
        return None

    candidates.sort(key=lambda t: t[0], reverse=True)
    best_score, best_money = candidates[0]
    if best_score < config.total_min_score:
        return None
    return best_money


def _parse_tax_rate(value: str) -> Optional[float]:
    if not value:
        return None
    raw = value.replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _extract_taxes(lines: Sequence[ReceiptLine]) -> list[dict]:
    taxes: list[dict] = []
    for ln in lines:
        tokens = _tokenize(ln.norm)
        if not _KW_TAX.matches(ln.norm, tokens):
            continue
        if not ln.money:
            continue
        rate_match = _RE_TAX_RATE.search(ln.raw) or _RE_TAX_RATE.search(ln.norm)
        tax_rate = _parse_tax_rate(rate_match.group(1)) if rate_match else None
        if tax_rate is None:
            continue

        monies = [t.money for t in ln.money]
        if not monies:
            continue
        tax_amount = monies[-1].amount
        taxable_amount = monies[0].amount if len(monies) >= 2 else None

        taxes.append(
            {
                "tax_rate": float(tax_rate),
                "tax_amount": float(tax_amount),
                "taxable_amount": float(taxable_amount) if taxable_amount is not None else None,
                "currency": monies[-1].currency,
            }
        )
    return taxes


def _merge_multiline_item_candidates(lines: Sequence[ReceiptLine]) -> list[ReceiptLine]:
    merged: list[ReceiptLine] = []
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.money:
            merged.append(ln)
            i += 1
            continue

        # Candidate: name-only line followed by amount-only line.
        if (
            i + 1 < len(lines)
            and re.search(r"[a-zäöüß]", ln.norm)
            and not ln.money
            and lines[i + 1].money
            and not re.search(r"[a-zäöüß]", lines[i + 1].norm)
        ):
            nxt = lines[i + 1]
            raw = f"{ln.raw} {nxt.raw}".strip()
            norm = f"{ln.norm} {nxt.norm}".strip()
            merged.append(
                ReceiptLine(
                    index=ln.index,
                    raw=raw,
                    norm=norm,
                    money=nxt.money,
                    dates=ln.dates or nxt.dates,
                    classification=ln.classification,
                )
            )
            i += 2
            continue

        merged.append(ln)
        i += 1
    return merged


def _extract_items(lines: Sequence[ReceiptLine], *, config: ExtractionConfig) -> list[dict]:
    items: list[dict] = []
    seen: set[tuple[str, str, float]] = set()

    merged_lines = _merge_multiline_item_candidates(lines)

    for ln in merged_lines:
        if ln.classification.label in {LineLabel.TOTAL, LineLabel.PAYMENT, LineLabel.TECHNICAL}:
            continue
        if not ln.money:
            continue
        tokens = _tokenize(ln.norm)
        is_discount_signal = _KW_DISCOUNT.matches(ln.norm, tokens) or any(
            t.money.amount < 0 for t in ln.money
        )
        if (
            ln.classification.label == LineLabel.ITEM
            and ln.classification.confidence < config.item_min_confidence
            and not is_discount_signal
        ):
            continue
        if _KW_TOTAL.matches(ln.norm, tokens) or _KW_SUBTOTAL.matches(ln.norm, tokens):
            continue
        if _KW_TAX.matches(ln.norm, tokens) and not re.search(r"[a-zäöüß]", ln.norm):
            continue

        # Quantity (e.g. "2x").
        quantity: float = 1.0
        clean_raw = ln.raw.strip()
        m_qty = RE_QUANTITY_PREFIX.match(clean_raw)
        if m_qty:
            try:
                quantity = float(int(m_qty.group(1)))
            except ValueError:
                quantity = 1.0
            clean_raw = clean_raw[m_qty.end() :].strip()

        # Weight-based items (e.g. "0,512 kg").
        unit: Optional[str] = None
        m_w = RE_WEIGHT.search(ln.norm)
        weight_qty_dec: Optional[Decimal] = None
        if m_w:
            qty_raw = m_w.group("qty").replace(",", ".")
            try:
                weight_qty_dec = Decimal(qty_raw)
                quantity = float(weight_qty_dec)
                unit = m_w.group("unit").lower()
            except (InvalidOperation, ValueError):
                pass

        monies = [t.money for t in ln.money]
        # If the line contains a weight token like "0,50 kg", OCR often also makes
        # that number look like a price. Drop it from money candidates.
        if weight_qty_dec is not None and len(monies) >= 2:
            weight_q = weight_qty_dec.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if monies[0].amount == weight_q:
                monies = monies[1:]
        line_total = monies[-1]
        unit_price: Optional[Money] = monies[-2] if len(monies) >= 2 else None

        # Discounts are often printed as negative or with discount keywords.
        is_discount = line_total.amount < 0 or _KW_DISCOUNT.matches(ln.norm, tokens)
        if is_discount and line_total.amount > 0:
            line_total = Money(amount=-line_total.amount, currency=line_total.currency)

        # Name cleanup: remove trailing money token raw strings.
        clean = clean_raw
        for tok in ln.money:
            clean = clean.replace(tok.raw, " ")
        clean = _RE_WHITESPACE.sub(" ", clean).strip(" -:\t")

        if len(clean) < 2 or not re.search(r"[A-Za-zÄÖÜäöüß]", clean):
            continue
        if not (MIN_ITEM_NAME_LENGTH <= len(clean) <= MAX_ITEM_NAME_LENGTH):
            continue
        if _KW_BLOCKED.matches(clean.casefold(), _tokenize(clean.casefold())) and not is_discount:
            continue
        if quantity <= 0:
            continue
        if not (_MIN_ITEM_AMOUNT <= line_total.amount <= _MAX_ITEM_AMOUNT):
            continue

        price_str = _format_money(line_total)
        key = (clean.casefold(), price_str, float(quantity))
        if key in seen:
            continue
        seen.add(key)

        item: dict = {
            "name": clean,
            "price": price_str,
            "quantity": quantity,
            "line_total_amount": float(line_total.amount),
            "currency": line_total.currency,
        }
        if unit:
            item["unit"] = unit
        if unit_price:
            item["unit_price"] = _format_money(unit_price)
            item["unit_price_amount"] = float(unit_price.amount)
        if is_discount:
            item["is_discount"] = True
        items.append(item)
        if len(items) >= config.max_items_per_receipt:
            break

    return items


def _sum_item_totals(items: Sequence[dict]) -> Optional[Decimal]:
    total = Decimal("0")
    has_any = False
    for it in items:
        amount_val = it.get("line_total_amount")
        if amount_val is not None:
            try:
                total += Decimal(str(amount_val)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                has_any = True
                continue
            except InvalidOperation:
                pass

        price = it.get("price") or ""
        m = RE_MONEY_TOKEN.search(str(price))
        if not m:
            continue
        number = m.group("number") or ""
        if not number:
            continue
        amount = _parse_decimal_number(number, allow_implicit_cents=False)
        if amount is None:
            continue
        if (m.group("sign") or "") == "-":
            amount = -amount
        total += amount
        has_any = True
    return total if has_any else None


class ReceiptExtractor:
    def __init__(self, config: ExtractionConfig = ExtractionConfig()) -> None:
        self._config = config
        self._normalizer = TextNormalizer(config.normalization)

    def extract(self, text: str) -> dict:
        norm_text = self._normalizer.normalize_text(text or "")
        raw_lines, norm_lines = self._preprocess_lines(text or "", norm_text)
        lines = _classify_lines(
            norm_lines,
            raw_lines,
            config=self._config,
            normalizer=self._normalizer,
        )

        store_name = _extract_store(lines, config=self._config, normalizer=self._normalizer)
        store_location, postal_code = _extract_location(lines)
        receipt_number = _extract_receipt_number(lines)
        payment_method = _extract_payment_method(lines)
        dt = _extract_best_date(lines)
        items = _extract_items(lines, config=self._config)
        taxes = _extract_taxes(lines)

        items_sum = _sum_item_totals(items)
        total_money = _extract_total_money(lines, config=self._config, expected_total=items_sum)
        if total_money and not (_MIN_TOTAL_AMOUNT <= total_money.amount <= _MAX_TOTAL_AMOUNT):
            total_money = None

        result: dict = {
            "store_name": store_name,
            "store_location": store_location,
            "postal_code": postal_code,
            "receipt_number": receipt_number,
            "payment_method": payment_method,
            "date": dt.isoformat() if dt else None,
            "total": _format_money(total_money) if total_money else None,
            "items": items,
            "raw_text": text,
        }
        if taxes:
            result["taxes"] = taxes

        if items_sum is not None:
            result["items_sum"] = float(items_sum)
        if total_money is not None:
            result["currency"] = total_money.currency

        return result

    def _preprocess_lines(self, raw_text: str, norm_text: str) -> tuple[list[str], list[str]]:
        raw_lines_all = (raw_text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
        norm_lines_all = (norm_text or "").split("\n")
        raw_lines: list[str] = []
        norm_lines: list[str] = []

        for raw, norm in zip(raw_lines_all, norm_lines_all):
            raw_s = raw.strip()
            norm_s = norm.strip()
            if not raw_s or not norm_s:
                continue
            raw_lines.append(raw_s)
            norm_lines.append(norm_s)
            if len(raw_lines) >= self._config.max_lines:
                break

        return raw_lines, norm_lines


_DEFAULT_EXTRACTOR = ReceiptExtractor()


def extract_receipt_data(text: str) -> dict:
    """
    Backwards-compatible module-level API used by the Flask app.

    Returns a JSON-serializable dict with keys:
    store_name, store_location, postal_code, receipt_number, payment_method,
    date, total, items, raw_text
    """

    return _DEFAULT_EXTRACTOR.extract(text)
