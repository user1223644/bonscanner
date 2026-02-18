"""
Database operations for receipt storage.
"""

import json
import os
import re
import sqlite3
import threading
from datetime import datetime, timezone


def _resolve_db_path(configured_path):
    # Keep legacy default (DB next to this file) but allow overriding via env var.
    if not configured_path:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        return os.path.join(base_dir, "receipts.db")
    # Special SQLite paths should pass through unchanged.
    if configured_path == ":memory:" or configured_path.startswith("file:"):
        return configured_path
    return os.path.abspath(configured_path)


DB_PATH = _resolve_db_path(os.environ.get("BONSCANNER_DB_PATH"))

_DB_INITIALIZED = False
_DB_INIT_LOCK = threading.Lock()


def _is_ephemeral_db_path(path):
    if path == ":memory:":
        return True
    # Common shared in-memory URI forms: file::memory:?cache=shared or file:...mode=memory
    if path.startswith("file:") and (":memory:" in path or "mode=memory" in path):
        return True
    return False


def _ensure_db_parent_dir():
    if DB_PATH == ":memory:" or DB_PATH.startswith("file:"):
        return
    parent_dir = os.path.dirname(DB_PATH)
    if parent_dir:
        os.makedirs(parent_dir, exist_ok=True)


def _raw_connect():
    _ensure_db_parent_dir()
    conn = sqlite3.connect(DB_PATH, uri=DB_PATH.startswith("file:"))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db_connection():
    """Create a database connection with Row factory."""
    conn = _raw_connect()
    _ensure_db_initialized(conn)
    return conn


def json_dumps_list(value):
    """Serialize list-like data to JSON."""
    return json.dumps(value or [], ensure_ascii=True)


def json_loads_list(value):
    """Deserialize JSON list or return empty list."""
    if not value:
        return []
    return json.loads(value)


def normalize_labels(labels):
    """Normalize label list (trim, dedupe, drop empties)."""
    if not labels:
        return []
    cleaned = [str(label).strip() for label in labels if str(label).strip()]
    return list(dict.fromkeys(cleaned))


def ensure_categories(conn, labels):
    """Ensure categories exist for the provided labels."""
    label_list = normalize_labels(labels)
    if not label_list:
        return
    now = datetime.now(timezone.utc).isoformat()
    for label in label_list:
        conn.execute(
            """
            INSERT OR IGNORE INTO categories (name, created_at, updated_at)
            VALUES (?, ?, ?)
            """,
            (label, now, now),
        )


def get_category_ids(conn, labels):
    """Return mapping of label -> category_id for known categories."""
    label_list = normalize_labels(labels)
    if not label_list:
        return {}
    placeholders = ", ".join("?" for _ in label_list)
    rows = conn.execute(
        f"""
        SELECT id, name
        FROM categories
        WHERE name IN ({placeholders}) AND deleted_at IS NULL
        """,
        label_list,
    ).fetchall()
    return {row["name"]: row["id"] for row in rows}


def sync_receipt_categories(conn, receipt_id, labels, source=None):
    """Sync receipt_categories rows to match provided labels."""
    label_list = normalize_labels(labels)

    existing = conn.execute(
        """
        SELECT c.id, c.name
        FROM receipt_categories rc
        JOIN categories c ON rc.category_id = c.id
        WHERE rc.receipt_id = ?
        """,
        (receipt_id,),
    ).fetchall()
    existing_by_name = {row["name"]: row["id"] for row in existing}

    if not label_list and not existing_by_name:
        return

    ensure_categories(conn, label_list)
    category_ids = get_category_ids(conn, label_list)

    desired_ids = {category_ids[name] for name in label_list if name in category_ids}
    existing_ids = set(existing_by_name.values())

    to_remove = existing_ids - desired_ids
    if to_remove:
        placeholders = ", ".join("?" for _ in to_remove)
        conn.execute(
            f"""
            DELETE FROM receipt_categories
            WHERE receipt_id = ? AND category_id IN ({placeholders})
            """,
            (receipt_id, *to_remove),
        )

    to_add = desired_ids - existing_ids
    if to_add:
        now = datetime.now(timezone.utc).isoformat()
        for category_id in to_add:
            conn.execute(
                """
                INSERT OR IGNORE INTO receipt_categories
                    (receipt_id, category_id, source, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (receipt_id, category_id, source, now),
            )


def backfill_receipt_categories(conn):
    """Populate categories/receipt_categories from legacy receipt labels."""
    existing = conn.execute(
        "SELECT COUNT(*) as count FROM receipt_categories"
    ).fetchone()
    if existing["count"] > 0:
        return
    rows = conn.execute(
        "SELECT id, labels FROM receipts WHERE labels IS NOT NULL AND labels != '[]'"
    ).fetchall()
    for row in rows:
        labels = json_loads_list(row["labels"])
        sync_receipt_categories(conn, row["id"], labels, source="legacy")


def ensure_columns(conn, columns):
    """Add missing columns to receipts table."""
    existing_cols = {
        row["name"] for row in conn.execute("PRAGMA table_info(receipts)").fetchall()
    }
    for col, col_type in columns.items():
        if col not in existing_cols:
            try:
                conn.execute(f"ALTER TABLE receipts ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError as exc:
                # In multi-process setups, another worker may have raced this migration.
                msg = str(exc).lower()
                if "duplicate column name" in msg or "already exists" in msg:
                    continue
                raise


def ensure_table_columns(conn, table_name, columns):
    """Add missing columns to a table."""
    existing_cols = {
        row["name"] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    }
    for col, col_type in columns.items():
        if col not in existing_cols:
            try:
                conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError as exc:
                msg = str(exc).lower()
                if "duplicate column name" in msg or "already exists" in msg:
                    continue
                raise


def init_db():
    """Initialize database and run migrations."""
    global _DB_INITIALIZED
    with _raw_connect() as conn:
        _run_migrations(conn)
    if not _is_ephemeral_db_path(DB_PATH):
        _DB_INITIALIZED = True


def _ensure_db_initialized(conn):
    global _DB_INITIALIZED
    if _is_ephemeral_db_path(DB_PATH):
        _run_migrations(conn)
        return
    if _DB_INITIALIZED:
        return
    with _DB_INIT_LOCK:
        if _DB_INITIALIZED:
            return
        _run_migrations(conn)
        _DB_INITIALIZED = True


def _run_migrations(conn):
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
    ensure_table_columns(
        conn,
        "receipt_items",
        {
            "unit": "TEXT",
            "currency": "TEXT",
            "is_discount": "INTEGER",
            "tax_rate": "REAL",
            "tax_amount": "REAL",
        },
    )

    # Categories and mappings for future extensibility
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT,
            created_at TEXT,
            updated_at TEXT,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS receipt_categories (
            receipt_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            source TEXT,
            created_at TEXT,
            PRIMARY KEY (receipt_id, category_id),
            FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_receipt_categories_receipt_id ON receipt_categories(receipt_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_receipt_categories_category_id ON receipt_categories(category_id)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS receipt_item_categories (
            item_id INTEGER NOT NULL,
            category_id INTEGER NOT NULL,
            allocation_amount REAL,
            allocation_ratio REAL,
            source TEXT,
            created_at TEXT,
            PRIMARY KEY (item_id, category_id),
            FOREIGN KEY (item_id) REFERENCES receipt_items(id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_receipt_item_categories_item_id ON receipt_item_categories(item_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_receipt_item_categories_category_id ON receipt_item_categories(category_id)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS category_rules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            rule_type TEXT NOT NULL,
            pattern TEXT NOT NULL,
            match_type TEXT NOT NULL DEFAULT 'contains',
            category_id INTEGER NOT NULL,
            priority INTEGER DEFAULT 100,
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_category_rules_type ON category_rules(rule_type, is_active)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_category_rules_category_id ON category_rules(category_id)"
    )

    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS receipt_taxes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            receipt_id INTEGER NOT NULL,
            tax_rate REAL,
            tax_amount REAL,
            taxable_amount REAL,
            source TEXT,
            created_at TEXT,
            FOREIGN KEY (receipt_id) REFERENCES receipts(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_receipt_taxes_receipt_id ON receipt_taxes(receipt_id)"
    )

    # Run migration to move JSON items to receipt_items table
    migrate_items_to_table(conn)

    # Add placeholder items for receipts with totals but no items
    add_placeholder_items_for_existing_receipts(conn)

    # Backfill categories from legacy receipt labels
    backfill_receipt_categories(conn)

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

        sync_receipt_categories(conn, receipt_id, labels, source=None)
        
        conn.commit()


def update_receipt_labels(receipt_id, labels):
    """Update labels for a specific receipt."""
    labels_json = json_dumps_list(labels or [])
    with get_db_connection() as conn:
        conn.execute(
            "UPDATE receipts SET labels = ? WHERE id = ?",
            (labels_json, receipt_id)
        )
        sync_receipt_categories(conn, receipt_id, labels, source="manual")
        conn.commit()


def update_receipt(receipt_id, updates):
    """Update receipt fields."""
    allowed_fields = ['store_name', 'date', 'total', 'labels']
    set_parts = []
    values = []
    label_updates = None
    
    for field in allowed_fields:
        if field in updates:
            if field == 'labels':
                set_parts.append("labels = ?")
                label_updates = updates['labels'] or []
                values.append(json_dumps_list(label_updates))
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
        if label_updates is not None:
            sync_receipt_categories(conn, receipt_id, label_updates, source="manual")
        conn.commit()
    return True


def get_all_receipts(store_filter=None, date_from=None, date_to=None, label_filter=None):
    """Retrieve all receipts from database with optional filtering.
    
    Args:
        store_filter: Filter by store name (case-insensitive substring match)
        date_from: Filter receipts from this date (YYYY-MM-DD)
        date_to: Filter receipts to this date (YYYY-MM-DD)
        label_filter: Filter by label (exact match)
    
    Returns:
        List of receipt dictionaries
    """
    with get_db_connection() as conn:
        # Build SQL query with optional filters
        sql = """
            SELECT id, store_name, store_location, postal_code, receipt_number,
                   payment_method, date, total, items, labels, raw_text, created_at
            FROM receipts
            WHERE 1=1
        """
        params = []
        
        # Store name filter (case-insensitive)
        if store_filter:
            sql += " AND LOWER(store_name) LIKE LOWER(?)"
            params.append(f"%{store_filter}%")
        
        # Date range filters
        if date_from:
            # Support both DD.MM.YYYY and YYYY-MM-DD formats
            sql += " AND (date >= ? OR date LIKE ?)"
            params.append(date_from)
            params.append(f"%{date_from}%")
        
        if date_to:
            sql += " AND (date <= ? OR date LIKE ?)"
            params.append(date_to)
            params.append(f"%{date_to}%")
        
        # Label filter
        if label_filter:
            sql += " AND labels LIKE ?"
            params.append(f'%"{label_filter}"%')
        
        sql += " ORDER BY id DESC"
        
        rows = conn.execute(sql, params).fetchall()
        
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
