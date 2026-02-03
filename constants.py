"""
Constants for receipt extraction.
"""

# Common store names for priority detection
KNOWN_STORES = [
    'rewe', 'edeka', 'aldi', 'lidl', 'penny', 'netto', 'kaufland', 'real',
    'dm', 'rossmann', 'müller', 'budni', 'ikea', 'mediamarkt', 'saturn',
    'obi', 'bauhaus', 'hornbach', 'toom', 'hagebau',
    'späti', 'spätverkauf', 'kiosk', 'trinkhalle',
    'mcdonald', 'mcdonalds', 'burger king', 'subway', 'starbucks', 'dunkin',
    'backwerk', 'ditsch', 'nordsee', 'vapiano', 'dean & david',
    'tankstelle', 'aral', 'shell', 'esso', 'jet', 'total', 'star',
    'apotheke', 'reformhaus', 'bio company', 'denns', 'alnatura',
    'tk maxx', 'primark', 'h&m', 'zara', 'c&a', 'deichmann', 'foot locker',
    'saturn', 'expert', 'euronics', 'conrad',
    'action', 'tedi', 'woolworth', 'nanu nana', 'depot',
    'gmbh', 'kg', 'ohg', 'e.k.', 'ag',
]

# Blocked words for filtering meta lines
BLOCKED_WORDS = [
    'total', 'summe', 'gesamt', 'subtotal', 'zwischensumme', 'netto', 'brutto',
    'mwst', 'ust', 'steuer', 'tax', 'rabatt', 'discount', 'nachlass',
    'change', 'rückgeld', 'wechselgeld', 'gegeben', 'zurück',
    'cash', 'bar', 'visa', 'mastercard', 'karte', 'ec', 'ec-karte', 'maestro',
    'betrag', 'zu zahlen', 'endsumme', 'zwsumme', 'pfand', 'leergut',
    'bon', 'beleg', 'kassenbon', 'quittung', 'rechnung',
    # Fiscal/technical terms
    'tse', 'seriennr', 'transaktionsnr', 'signaturzähler', 'prüfwert',
    'tse-seriennr', 'signatur', 'transaktion', 'kassennr', 'filiale',
    'bediener', 'kasse', 'terminal', 'trace', 'auth', 'datum', 'uhrzeit',
]

# Payment method patterns
PAYMENT_PATTERNS = [
    (r'\b(bar|cash|bargeld)\b', 'Cash'),
    (r'\b(ec|ec-karte|maestro|girocard)\b', 'EC'),
    (r'\b(kreditkarte|credit)\b', 'Card'),
    (r'\b(visa)\b', 'Visa'),
    (r'\b(mastercard|mc)\b', 'Mastercard'),
    (r'\b(karte|card)\b', 'Card'),
]

# Date patterns (ordered by specificity)
DATE_PATTERNS = [
    r'\b(\d{2}[./]\d{2}[./]\d{4})\b',  # DD.MM.YYYY or DD/MM/YYYY
    r'\b(\d{1,2}[./]\d{1,2}[./]\d{2})\b',  # D.M.YY or DD.MM.YY
    r'\b(\d{4}-\d{2}-\d{2})\b',  # YYYY-MM-DD
    r'\b(\d{2}-\d{2}-\d{4})\b',  # DD-MM-YYYY
]

# Total amount patterns
TOTAL_PATTERNS = [
    r'(?:total|summe|gesamt|zu zahlen|endsumme|betrag|amount|gesamtbetrag)[:\s]*([€$]?\s*\d+[.,]\d{2})',
    r'(?:total|summe|gesamt|zu zahlen|endsumme)[:\s]*\**\s*([€$]?\s*\d+[.,]\d{2})',
    r'([€$]\s*\d+[.,]\d{2})\s*$',
    r'(\d+[.,]\d{2})\s*(?:€|EUR|USD|\$)',
]

# Receipt number patterns
RECEIPT_NUMBER_PATTERN = r'\b(?:receipt|beleg|bon|kassenbon|nr|nr\.|no|no\.|belegnr|beleg-nr|receipt no|bonnr|bon-nr|transaktionsnr|transaktion)[.:\s-]*([A-Za-z0-9-]+)'

# Item line pattern
ITEM_PATTERN = r'^(.+?)\s+(\d+[.,]\d{2})\s*€?$'

# Quantity prefix pattern
QUANTITY_PATTERN = r'^\s*(\d+)\s*[xX]\b\s*'
