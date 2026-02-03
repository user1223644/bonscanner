"""
Minimal Receipt Scanner Backend
Flask API with Tesseract OCR
"""

import json
import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS
import pytesseract
from PIL import Image

app = Flask(__name__)
CORS(app)

DB_PATH = os.path.join(os.path.dirname(__file__), "receipts.db")


def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                total REAL,
                items TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()


def parse_total_to_float(total):
    if total is None:
        return None
    cleaned = re.sub(r'[^\d,.\-]', '', str(total))
    cleaned = cleaned.replace(',', '.')
    if cleaned == '':
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def save_receipt_to_db(result):
    created_at = datetime.now(timezone.utc).isoformat()
    items_json = json.dumps(result.get('items', []), ensure_ascii=True)
    total_value = parse_total_to_float(result.get('total'))
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO receipts (date, total, items, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (result.get('date'), total_value, items_json, created_at),
        )
        conn.commit()


def extract_receipt_data(text):
    """Extract date, total, and items from OCR text."""
    lines = text.strip().split('\n')
    lines = [line.strip() for line in lines if line.strip()]
    
    # Extract date (common formats: DD.MM.YYYY, DD/MM/YYYY, YYYY-MM-DD)
    date = None
    date_patterns = [
        r'\b(\d{1,2}[./]\d{1,2}[./]\d{2,4})\b',
        r'\b(\d{4}-\d{2}-\d{2})\b',
    ]
    for pattern in date_patterns:
        match = re.search(pattern, text)
        if match:
            date = match.group(1)
            break
    
    # Extract total amount (look for keywords like Total, Summe, Gesamt)
    total = None
    total_patterns = [
        r'(?:total|summe|gesamt|zu zahlen|betrag|amount)[:\s]*([€$]?\s*\d+[.,]\d{2})',
        r'([€$]\s*\d+[.,]\d{2})\s*$',
        r'(\d+[.,]\d{2})\s*(?:€|EUR|USD|\$)',
    ]
    for pattern in total_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            total = match.group(1).strip()
            break
    
    # Extract items (lines with prices)
    items = []
    item_pattern = r'^(.+?)\s+(\d+[.,]\d{2})\s*€?$'
    blocked_words = [
        'total', 'summe', 'gesamt', 'subtotal', 'zwischensumme', 'mwst', 'ust',
        'steuer', 'tax', 'rabatt', 'discount', 'change', 'rückgeld', 'cash',
        'visa', 'mastercard', 'karte', 'ec', 'betrag', 'zu zahlen'
    ]
    for line in lines:
        match = re.match(item_pattern, line)
        if match:
            name = match.group(1).strip()
            price = match.group(2)
            # Strict filter: exclude any meta lines and only allow clear name + price lines.
            lowered = line.lower()
            has_blocked = any(word in lowered for word in blocked_words)
            has_letter = re.search(r'[A-Za-zÄÖÜäöüß]', name) is not None
            if len(name) > 2 and has_letter and not has_blocked:
                items.append({'name': name, 'price': price})
    
    return {
        'date': date,
        'total': total,
        'items': items,
        'raw_text': text
    }


@app.route('/upload', methods=['POST'])
def upload_receipt():
    """Endpoint to receive and process receipt image."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400
    
    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    try:
        # Save to temp file and process
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            file.save(tmp.name)
            
            # Open image and run OCR
            image = Image.open(tmp.name)
            text = pytesseract.image_to_string(image, lang='deu+eng')
            
            # Clean up temp file
            os.unlink(tmp.name)
        
        # Extract structured data
        result = extract_receipt_data(text)
        save_receipt_to_db(result)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/scan', methods=['POST'])
def scan_receipt():
    """Backwards-compatible alias for /upload."""
    return upload_receipt()


@app.route('/receipts', methods=['GET'])
def list_receipts():
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT id, date, total, items, created_at FROM receipts ORDER BY id DESC"
        ).fetchall()
    receipts = []
    for row in rows:
        receipts.append(
            {
                'id': row['id'],
                'date': row['date'],
                'total': row['total'],
                'items': json.loads(row['items']) if row['items'] else [],
                'created_at': row['created_at'],
            }
        )
    return jsonify(receipts)


@app.route('/stats', methods=['GET'])
def receipt_stats():
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count,
                   SUM(total) AS total_sum,
                   AVG(total) AS total_avg
            FROM receipts
            """
        ).fetchone()
    return jsonify(
        {
            'count': row['count'] or 0,
            'sum': row['total_sum'] or 0.0,
            'average': row['total_avg'] or 0.0,
        }
    )


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})


init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
