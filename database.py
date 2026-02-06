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


def json_dumps_list(value):
    """Serialize list-like data to JSON."""
    return json.dumps(value or [], ensure_ascii=True)


def json_loads_list(value):
    """Deserialize JSON list or return empty list."""
    if not value:
        return []
    return json.loads(value)


def ensure_columns(conn, columns):
    """Add missing columns to receipts table."""
    existing_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(receipts)").fetchall()
    }
    for col, col_type in columns.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE receipts ADD COLUMN {col} {col_type}")


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
                labels TEXT,
                raw_text TEXT,
                created_at TEXT
            )
            """
        )
        # Auto-migration for new columns
        needed_cols = {
            "store_name": "TEXT",
            "store_location": "TEXT",
            "postal_code": "TEXT",
            "receipt_number": "TEXT",
            "payment_method": "TEXT",
            "labels": "TEXT",
            "raw_text": "TEXT",
        }
        ensure_columns(conn, needed_cols)
        
        # Create receipt_items table
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS receipt_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                receipt_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                quantity REAL DEFAULT 1.0,
                unit_price REAL,
                line_total REAL,
                FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
            )
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_receipt_items_receipt_id ON receipt_items(receipt_id)"
        )
        
        # Run migration to move JSON items to receipt_items table
        migrate_items_to_table(conn)
        
        # Add placeholder items for receipts with totals but no items
        add_placeholder_items_for_existing_receipts(conn)
        
        conn.commit()


def migrate_items_to_table(conn):
    """Migrate items from JSON column to receipt_items table."""
    # Check if migration is needed
    existing_items = conn.execute("SELECT COUNT(*) as count FROM receipt_items").fetchone()
    if existing_items['count'] > 0:
        # Already migrated
        return
    
    # Get all receipts with items
    receipts = conn.execute(
        "SELECT id, items FROM receipts WHERE items IS NOT NULL AND items != '[]'"
    ).fetchall()
    
    for receipt in receipts:
        receipt_id = receipt['id']
        items = json_loads_list(receipt['items'])
        
        for item in items:
            # Extract item data
            name = item.get('name', '')
            if not name:
                continue
            
            # Parse price - could be string like "1.50 €" or float
            price_str = item.get('price', '')
            line_total = None
            if price_str:
                line_total = parse_total_to_float(price_str)
            
            # Insert into receipt_items
            conn.execute(
                """
                INSERT INTO receipt_items (receipt_id, name, quantity, line_total)
                VALUES (?, ?, ?, ?)
                """,
                (receipt_id, name, 1.0, line_total)
            )
    
    conn.commit()


def add_placeholder_items_for_existing_receipts(conn):
    """Add placeholder items for receipts that have a total but no items in receipt_items."""
    # Find receipts with total > 0 but no items in receipt_items
    receipts = conn.execute(
        """
        SELECT r.id, r.total
        FROM receipts r
        LEFT JOIN receipt_items ri ON r.id = ri.receipt_id
        WHERE r.total IS NOT NULL 
          AND r.total > 0
          AND ri.id IS NULL
        """
    ).fetchall()
    
    for receipt in receipts:
        receipt_id = receipt['id']
        total = receipt['total']
        
        # Add placeholder item
        conn.execute(
            """
            INSERT INTO receipt_items (receipt_id, name, quantity, line_total)
            VALUES (?, ?, ?, ?)
            """,
            (receipt_id, "Unbekannte Artikel", 1.0, total)
        )
    
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


def save_receipt(result, labels=None):
    """Save extracted receipt data to database."""
    created_at = datetime.now(timezone.utc).isoformat()
    items_json = json_dumps_list(result.get('items', []))
    labels_json = json_dumps_list(labels or [])
    total_value = parse_total_to_float(result.get('total'))

    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO receipts (
                store_name, store_location, postal_code, receipt_number,
                payment_method, date, total, items, labels, raw_text, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                labels_json,
                result.get('raw_text'),
                created_at,
            ),
        )
        receipt_id = cursor.lastrowid
        
        # Also save items to receipt_items table
        items = result.get('items', [])
        has_items = False
        
        for item in items:
            name = item.get('name', '')
            if not name:
                continue
            
            has_items = True
            
            # Parse price
            price_str = item.get('price', '')
            line_total = None
            if price_str:
                line_total = parse_total_to_float(price_str)
            
            conn.execute(
                """
                INSERT INTO receipt_items (receipt_id, name, quantity, line_total)
                VALUES (?, ?, ?, ?)
                """,
                (receipt_id, name, 1.0, line_total)
            )
        
        # If no items were extracted but we have a total, create a placeholder item
        # This prevents the total from being lost when users add items manually
        if not has_items and total_value and total_value > 0:
            conn.execute(
                """
                INSERT INTO receipt_items (receipt_id, name, quantity, line_total)
                VALUES (?, ?, ?, ?)
                """,
                (receipt_id, "Unbekannte Artikel", 1.0, total_value)
            )
        
        conn.commit()


def update_receipt_labels(receipt_id, labels):
    """Update labels for a specific receipt."""
    labels_json = json_dumps_list(labels or [])
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE receipts SET labels = ? WHERE id = ?",
            (labels_json, receipt_id)
        )
        conn.commit()


def update_receipt(receipt_id, updates):
    """Update receipt fields."""
    allowed_fields = ['store_name', 'date', 'total', 'labels']
    set_parts = []
    values = []
    
    for field in allowed_fields:
        if field in updates:
            if field == 'labels':
                set_parts.append("labels = ?")
                values.append(json_dumps_list(updates['labels'] or []))
            elif field == 'total':
                set_parts.append("total = ?")
                values.append(parse_total_to_float(updates['total']))
            else:
                set_parts.append(f"{field} = ?")
                values.append(updates[field])
    
    if not set_parts:
        return False
    
    values.append(receipt_id)
    with get_db_connection() as conn:
        conn.execute(
            f"UPDATE receipts SET {', '.join(set_parts)} WHERE id = ?",
            values
        )
        conn.commit()
    return True


def get_all_receipts():
    """Retrieve all receipts from database."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, store_name, store_location, postal_code, receipt_number,
                   payment_method, date, total, items, labels, raw_text, created_at
            FROM receipts
            ORDER BY id DESC
            """
        ).fetchall()
        
        # Fetch all items from receipt_items table
        all_items = conn.execute(
            """
            SELECT receipt_id, name, quantity, unit_price, line_total
            FROM receipt_items
            ORDER BY id
            """
        ).fetchall()
        
        # Group items by receipt_id
        items_by_receipt = {}
        for item in all_items:
            receipt_id = item['receipt_id']
            if receipt_id not in items_by_receipt:
                items_by_receipt[receipt_id] = []
            
            # Format item like the original JSON structure
            item_dict = {
                'name': item['name'],
                'price': f"{item['line_total']:.2f} €" if item['line_total'] else ''
            }
            items_by_receipt[receipt_id].append(item_dict)

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
            # Read from receipt_items table, fallback to JSON
            'items': items_by_receipt.get(row['id'], json_loads_list(row['items'])),
            'labels': json_loads_list(row['labels']),
            'raw_text': row['raw_text'],
            'created_at': row['created_at'],
        }
        for row in rows
    ]


def get_all_labels():
    """Get all unique labels from receipts."""
    with get_db_connection() as conn:
        rows = conn.execute("SELECT labels FROM receipts WHERE labels IS NOT NULL").fetchall()

    all_labels = set()
    for row in rows:
        if row['labels']:
            labels = json_loads_list(row['labels'])
            all_labels.update(labels)

    return sorted(all_labels)


def get_receipt_stats():
    """Get aggregate statistics for receipts including monthly and category breakdown."""
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

        # All receipts for monthly and category aggregation
        all_rows = conn.execute(
            """
            SELECT date, total, labels
            FROM receipts
            WHERE total IS NOT NULL
            """
        ).fetchall()

    # Aggregate by month
    monthly_totals = {}
    category_totals = {}

    for r in all_rows:
        date_str = r['date']
        total = r['total']
        labels_json = r['labels']

        if total is None:
            continue

        # Monthly aggregation
        if date_str:
            month_key = None
            match = re.match(r'(\d{1,2})[./](\d{1,2})[./](\d{4})', date_str)
            if match:
                day, month, year = match.groups()
                month_key = f"{year}-{month.zfill(2)}"
            else:
                match = re.match(r'(\d{4})-(\d{2})-(\d{2})', date_str)
                if match:
                    year, month, day = match.groups()
                    month_key = f"{year}-{month}"

            if month_key:
                monthly_totals[month_key] = monthly_totals.get(month_key, 0) + total

        # Category aggregation
        labels = json_loads_list(labels_json)
        if labels:
            for label in labels:
                category_totals[label] = category_totals.get(label, 0) + total
        else:
            category_totals['Ohne Kategorie'] = category_totals.get('Ohne Kategorie', 0) + total

    # Sort
    sorted_monthly = dict(sorted(monthly_totals.items()))
    sorted_category = dict(sorted(category_totals.items(), key=lambda x: -x[1]))

    return {
        'count': row['count'] or 0,
        'sum': round(row['total_sum'] or 0.0, 2),
        'average': round(row['total_avg'] or 0.0, 2),
        'monthly_totals': sorted_monthly,
        'category_totals': sorted_category,
    }


def add_receipt_item(receipt_id, name, price):
    """Add an item to a receipt."""
    line_total = parse_total_to_float(price)
    
    with get_db_connection() as conn:
        conn.execute(
            """
            INSERT INTO receipt_items (receipt_id, name, quantity, line_total)
            VALUES (?, ?, ?, ?)
            """,
            (receipt_id, name, 1.0, line_total)
        )
        conn.commit()
    
    # Recalculate total
    recalculate_receipt_total(receipt_id)


def delete_receipt_item(item_id):
    """Delete an item from receipt_items table."""
    with get_db_connection() as conn:
        # Get receipt_id before deleting
        row = conn.execute(
            "SELECT receipt_id FROM receipt_items WHERE id = ?",
            (item_id,)
        ).fetchone()
        
        if not row:
            return False
        
        receipt_id = row['receipt_id']
        
        conn.execute("DELETE FROM receipt_items WHERE id = ?", (item_id,))
        conn.commit()
    
    # Recalculate total
    recalculate_receipt_total(receipt_id)
    return True


def get_receipt_items(receipt_id):
    """Get all items for a specific receipt."""
    with get_db_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, name, quantity, unit_price, line_total
            FROM receipt_items
            WHERE receipt_id = ?
            ORDER BY id
            """,
            (receipt_id,)
        ).fetchall()
    
    return [
        {
            'id': row['id'],
            'name': row['name'],
            'quantity': row['quantity'],
            'unit_price': row['unit_price'],
            'line_total': row['line_total'],
            'price': f"{row['line_total']:.2f} €" if row['line_total'] else ''
        }
        for row in rows
    ]


def recalculate_receipt_total(receipt_id):
    """Recalculate and update receipt total from items."""
    with get_db_connection() as conn:
        row = conn.execute(
            """
            SELECT SUM(line_total) as total
            FROM receipt_items
            WHERE receipt_id = ? AND line_total IS NOT NULL
            """,
            (receipt_id,)
        ).fetchone()
        
        new_total = row['total'] or 0.0
        
        conn.execute(
            "UPDATE receipts SET total = ? WHERE id = ?",
            (new_total, receipt_id)
        )
        conn.commit()
    
    return new_total
