"""
Database operations for receipt storage.
"""

import json
import os
import re
import sqlite3
import tempfile
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


def backfill_receipt_dates(conn):
    """Populate date_iso for receipts that have a date but no normalized date."""
    rows = conn.execute(
        """
        SELECT id, date
        FROM receipts
        WHERE date IS NOT NULL
          AND (date_iso IS NULL OR date_iso = '')
        """
    ).fetchall()
    for row in rows:
        date_iso = parse_date_to_iso(row["date"])
        if not date_iso:
            continue
        conn.execute(
            "UPDATE receipts SET date_iso = ? WHERE id = ?",
            (date_iso, row["id"]),
        )


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
        "date_iso": "TEXT",
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

    # Backfill normalized date column
    backfill_receipt_dates(conn)

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


def parse_date_to_iso(date_value):
    """Normalize common receipt date formats to YYYY-MM-DD."""
    if not date_value:
        return None
    raw = str(date_value).strip()
    if not raw:
        return None
    match = re.match(r"^(\d{4})[./-](\d{1,2})[./-](\d{1,2})", raw)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    match = re.match(r"^(\d{1,2})[./-](\d{1,2})[./-](\d{4})", raw)
    if match:
        day, month, year = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None


def save_receipt(result, labels=None):
    """Save extracted receipt data to database."""
    created_at = datetime.now(timezone.utc).isoformat()
    items_json = json_dumps_list(result.get('items', []))
    labels_json = json_dumps_list(labels or [])
    total_value = parse_total_to_float(result.get('total'))
    receipt_currency = result.get('currency')
    date_iso = parse_date_to_iso(result.get('date'))

    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO receipts (
                store_name, store_location, postal_code, receipt_number,
                payment_method, date, date_iso, total, items, labels, raw_text, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                result.get('store_name'),
                result.get('store_location'),
                result.get('postal_code'),
                result.get('receipt_number'),
                result.get('payment_method'),
                result.get('date'),
                date_iso,
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

            quantity = item.get('quantity', 1.0)
            try:
                quantity = float(quantity) if quantity is not None else 1.0
            except (TypeError, ValueError):
                quantity = 1.0

            # Parse prices
            line_total = item.get('line_total_amount')
            if line_total is None:
                price_str = item.get('price', '')
                line_total = parse_total_to_float(price_str)

            unit_price = item.get('unit_price_amount')
            if unit_price is None:
                unit_price = parse_total_to_float(item.get('unit_price'))

            is_discount = item.get('is_discount')
            is_discount_value = 1 if is_discount else 0 if is_discount is not None else None
            unit = item.get('unit')
            currency = item.get('currency') or receipt_currency
            tax_rate = item.get('tax_rate')
            tax_amount = item.get('tax_amount')
            
            conn.execute(
                """
                INSERT INTO receipt_items (
                    receipt_id, name, quantity, unit_price, line_total,
                    unit, currency, is_discount, tax_rate, tax_amount
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    name,
                    quantity,
                    unit_price,
                    line_total,
                    unit,
                    currency,
                    is_discount_value,
                    tax_rate,
                    tax_amount,
                )
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

        taxes = result.get('taxes') or []
        if taxes:
            now = datetime.now(timezone.utc).isoformat()
            for tax in taxes:
                conn.execute(
                    """
                    INSERT INTO receipt_taxes
                        (receipt_id, tax_rate, tax_amount, taxable_amount, source, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        receipt_id,
                        tax.get("tax_rate"),
                        tax.get("tax_amount"),
                        tax.get("taxable_amount"),
                        "ocr",
                        now,
                    ),
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
    allowed_fields = ['store_name', 'date', 'total', 'labels', 'payment_method']
    set_parts = []
    values = []
    label_updates = None
    
    for field in allowed_fields:
        if field in updates:
            if field == 'labels':
                set_parts.append("labels = ?")
                label_updates = updates['labels'] or []
                values.append(json_dumps_list(label_updates))
            elif field == 'date':
                set_parts.append("date = ?")
                values.append(updates['date'])
                date_iso = parse_date_to_iso(updates['date'])
                set_parts.append("date_iso = ?")
                values.append(date_iso)
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


def _normalize_text_filter(value):
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _build_receipt_filters(
    store_filter=None,
    date_from=None,
    date_to=None,
    label_filter=None,
    category_filter=None,
    amount_min=None,
    amount_max=None,
    text_filter=None,
    payment_method=None,
):
    where = []
    params = []

    store_filter = _normalize_text_filter(store_filter)
    text_filter = _normalize_text_filter(text_filter)
    payment_method = _normalize_text_filter(payment_method)
    category_name = _normalize_text_filter(category_filter or label_filter)

    if store_filter:
        where.append("LOWER(r.store_name) LIKE LOWER(?)")
        params.append(f"%{store_filter}%")

    if date_from:
        where.append("r.date_iso >= ?")
        params.append(date_from)

    if date_to:
        where.append("r.date_iso <= ?")
        params.append(date_to)

    if amount_min is not None:
        where.append("r.total >= ?")
        params.append(amount_min)

    if amount_max is not None:
        where.append("r.total <= ?")
        params.append(amount_max)

    if payment_method:
        where.append("LOWER(r.payment_method) LIKE LOWER(?)")
        params.append(f"%{payment_method}%")

    if category_name:
        where.append(
            """
            (
                EXISTS (
                    SELECT 1
                    FROM receipt_categories rc
                    JOIN categories c ON rc.category_id = c.id
                    WHERE rc.receipt_id = r.id
                      AND c.deleted_at IS NULL
                      AND c.name = ?
                )
                OR r.labels LIKE ?
            )
            """
        )
        params.append(category_name)
        params.append(f'%"{category_name}"%')

    if text_filter:
        like = f"%{text_filter}%"
        where.append(
            """
            (
                LOWER(r.store_name) LIKE LOWER(?)
                OR LOWER(r.store_location) LIKE LOWER(?)
                OR LOWER(r.receipt_number) LIKE LOWER(?)
                OR LOWER(r.payment_method) LIKE LOWER(?)
                OR LOWER(r.raw_text) LIKE LOWER(?)
                OR EXISTS (
                    SELECT 1
                    FROM receipt_items ri
                    WHERE ri.receipt_id = r.id
                      AND LOWER(ri.name) LIKE LOWER(?)
                )
            )
            """
        )
        params.extend([like, like, like, like, like, like])

    return where, params


def _fetch_receipts_rows(conn, where, params, limit=None, offset=None):
    sql = """
        SELECT r.id, r.store_name, r.store_location, r.postal_code, r.receipt_number,
               r.payment_method, r.date, r.date_iso, r.total, r.items, r.labels,
               r.raw_text, r.created_at
        FROM receipts r
    """
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.id DESC"
    if limit is not None:
        sql += " LIMIT ?"
        params = params + [limit]
        if offset:
            sql += " OFFSET ?"
            params = params + [offset]
    return conn.execute(sql, params).fetchall()


def _fetch_receipts_count(conn, where, params):
    sql = "SELECT COUNT(*) as count FROM receipts r"
    if where:
        sql += " WHERE " + " AND ".join(where)
    row = conn.execute(sql, params).fetchone()
    return row["count"] if row else 0


def get_all_receipts(
    store_filter=None,
    date_from=None,
    date_to=None,
    label_filter=None,
    category_filter=None,
    amount_min=None,
    amount_max=None,
    text_filter=None,
    payment_method=None,
    limit=None,
    offset=None,
    include_total=False,
):
    """Retrieve receipts with optional filtering and pagination."""
    where, params = _build_receipt_filters(
        store_filter=store_filter,
        date_from=date_from,
        date_to=date_to,
        label_filter=label_filter,
        category_filter=category_filter,
        amount_min=amount_min,
        amount_max=amount_max,
        text_filter=text_filter,
        payment_method=payment_method,
    )

    with get_db_connection() as conn:
        rows = _fetch_receipts_rows(conn, where, params, limit=limit, offset=offset)

        total_count = None
        if include_total:
            total_count = _fetch_receipts_count(conn, where, params)

        receipt_ids = [row["id"] for row in rows]
        if receipt_ids:
            placeholders = ", ".join("?" for _ in receipt_ids)
            all_items = conn.execute(
                f"""
                SELECT id, receipt_id, name, quantity, unit_price, line_total,
                       unit, currency, is_discount, tax_rate, tax_amount
                FROM receipt_items
                WHERE receipt_id IN ({placeholders})
                ORDER BY id
                """,
                receipt_ids,
            ).fetchall()
            item_ids = [row["id"] for row in all_items]
            categories_by_item = {}
            if item_ids:
                item_placeholders = ", ".join("?" for _ in item_ids)
                cat_rows = conn.execute(
                    f"""
                    SELECT ric.item_id, ric.allocation_amount, ric.allocation_ratio,
                           c.id as category_id, c.name as category_name, c.color as category_color
                    FROM receipt_item_categories ric
                    JOIN categories c ON ric.category_id = c.id
                    WHERE ric.item_id IN ({item_placeholders}) AND c.deleted_at IS NULL
                    """,
                    item_ids,
                ).fetchall()
                for row in cat_rows:
                    categories_by_item.setdefault(row["item_id"], []).append(
                        {
                            "category_id": row["category_id"],
                            "category_name": row["category_name"],
                            "category_color": row["category_color"],
                            "allocation_amount": row["allocation_amount"],
                            "allocation_ratio": row["allocation_ratio"],
                        }
                    )
            tax_rows = conn.execute(
                f"""
                SELECT receipt_id, tax_rate, tax_amount, taxable_amount, source, created_at
                FROM receipt_taxes
                WHERE receipt_id IN ({placeholders})
                ORDER BY id
                """,
                receipt_ids,
            ).fetchall()
        else:
            all_items = []
            categories_by_item = {}
            tax_rows = []

    # Group items by receipt_id
    items_by_receipt = {}
    for item in all_items:
        receipt_id = item['receipt_id']
        if receipt_id not in items_by_receipt:
            items_by_receipt[receipt_id] = []

        # Format item like the original JSON structure
        item_dict = {
            'id': item['id'],
            'name': item['name'],
            'price': f"{item['line_total']:.2f} €" if item['line_total'] else '',
            'quantity': item['quantity'],
            'unit_price': item['unit_price'],
            'line_total': item['line_total'],
            'unit': item['unit'],
            'currency': item['currency'],
            'is_discount': bool(item['is_discount']) if item['is_discount'] is not None else None,
            'tax_rate': item['tax_rate'],
            'tax_amount': item['tax_amount'],
            'categories': categories_by_item.get(item['id'], []),
        }
        items_by_receipt[receipt_id].append(item_dict)

    taxes_by_receipt = {}
    for tax in tax_rows:
        receipt_id = tax["receipt_id"]
        taxes_by_receipt.setdefault(receipt_id, []).append(
            {
                "tax_rate": tax["tax_rate"],
                "tax_amount": tax["tax_amount"],
                "taxable_amount": tax["taxable_amount"],
                "source": tax["source"],
                "created_at": tax["created_at"],
            }
        )

    receipts = [
        {
            'id': row['id'],
            'store_name': row['store_name'],
            'store_location': row['store_location'],
            'postal_code': row['postal_code'],
            'receipt_number': row['receipt_number'],
            'payment_method': row['payment_method'],
            'date': row['date'],
            'date_iso': row['date_iso'],
            'total': row['total'],
            # Read from receipt_items table, fallback to JSON
            'items': items_by_receipt.get(row['id'], json_loads_list(row['items'])),
            'labels': json_loads_list(row['labels']),
            'raw_text': row['raw_text'],
            'created_at': row['created_at'],
            'taxes': taxes_by_receipt.get(row['id'], []),
        }
        for row in rows
    ]

    if include_total:
        return receipts, total_count
    return receipts


def get_all_labels():
    """Get all unique labels from receipts."""
    with get_db_connection() as conn:
        category_rows = conn.execute(
            "SELECT name FROM categories WHERE deleted_at IS NULL ORDER BY name"
        ).fetchall()
        rows = conn.execute("SELECT labels FROM receipts WHERE labels IS NOT NULL").fetchall()

    all_labels = {row["name"] for row in category_rows}
    for row in rows:
        if row['labels']:
            labels = json_loads_list(row['labels'])
            all_labels.update(labels)

    return sorted(all_labels)


def get_categories(include_deleted=False):
    """Get categories with usage counts."""
    with get_db_connection() as conn:
        sql = """
            SELECT c.id, c.name, c.color, c.created_at, c.updated_at, c.deleted_at,
                   COUNT(rc.receipt_id) as usage_count
            FROM categories c
            LEFT JOIN receipt_categories rc ON rc.category_id = c.id
        """
        params = []
        if not include_deleted:
            sql += " WHERE c.deleted_at IS NULL"
        sql += " GROUP BY c.id ORDER BY c.name"
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "color": row["color"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "deleted_at": row["deleted_at"],
            "usage_count": row["usage_count"],
        }
        for row in rows
    ]


def create_category(name, color=None):
    """Create or restore a category."""
    if not name or not str(name).strip():
        raise ValueError("Category name required")
    clean_name = str(name).strip()
    now = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT id, deleted_at FROM categories WHERE name = ?",
            (clean_name,),
        ).fetchone()
        if existing:
            conn.execute(
                """
                UPDATE categories
                SET deleted_at = NULL,
                    color = COALESCE(?, color),
                    updated_at = ?
                WHERE id = ?
                """,
                (color, now, existing["id"]),
            )
            conn.commit()
            return existing["id"]

        cursor = conn.execute(
            """
            INSERT INTO categories (name, color, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (clean_name, color, now, now),
        )
        conn.commit()
        return cursor.lastrowid


def _rename_category_labels(conn, old_name, new_name):
    rows = conn.execute(
        "SELECT id, labels FROM receipts WHERE labels LIKE ?",
        (f'%"{old_name}"%',),
    ).fetchall()
    for row in rows:
        labels = json_loads_list(row["labels"])
        updated = [new_name if l == old_name else l for l in labels]
        if updated == labels:
            continue
        conn.execute(
            "UPDATE receipts SET labels = ? WHERE id = ?",
            (json_dumps_list(updated), row["id"]),
        )
        sync_receipt_categories(conn, row["id"], updated, source="manual")


def _remove_category_labels(conn, name):
    rows = conn.execute(
        "SELECT id, labels FROM receipts WHERE labels LIKE ?",
        (f'%"{name}"%',),
    ).fetchall()
    for row in rows:
        labels = json_loads_list(row["labels"])
        updated = [l for l in labels if l != name]
        if updated == labels:
            continue
        conn.execute(
            "UPDATE receipts SET labels = ? WHERE id = ?",
            (json_dumps_list(updated), row["id"]),
        )
        sync_receipt_categories(conn, row["id"], updated, source="manual")


def update_category(category_id, name=None, color=None):
    """Update category name/color."""
    if not category_id:
        raise ValueError("Category id required")
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, name FROM categories WHERE id = ?",
            (category_id,),
        ).fetchone()
        if not row:
            raise ValueError("Category not found")

        updates = []
        values = []
        old_name = row["name"]
        if name is not None:
            new_name = str(name).strip()
            if not new_name:
                raise ValueError("Category name required")
            conflict = conn.execute(
                "SELECT id FROM categories WHERE name = ? AND id != ? AND deleted_at IS NULL",
                (new_name, category_id),
            ).fetchone()
            if conflict:
                raise ValueError("Category name already exists")
            updates.append("name = ?")
            values.append(new_name)
        else:
            new_name = None

        if color is not None:
            updates.append("color = ?")
            values.append(color)

        if not updates:
            return False

        updates.append("updated_at = ?")
        values.append(now)
        values.append(category_id)

        conn.execute(
            f"UPDATE categories SET {', '.join(updates)} WHERE id = ?",
            values,
        )

        if new_name and new_name != old_name:
            _rename_category_labels(conn, old_name, new_name)

        conn.commit()
    return True


def delete_category(category_id):
    """Soft-delete category and remove labels from receipts."""
    if not category_id:
        raise ValueError("Category id required")
    now = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT id, name FROM categories WHERE id = ?",
            (category_id,),
        ).fetchone()
        if not row:
            raise ValueError("Category not found")

        conn.execute(
            "UPDATE categories SET deleted_at = ?, updated_at = ? WHERE id = ?",
            (now, now, category_id),
        )
        conn.execute(
            "DELETE FROM receipt_categories WHERE category_id = ?",
            (category_id,),
        )
        _remove_category_labels(conn, row["name"])
        conn.commit()
    return True


def get_category_rules(rule_type=None):
    """Get category rules."""
    with get_db_connection() as conn:
        sql = """
            SELECT r.id, r.name, r.rule_type, r.pattern, r.match_type,
                   r.priority, r.is_active, r.created_at, r.updated_at,
                   c.id as category_id, c.name as category_name, c.color as category_color
            FROM category_rules r
            JOIN categories c ON r.category_id = c.id
            WHERE c.deleted_at IS NULL
        """
        params = []
        if rule_type:
            sql += " AND r.rule_type = ?"
            params.append(rule_type)
        sql += " ORDER BY r.priority, r.id"
        rows = conn.execute(sql, params).fetchall()

    return [
        {
            "id": row["id"],
            "name": row["name"],
            "rule_type": row["rule_type"],
            "pattern": row["pattern"],
            "match_type": row["match_type"],
            "priority": row["priority"],
            "is_active": bool(row["is_active"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "category_id": row["category_id"],
            "category_name": row["category_name"],
            "category_color": row["category_color"],
        }
        for row in rows
    ]


def create_category_rule(
    category_id,
    rule_type,
    pattern,
    match_type="contains",
    priority=100,
    name=None,
    is_active=True,
):
    if not category_id:
        raise ValueError("Category id required")
    if not rule_type:
        raise ValueError("Rule type required")
    if not pattern or not str(pattern).strip():
        raise ValueError("Pattern required")
    clean_pattern = str(pattern).strip()
    clean_match = str(match_type or "contains").strip().lower()
    clean_type = str(rule_type).strip().lower()
    now = datetime.now(timezone.utc).isoformat()

    with get_db_connection() as conn:
        cat = conn.execute(
            "SELECT id FROM categories WHERE id = ? AND deleted_at IS NULL",
            (category_id,),
        ).fetchone()
        if not cat:
            raise ValueError("Category not found")
        cursor = conn.execute(
            """
            INSERT INTO category_rules
                (name, rule_type, pattern, match_type, category_id,
                 priority, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                clean_type,
                clean_pattern,
                clean_match,
                category_id,
                int(priority or 100),
                1 if is_active else 0,
                now,
                now,
            ),
        )
        conn.commit()
        return cursor.lastrowid


def update_category_rule(rule_id, updates):
    if not rule_id:
        raise ValueError("Rule id required")
    if not updates:
        return False
    fields = []
    values = []
    now = datetime.now(timezone.utc).isoformat()

    if "name" in updates:
        fields.append("name = ?")
        values.append(updates["name"])
    if "rule_type" in updates and updates["rule_type"]:
        fields.append("rule_type = ?")
        values.append(str(updates["rule_type"]).strip().lower())
    if "pattern" in updates and updates["pattern"]:
        fields.append("pattern = ?")
        values.append(str(updates["pattern"]).strip())
    if "match_type" in updates and updates["match_type"]:
        fields.append("match_type = ?")
        values.append(str(updates["match_type"]).strip().lower())
    if "priority" in updates and updates["priority"] is not None:
        fields.append("priority = ?")
        values.append(int(updates["priority"]))
    if "is_active" in updates and updates["is_active"] is not None:
        fields.append("is_active = ?")
        values.append(1 if updates["is_active"] else 0)
    if "category_id" in updates and updates["category_id"]:
        fields.append("category_id = ?")
        values.append(updates["category_id"])

    if not fields:
        return False

    fields.append("updated_at = ?")
    values.append(now)
    values.append(rule_id)

    with get_db_connection() as conn:
        conn.execute(
            f"UPDATE category_rules SET {', '.join(fields)} WHERE id = ?",
            values,
        )
        conn.commit()
    return True


def delete_category_rule(rule_id):
    if not rule_id:
        raise ValueError("Rule id required")
    with get_db_connection() as conn:
        conn.execute("DELETE FROM category_rules WHERE id = ?", (rule_id,))
        conn.commit()
    return True


def seed_default_category_rules(rules):
    """Seed default rules if none exist."""
    if not rules:
        return
    with get_db_connection() as conn:
        existing = conn.execute(
            "SELECT COUNT(*) as count FROM category_rules"
        ).fetchone()
        if existing["count"] > 0:
            return
        now = datetime.now(timezone.utc).isoformat()
        for category, patterns in rules.items():
            ensure_categories(conn, [category])
            cat_ids = get_category_ids(conn, [category])
            category_id = cat_ids.get(category)
            if not category_id:
                continue
            for pattern in patterns:
                conn.execute(
                    """
                    INSERT INTO category_rules
                        (rule_type, pattern, match_type, category_id,
                         priority, is_active, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ("store", str(pattern).strip(), "contains", category_id, 100, 1, now, now),
                )
        conn.commit()


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

        store_rows = conn.execute(
            """
            SELECT store_name, SUM(total) as total_sum, COUNT(*) as receipt_count
            FROM receipts
            WHERE total IS NOT NULL AND store_name IS NOT NULL AND store_name != ''
            GROUP BY store_name
            ORDER BY total_sum DESC
            LIMIT 5
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

    sorted_month_keys = sorted(monthly_totals.keys())
    current_month = sorted_month_keys[-1] if sorted_month_keys else None
    previous_month = sorted_month_keys[-2] if len(sorted_month_keys) > 1 else None
    current_total = monthly_totals.get(current_month, 0) if current_month else 0
    previous_total = monthly_totals.get(previous_month, 0) if previous_month else 0
    change = current_total - previous_total if previous_month else None
    percent_change = (
        round((change / previous_total) * 100, 2) if previous_total else None
    )

    month_avg = (
        (sum(monthly_totals.values()) / len(monthly_totals)) if monthly_totals else 0
    )
    alerts = []
    if previous_total and percent_change is not None and percent_change >= 20:
        alerts.append(
            {
                "type": "spike",
                "message": "Ausgaben sind deutlich gestiegen.",
                "current_month": current_month,
                "percent_change": percent_change,
            }
        )
    if month_avg and current_total > month_avg * 1.2:
        alerts.append(
            {
                "type": "above_average",
                "message": "Aktueller Monat liegt über dem Durchschnitt.",
                "current_month": current_month,
                "current_total": round(current_total, 2),
                "average_monthly": round(month_avg, 2),
            }
        )

    top_stores = [
        {
            "store_name": r["store_name"],
            "total": round(r["total_sum"] or 0.0, 2),
            "count": r["receipt_count"],
        }
        for r in store_rows
    ]

    return {
        'count': row['count'] or 0,
        'sum': round(row['total_sum'] or 0.0, 2),
        'average': round(row['total_avg'] or 0.0, 2),
        'monthly_totals': sorted_monthly,
        'category_totals': sorted_category,
        'trend': {
            'current_month': current_month,
            'previous_month': previous_month,
            'current_total': round(current_total, 2) if current_month else None,
            'previous_total': round(previous_total, 2) if previous_month else None,
            'change': round(change, 2) if change is not None else None,
            'percent_change': percent_change,
        },
        'top_stores': top_stores,
        'alerts': alerts,
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
            SELECT id, name, quantity, unit_price, line_total,
                   unit, currency, is_discount, tax_rate, tax_amount
            FROM receipt_items
            WHERE receipt_id = ?
            ORDER BY id
            """,
            (receipt_id,)
        ).fetchall()

        item_ids = [row["id"] for row in rows]
        categories_by_item = {}
        if item_ids:
            placeholders = ", ".join("?" for _ in item_ids)
            cat_rows = conn.execute(
                f"""
                SELECT ric.item_id, ric.allocation_amount, ric.allocation_ratio,
                       c.id as category_id, c.name as category_name, c.color as category_color
                FROM receipt_item_categories ric
                JOIN categories c ON ric.category_id = c.id
                WHERE ric.item_id IN ({placeholders}) AND c.deleted_at IS NULL
                """,
                item_ids,
            ).fetchall()
            for row in cat_rows:
                categories_by_item.setdefault(row["item_id"], []).append(
                    {
                        "category_id": row["category_id"],
                        "category_name": row["category_name"],
                        "category_color": row["category_color"],
                        "allocation_amount": row["allocation_amount"],
                        "allocation_ratio": row["allocation_ratio"],
                    }
                )
    
    return [
        {
            'id': row['id'],
            'name': row['name'],
            'quantity': row['quantity'],
            'unit_price': row['unit_price'],
            'line_total': row['line_total'],
            'unit': row['unit'],
            'currency': row['currency'],
            'is_discount': bool(row['is_discount']) if row['is_discount'] is not None else None,
            'tax_rate': row['tax_rate'],
            'tax_amount': row['tax_amount'],
            'categories': categories_by_item.get(row['id'], []),
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


def set_receipt_item_categories(item_id, allocations):
    """Replace categories for a receipt item."""
    if not item_id:
        raise ValueError("Item id required")
    allocations = allocations or []
    with get_db_connection() as conn:
        conn.execute(
            "DELETE FROM receipt_item_categories WHERE item_id = ?",
            (item_id,),
        )
        if not allocations:
            conn.commit()
            return True

        names = []
        ids = []
        for entry in allocations:
            if entry.get("category_id"):
                ids.append(entry.get("category_id"))
            elif entry.get("category_name"):
                names.append(entry.get("category_name"))

        if names:
            ensure_categories(conn, names)
        if ids:
            pass

        category_ids = get_category_ids(conn, names) if names else {}

        now = datetime.now(timezone.utc).isoformat()
        for entry in allocations:
            category_id = entry.get("category_id")
            if not category_id:
                category_id = category_ids.get(entry.get("category_name"))
            if not category_id:
                continue
            conn.execute(
                """
                INSERT OR REPLACE INTO receipt_item_categories
                    (item_id, category_id, allocation_amount, allocation_ratio, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    category_id,
                    entry.get("allocation_amount"),
                    entry.get("allocation_ratio"),
                    entry.get("source"),
                    now,
                ),
            )
        conn.commit()
    return True


def _rows_to_dicts(rows):
    return [dict(row) for row in rows]


def export_backup_data():
    """Export all data for backup/restore."""
    exported_at = datetime.now(timezone.utc).isoformat()
    with get_db_connection() as conn:
        receipts = conn.execute("SELECT * FROM receipts ORDER BY id").fetchall()
        items = conn.execute("SELECT * FROM receipt_items ORDER BY id").fetchall()
        categories = conn.execute("SELECT * FROM categories ORDER BY id").fetchall()
        category_rules = conn.execute("SELECT * FROM category_rules ORDER BY id").fetchall()
        receipt_categories = conn.execute(
            "SELECT * FROM receipt_categories ORDER BY receipt_id, category_id"
        ).fetchall()
        receipt_item_categories = conn.execute(
            "SELECT * FROM receipt_item_categories ORDER BY item_id, category_id"
        ).fetchall()
        receipt_taxes = conn.execute("SELECT * FROM receipt_taxes ORDER BY id").fetchall()

    return {
        "version": 1,
        "exported_at": exported_at,
        "receipts": _rows_to_dicts(receipts),
        "receipt_items": _rows_to_dicts(items),
        "categories": _rows_to_dicts(categories),
        "category_rules": _rows_to_dicts(category_rules),
        "receipt_categories": _rows_to_dicts(receipt_categories),
        "receipt_item_categories": _rows_to_dicts(receipt_item_categories),
        "receipt_taxes": _rows_to_dicts(receipt_taxes),
    }


def create_db_backup_file():
    """Create a temporary SQLite backup file and return its path."""
    if _is_ephemeral_db_path(DB_PATH):
        raise ValueError("Ephemeral database cannot be exported")
    with tempfile.NamedTemporaryFile(delete=False, suffix=".db") as tmp:
        backup_path = tmp.name
    source = _raw_connect()
    dest = sqlite3.connect(backup_path)
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    return backup_path


def import_backup_data(data):
    """Import backup data. Returns counts of imported records."""
    if not isinstance(data, dict):
        raise ValueError("Invalid backup data")

    receipts = data.get("receipts") or []
    items = data.get("receipt_items") or []
    categories = data.get("categories") or []
    category_rules = data.get("category_rules") or []
    receipt_categories = data.get("receipt_categories") or []
    receipt_item_categories = data.get("receipt_item_categories") or []
    receipt_taxes = data.get("receipt_taxes") or []

    imported = {
        "categories": 0,
        "receipts": 0,
        "receipt_items": 0,
        "category_rules": 0,
        "receipt_categories": 0,
        "receipt_item_categories": 0,
        "receipt_taxes": 0,
    }

    with get_db_connection() as conn:
        category_id_map = {}
        for cat in categories:
            name = str(cat.get("name") or "").strip()
            if not name:
                continue
            existing = conn.execute(
                "SELECT id FROM categories WHERE name = ?",
                (name,),
            ).fetchone()
            if existing:
                cat_id = existing["id"]
                conn.execute(
                    """
                    UPDATE categories
                    SET color = COALESCE(?, color),
                        deleted_at = ?,
                        updated_at = COALESCE(?, updated_at)
                    WHERE id = ?
                    """,
                    (
                        cat.get("color"),
                        cat.get("deleted_at"),
                        cat.get("updated_at"),
                        cat_id,
                    ),
                )
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO categories (name, color, created_at, updated_at, deleted_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        name,
                        cat.get("color"),
                        cat.get("created_at"),
                        cat.get("updated_at"),
                        cat.get("deleted_at"),
                    ),
                )
                cat_id = cursor.lastrowid
                imported["categories"] += 1
            category_id_map[cat.get("id")] = cat_id

        receipt_id_map = {}
        existing_item_counts = {}
        for receipt in receipts:
            created_at = receipt.get("created_at")
            store_name = receipt.get("store_name")
            total = receipt.get("total")
            date = receipt.get("date")
            existing = None
            if created_at:
                existing = conn.execute(
                    """
                    SELECT id FROM receipts
                    WHERE created_at = ? AND store_name IS ? AND total IS ? AND date IS ?
                    """,
                    (created_at, store_name, total, date),
                ).fetchone()
            if existing:
                receipt_id = existing["id"]
                receipt_id_map[receipt.get("id")] = receipt_id
                existing_count = conn.execute(
                    "SELECT COUNT(*) as count FROM receipt_items WHERE receipt_id = ?",
                    (receipt_id,),
                ).fetchone()
                existing_item_counts[receipt_id] = existing_count["count"]
                continue

            labels_value = receipt.get("labels")
            if isinstance(labels_value, str):
                labels_list = json_loads_list(labels_value)
                labels_json = labels_value
            else:
                labels_list = labels_value or []
                labels_json = json_dumps_list(labels_list)

            date_iso = receipt.get("date_iso") or parse_date_to_iso(date)

            cursor = conn.execute(
                """
                INSERT INTO receipts (
                    store_name, store_location, postal_code, receipt_number,
                    payment_method, date, date_iso, total, items, labels,
                    raw_text, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    store_name,
                    receipt.get("store_location"),
                    receipt.get("postal_code"),
                    receipt.get("receipt_number"),
                    receipt.get("payment_method"),
                    date,
                    date_iso,
                    receipt.get("total"),
                    receipt.get("items"),
                    labels_json,
                    receipt.get("raw_text"),
                    created_at,
                ),
            )
            receipt_id = cursor.lastrowid
            receipt_id_map[receipt.get("id")] = receipt_id
            sync_receipt_categories(conn, receipt_id, labels_list, source="import")
            imported["receipts"] += 1

        item_id_map = {}
        for item in items:
            old_receipt_id = item.get("receipt_id")
            receipt_id = receipt_id_map.get(old_receipt_id)
            if not receipt_id:
                continue
            if existing_item_counts.get(receipt_id):
                continue
            cursor = conn.execute(
                """
                INSERT INTO receipt_items (
                    receipt_id, name, quantity, unit_price, line_total,
                    unit, currency, is_discount, tax_rate, tax_amount
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    item.get("name"),
                    item.get("quantity"),
                    item.get("unit_price"),
                    item.get("line_total"),
                    item.get("unit"),
                    item.get("currency"),
                    item.get("is_discount"),
                    item.get("tax_rate"),
                    item.get("tax_amount"),
                ),
            )
            item_id_map[item.get("id")] = cursor.lastrowid
            imported["receipt_items"] += 1

        for rc in receipt_categories:
            receipt_id = receipt_id_map.get(rc.get("receipt_id"))
            category_id = category_id_map.get(rc.get("category_id"))
            if not receipt_id or not category_id:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO receipt_categories
                    (receipt_id, category_id, source, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    category_id,
                    rc.get("source"),
                    rc.get("created_at"),
                ),
            )
            imported["receipt_categories"] += 1

        for ric in receipt_item_categories:
            item_id = item_id_map.get(ric.get("item_id"))
            category_id = category_id_map.get(ric.get("category_id"))
            if not item_id or not category_id:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO receipt_item_categories
                    (item_id, category_id, allocation_amount, allocation_ratio, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    item_id,
                    category_id,
                    ric.get("allocation_amount"),
                    ric.get("allocation_ratio"),
                    ric.get("source"),
                    ric.get("created_at"),
                ),
            )
            imported["receipt_item_categories"] += 1

        for rule in category_rules:
            category_id = category_id_map.get(rule.get("category_id"))
            if not category_id:
                continue
            existing = conn.execute(
                """
                SELECT id FROM category_rules
                WHERE rule_type = ? AND pattern = ? AND match_type = ? AND category_id = ?
                """,
                (
                    rule.get("rule_type"),
                    rule.get("pattern"),
                    rule.get("match_type"),
                    category_id,
                ),
            ).fetchone()
            if existing:
                continue
            conn.execute(
                """
                INSERT INTO category_rules
                    (name, rule_type, pattern, match_type, category_id,
                     priority, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rule.get("name"),
                    rule.get("rule_type"),
                    rule.get("pattern"),
                    rule.get("match_type"),
                    category_id,
                    rule.get("priority"),
                    rule.get("is_active"),
                    rule.get("created_at"),
                    rule.get("updated_at"),
                ),
            )
            imported["category_rules"] += 1

        for tax in receipt_taxes:
            receipt_id = receipt_id_map.get(tax.get("receipt_id"))
            if not receipt_id:
                continue
            conn.execute(
                """
                INSERT INTO receipt_taxes
                    (receipt_id, tax_rate, tax_amount, taxable_amount, source, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt_id,
                    tax.get("tax_rate"),
                    tax.get("tax_amount"),
                    tax.get("taxable_amount"),
                    tax.get("source"),
                    tax.get("created_at"),
                ),
            )
            imported["receipt_taxes"] += 1

        conn.commit()

    return imported
