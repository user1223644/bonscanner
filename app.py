"""
Receipt Scanner API
Flask backend for OCR-based receipt processing.
"""

import os
import re
import csv
import io
import json
import tempfile
from flask import Flask, request, jsonify, make_response, send_file, after_this_request
from flask_cors import CORS
import pytesseract
from PIL import Image

from database import (
    init_db, save_receipt, get_all_receipts, get_receipt_stats,
    get_all_labels, update_receipt_labels, add_receipt_item,
    delete_receipt_item, get_receipt_items, get_categories,
    create_category, update_category, delete_category,
    get_category_rules, create_category_rule, update_category_rule,
    delete_category_rule, seed_default_category_rules,
    export_backup_data, create_db_backup_file, import_backup_data,
    set_receipt_item_categories
)
from extractor import extract_receipt_data

app = Flask(__name__)
CORS(app)

# Auto-categorization rules: store name patterns -> category labels
CATEGORIZATION_RULES = {
    'Lebensmittel': ['rewe', 'lidl', 'aldi', 'edeka', 'netto', 'penny', 'kaufland'],
    'Transport': ['shell', 'aral', 'esso', 'total', 'jet'],
    'Gesundheit': ['apotheke', 'dm', 'rossmann'],
    'Haushalt': ['bauhaus', 'obi', 'hornbach', 'ikea'],
    'Elektronik': ['media markt', 'saturn', 'conrad'],
}

def apply_auto_categorization(store_name, existing_labels, raw_text=None, payment_method=None, items=None):
    """Apply auto-categorization rules based on configured rules."""
    labels = list(existing_labels) if existing_labels else []
    rules = get_category_rules()

    if not rules:
        return labels

    store_value = (store_name or "").lower()
    text_value = (raw_text or "").lower()
    payment_value = (payment_method or "").lower()
    item_names = [str(it.get("name", "")).lower() for it in (items or []) if it.get("name")]

    for rule in rules:
        if not rule.get("is_active"):
            continue
        category_name = rule.get("category_name")
        if not category_name or category_name in labels:
            continue

        rule_type = (rule.get("rule_type") or "").lower()
        pattern = str(rule.get("pattern") or "").lower()
        match_type = (rule.get("match_type") or "contains").lower()

        def match_value(value):
            if not value:
                return False
            if match_type == "equals":
                return value == pattern
            if match_type == "regex":
                try:
                    return re.search(pattern, value, re.IGNORECASE) is not None
                except re.error:
                    return False
            return pattern in value

        matched = False
        if rule_type == "store":
            matched = match_value(store_value)
        elif rule_type == "keyword":
            matched = match_value(text_value)
        elif rule_type == "payment":
            matched = match_value(payment_value)
        elif rule_type == "item":
            matched = any(match_value(name) for name in item_names)

        if matched:
            labels.append(category_name)

    return labels

def parse_labels_from_request(req):
    """Extract labels from form data (list or comma-separated)."""
    labels = req.form.getlist('labels')
    if not labels and req.form.get('labels'):
        labels = [l.strip() for l in req.form.get('labels').split(',') if l.strip()]
    return labels


def ocr_image_file(file_obj):
    """Run OCR on an uploaded image file and return extracted text."""
    with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
        file_obj.save(tmp.name)
        image = Image.open(tmp.name)
        text = pytesseract.image_to_string(image, lang='deu+eng')
        os.unlink(tmp.name)
    return text


@app.route('/upload', methods=['POST'])
def upload_receipt():
    """Process uploaded receipt image."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    labels = parse_labels_from_request(request)

    try:
        text = ocr_image_file(file)
        result = extract_receipt_data(text)
        
        # Apply auto-categorization based on store name
        store_name = result.get('store_name', '')
        labels = apply_auto_categorization(
            store_name,
            labels,
            raw_text=result.get('raw_text'),
            payment_method=result.get('payment_method'),
            items=result.get('items'),
        )
        
        result['labels'] = labels
        save_receipt(result, labels=labels)
        return jsonify(result)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/scan', methods=['POST'])
def scan_receipt():
    """Alias for /upload (backwards compatibility)."""
    return upload_receipt()


@app.route('/receipts', methods=['GET'])
def list_receipts():
    """List all stored receipts with optional filtering.
    
    Query params:
        store: Filter by store name
        date_from: Filter from date (YYYY-MM-DD)
        date_to: Filter to date (YYYY-MM-DD)
        label: Filter by category label (legacy)
        category: Filter by category label
        amount_min: Minimum total amount
        amount_max: Maximum total amount
        text: Full-text search across receipt fields and items
        payment_method: Filter by payment method
        page: Page number (1-based)
        page_size: Page size
    """
    store_filter = request.args.get('store')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    label_filter = request.args.get('label')
    category_filter = request.args.get('category')
    text_filter = request.args.get('text') or request.args.get('q')
    payment_method = request.args.get('payment_method')

    amount_min = request.args.get('amount_min')
    amount_max = request.args.get('amount_max')
    try:
        amount_min = float(amount_min) if amount_min is not None else None
    except ValueError:
        amount_min = None
    try:
        amount_max = float(amount_max) if amount_max is not None else None
    except ValueError:
        amount_max = None

    page = request.args.get('page')
    page_size = request.args.get('page_size')
    limit = None
    offset = None
    include_total = False
    if page is not None or page_size is not None:
        include_total = True
        try:
            page_val = max(1, int(page or 1))
        except ValueError:
            page_val = 1
        try:
            size_val = int(page_size or 25)
        except ValueError:
            size_val = 25
        size_val = max(1, min(size_val, 200))
        limit = size_val
        offset = (page_val - 1) * size_val

    receipts_result = get_all_receipts(
        store_filter=store_filter,
        date_from=date_from,
        date_to=date_to,
        label_filter=label_filter,
        category_filter=category_filter,
        amount_min=amount_min,
        amount_max=amount_max,
        text_filter=text_filter,
        payment_method=payment_method,
        limit=limit,
        offset=offset,
        include_total=include_total,
    )
    if include_total:
        receipts, total_count = receipts_result
    else:
        receipts, total_count = receipts_result, None

    response = jsonify(receipts)
    if total_count is not None:
        response.headers["X-Total-Count"] = str(total_count)
    return response


@app.route('/receipts/<int:receipt_id>/labels', methods=['PATCH'])
def patch_receipt_labels(receipt_id):
    """Update labels for a specific receipt."""
    data = request.get_json()
    labels = data.get('labels', [])
    update_receipt_labels(receipt_id, labels)
    return jsonify({'success': True, 'labels': labels})


@app.route('/receipts/<int:receipt_id>', methods=['PATCH'])
def patch_receipt(receipt_id):
    """Update receipt fields."""
    data = request.get_json()
    from database import update_receipt
    update_receipt(receipt_id, data)
    return jsonify({'success': True})


@app.route('/labels', methods=['GET'])
def list_labels():
    """Get all unique labels."""
    return jsonify(get_all_labels())


@app.route('/categories', methods=['GET'])
def list_categories():
    """Get all categories."""
    return jsonify(get_categories())


@app.route('/categories', methods=['POST'])
def create_category_route():
    """Create a category."""
    data = request.get_json() or {}
    name = data.get('name', '').strip()
    color = data.get('color')
    try:
        category_id = create_category(name, color=color)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'id': category_id, 'name': name, 'color': color})


@app.route('/categories/<int:category_id>', methods=['PATCH'])
def update_category_route(category_id):
    """Update a category."""
    data = request.get_json() or {}
    name = data.get('name')
    color = data.get('color')
    try:
        update_category(category_id, name=name, color=color)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'success': True})


@app.route('/categories/<int:category_id>', methods=['DELETE'])
def delete_category_route(category_id):
    """Delete a category (soft delete)."""
    try:
        delete_category(category_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'success': True})


@app.route('/category-rules', methods=['GET'])
def list_category_rules():
    """Get category rules."""
    rule_type = request.args.get('rule_type')
    return jsonify(get_category_rules(rule_type=rule_type))


@app.route('/category-rules', methods=['POST'])
def create_category_rule_route():
    """Create a category rule."""
    data = request.get_json() or {}
    try:
        rule_id = create_category_rule(
            category_id=data.get('category_id'),
            rule_type=data.get('rule_type'),
            pattern=data.get('pattern'),
            match_type=data.get('match_type') or 'contains',
            priority=data.get('priority') or 100,
            name=data.get('name'),
            is_active=data.get('is_active', True),
        )
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'id': rule_id})


@app.route('/category-rules/<int:rule_id>', methods=['PATCH'])
def update_category_rule_route(rule_id):
    """Update a category rule."""
    data = request.get_json() or {}
    try:
        update_category_rule(rule_id, data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'success': True})


@app.route('/category-rules/<int:rule_id>', methods=['DELETE'])
def delete_category_rule_route(rule_id):
    """Delete a category rule."""
    try:
        delete_category_rule(rule_id)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'success': True})


@app.route('/stats', methods=['GET'])
def receipt_stats():
    """Get receipt statistics."""
    return jsonify(get_receipt_stats())


@app.route('/export/json', methods=['GET'])
def export_json():
    """Export full backup as JSON."""
    data = export_backup_data()
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    response = make_response(payload)
    response.headers["Content-Type"] = "application/json"
    response.headers["Content-Disposition"] = "attachment; filename=bonscanner-backup.json"
    return response


@app.route('/export/csv', methods=['GET'])
def export_csv():
    """Export receipts as CSV."""
    receipts = get_all_receipts()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id",
        "store_name",
        "date",
        "total",
        "payment_method",
        "labels",
        "created_at",
    ])
    for r in receipts:
        writer.writerow([
            r.get("id"),
            r.get("store_name"),
            r.get("date"),
            r.get("total"),
            r.get("payment_method"),
            ", ".join(r.get("labels") or []),
            r.get("created_at"),
        ])
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = "attachment; filename=bonscanner-receipts.csv"
    return response


@app.route('/export/db', methods=['GET'])
def export_db():
    """Download SQLite database backup."""
    try:
        backup_path = create_db_backup_file()
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    @after_this_request
    def cleanup(response):
        try:
            os.unlink(backup_path)
        except OSError:
            pass
        return response

    return send_file(backup_path, as_attachment=True, download_name="bonscanner-backup.db")


@app.route('/import/json', methods=['POST'])
def import_json():
    """Import backup JSON."""
    data = None
    if request.is_json:
        data = request.get_json()
    elif 'file' in request.files:
        file = request.files['file']
        if file and file.filename:
            try:
                data = json.loads(file.read().decode('utf-8'))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                return jsonify({'error': f'Invalid JSON: {exc}'}), 400
    if data is None:
        return jsonify({'error': 'No JSON payload provided'}), 400

    try:
        result = import_backup_data(data)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    return jsonify({'success': True, 'imported': result})


@app.route('/receipts/<int:receipt_id>/items', methods=['GET'])
def list_receipt_items(receipt_id):
    """Get all items for a specific receipt."""
    items = get_receipt_items(receipt_id)
    return jsonify(items)


@app.route('/receipts/<int:receipt_id>/items', methods=['POST'])
def add_item(receipt_id):
    """Add an item to a receipt."""
    data = request.get_json()
    name = data.get('name', '').strip()
    price = data.get('price', 0)
    
    if not name:
        return jsonify({'error': 'Item name required'}), 400
    
    add_receipt_item(receipt_id, name, price)
    items = get_receipt_items(receipt_id)
    return jsonify({'success': True, 'items': items})


@app.route('/receipts/<int:receipt_id>/items/<int:item_id>', methods=['DELETE'])
def remove_item(receipt_id, item_id):
    """Delete an item from a receipt."""
    success = delete_receipt_item(item_id)
    if not success:
        return jsonify({'error': 'Item not found'}), 404
    
    items = get_receipt_items(receipt_id)
    return jsonify({'success': True, 'items': items})


@app.route('/receipts/<int:receipt_id>/items/<int:item_id>/categories', methods=['PATCH'])
def update_item_categories(receipt_id, item_id):
    """Update categories for a receipt item."""
    data = request.get_json() or {}
    categories = data.get('categories', [])
    try:
        set_receipt_item_categories(item_id, categories)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    items = get_receipt_items(receipt_id)
    return jsonify({'success': True, 'items': items})


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})


# Initialize database on startup
init_db()
seed_default_category_rules(CATEGORIZATION_RULES)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
