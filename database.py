"""
Database operations for receipt storage.
"""

import json
import os
import re
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "receipts.db")


def get_db_connection():
    """Create a database connection with Row factory."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Initialize database and run migrations."""
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS receipts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                store_name TEXT,
                store_location TEXT,
                postal_code TEXT,
                receipt_number TEXT,
                payment_method TEXT,
                date TEXT,
                total REAL,
                items TEXT,
                raw_text TEXT,
                created_at TEXT
            )
            """
        )
        # Auto-migration for new columns
        existing_cols = {
            row["name"] for row in conn.execute("PRAGMA table_info(receipts)").fetchall()
        }
        needed_cols = {
            "store_name": "TEXT",
            "store_location": "TEXT",
            "postal_code": "TEXT",
            "receipt_number": "TEXT",
            "payment_method": "TEXT",
            "raw_text": "TEXT",
        }
        for col, col_type in needed_cols.items():
            if col not in existing_cols:
                conn.execute(f"ALTER TABLE receipts ADD COLUMN {col} {col_type}")
        conn.commit()


def parse_total_to_float(total):
    """Convert total string to float."""
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


def save_receipt(result):
    """Save extracted receipt data to database."""
    created_at = datetime.now(timezone.utc).isoformat()
    items_json = json.dumps(result.get('items', []), ensure_ascii=True)
    total_value = parse_total_to_float(result.get('total'))
    
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO receipts (
                store_name, store_location, postal_code, receipt_number,
                payment_method, date, total, items, raw_text, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get('store_name'),
                result.get('store_location'),
                result.get('postal_code'),
                result.get('receipt_number'),
                result.get('payment_method'),
                result.get('date'),
                total_value,
                items_json,
                result.get('raw_text'),
                created_at,
            ),
        )
        conn.commit()


def get_all_receipts():
    """Retrieve all receipts from database."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, store_name, store_location, postal_code, receipt_number,
                   payment_method, date, total, items, raw_text, created_at
            FROM receipts
            ORDER BY id DESC
            """
        ).fetchall()
    
    return [
        {
            'id': row['id'],
            'store_name': row['store_name'],
            'store_location': row['store_location'],
            'postal_code': row['postal_code'],
            'receipt_number': row['receipt_number'],
            'payment_method': row['payment_method'],
            'date': row['date'],
            'total': row['total'],
            'items': json.loads(row['items']) if row['items'] else [],
            'raw_text': row['raw_text'],
            'created_at': row['created_at'],
        }
        for row in rows
    ]


def get_receipt_stats():
    """Get aggregate statistics for receipts including monthly breakdown."""
    with get_db_connection() as conn:
        # Basic stats
        row = conn.execute(
            """
            SELECT COUNT(*) AS count,
                   SUM(total) AS total_sum,
                   AVG(total) AS total_avg
            FROM receipts
            """
        ).fetchone()

        # Monthly totals - extract month from date field
        monthly_rows = conn.execute(
            """
            SELECT date, total
            FROM receipts
            WHERE date IS NOT NULL AND total IS NOT NULL
            """
        ).fetchall()

    # Aggregate by month
    monthly_totals = {}
    for r in monthly_rows:
        date_str = r['date']
        total = r['total']
        if not date_str or total is None:
            continue

        # Parse various date formats to extract YYYY-MM
        month_key = None
        # DD.MM.YYYY or DD/MM/YYYY
        match = re.match(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', date_str)
        if match:
            day, month, year = match.groups()
            month_key = f"{year}-{month.zfill(2)}"
        else:
            # YYYY-MM-DD
            match = re.match(r'(\d{4})-(\d{2})-(\d{2})', date_str)
            if match:
                year, month, day = match.groups()
                month_key = f"{year}-{month}"

        if month_key:
            monthly_totals[month_key] = monthly_totals.get(month_key, 0) + total

    # Sort by month
    sorted_monthly = dict(sorted(monthly_totals.items()))

    return {
        'count': row['count'] or 0,
        'sum': round(row['total_sum'] or 0.0, 2),
        'average': round(row['total_avg'] or 0.0, 2),
        'monthly_totals': sorted_monthly,
    }

