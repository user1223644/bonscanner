"""
Receipt data extraction from OCR text.
"""

import re
from constants import (
    KNOWN_STORES, BLOCKED_WORDS, PAYMENT_PATTERNS,
    DATE_PATTERNS, TOTAL_PATTERNS, RECEIPT_NUMBER_PATTERN,
    ITEM_PATTERN, QUANTITY_PATTERN
)


def is_technical_line(line):
    """Check if line looks like a technical/fiscal line."""
    # Lines with long alphanumeric codes (8+ chars)
    if re.search(r'[A-Z0-9]{8,}', line):
        return True
    # Lines with colon followed by mostly numbers/codes
    if re.search(r':\s*[A-Z0-9]{5,}', line, re.IGNORECASE):
        return True
    # Lines starting with technical keywords
    if re.match(r'^(tse|signatur|transaktion|prüf|trace|auth|terminal)', line, re.IGNORECASE):
        return True
    return False


def pick_store_name(lines):
    """Extract store name from receipt lines."""
    # First pass: look for known store names (highest priority)
    for line in lines[:15]:
        lowered = line.lower()
        for store in KNOWN_STORES:
            if store in lowered:
                if not any(word in lowered for word in BLOCKED_WORDS[:30]):
                    if not is_technical_line(line):
                        return line

    # Second pass: find first clean line that looks like a company name
    for line in lines[:15]:
        if re.search(r'[A-Za-zÄÖÜäöüß]', line) is None:
            continue
        lowered = line.lower()
        if any(word in lowered for word in BLOCKED_WORDS):
            continue
        if is_technical_line(line):
            continue
        if re.search(r'\d+[.,]\d{2}', line):
            continue
        if re.search(r'\d{1,2}[./]\d{1,2}[./]\d{2,4}', line):
            continue
        if re.match(r'^[A-Za-zÄÖÜäöüß]+(?:straße|str\.|weg|platz|allee)\s+\d+', line, re.IGNORECASE):
            continue
        if len(line) < 3:
            continue
        return line
    return None


def pick_store_location(lines):
    """Extract location with postal code and city."""
    for line in lines[:15]:
        match = re.search(r'\b(\d{5})\s+([A-Za-zÄÖÜäöüß][A-Za-zÄÖÜäöüß\s-]+)', line)
        if match:
            if not re.search(r'^\s*\d+[.,]\d{2}\s*€?\s*$', line):
                if not is_technical_line(line):
                    return line
    return None


def pick_postal_code(lines):
    """Extract just the postal code (PLZ)."""
    for line in lines[:15]:
        match = re.search(r'\b(\d{5})\b', line)
        if match:
            if re.search(r'[A-Za-zÄÖÜäöüß]{3,}', line):
                if not re.search(r'\d+[.,]\d{2}', line):
                    if not is_technical_line(line):
                        return match.group(1)
    return None


def pick_receipt_number(lines):
    """Extract receipt/transaction number."""
    for line in lines:
        match = re.search(RECEIPT_NUMBER_PATTERN, line, re.IGNORECASE)
        if match:
            return match.group(1)
    return None


def pick_payment_method(lines):
    """Extract payment method."""
    for line in lines:
        for pattern, label in PAYMENT_PATTERNS:
            if re.search(pattern, line, re.IGNORECASE):
                return label
    return None


def extract_date(text):
    """Extract date from text."""
    for pattern in DATE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def extract_total(text):
    """Extract total amount from text."""
    for pattern in TOTAL_PATTERNS:
        match = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None


def extract_items(lines):
    """Extract individual items from receipt lines."""
    items = []
    seen_items = set()

    for line in lines:
        match = re.match(ITEM_PATTERN, line)
        if not match:
            continue

        name = match.group(1).strip()
        price = match.group(2)

        # Filter blocked words
        lowered = line.lower()
        if any(word in lowered for word in BLOCKED_WORDS):
            continue

        # Skip technical lines
        if is_technical_line(line):
            continue

        # Extract quantity
        quantity = 1
        qty_match = re.match(QUANTITY_PATTERN, name)
        if qty_match:
            quantity = int(qty_match.group(1))
            name = name[qty_match.end():].strip()

        # Validate name
        if len(name) <= 2:
            continue
        if not re.search(r'[A-Za-zÄÖÜäöüß]', name):
            continue

        # Deduplicate
        item_key = (name.lower(), price)
        if item_key in seen_items:
            continue
        seen_items.add(item_key)

        items.append({'name': name, 'price': price, 'quantity': quantity})

    return items


def extract_receipt_data(text):
    """Extract all structured data from OCR text."""
    lines = text.strip().split('\n')
    lines = [line.strip() for line in lines if line.strip()]

    return {
        'store_name': pick_store_name(lines),
        'store_location': pick_store_location(lines),
        'postal_code': pick_postal_code(lines),
        'receipt_number': pick_receipt_number(lines),
        'payment_method': pick_payment_method(lines),
        'date': extract_date(text),
        'total': extract_total(text),
        'items': extract_items(lines),
        'raw_text': text
    }
