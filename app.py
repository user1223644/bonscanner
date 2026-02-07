"""
Receipt Scanner API
Flask backend for OCR-based receipt processing.
"""

import os
import tempfile
from flask import Flask, request, jsonify
from flask_cors import CORS
import pytesseract
from PIL import Image

from database import (
    init_db, save_receipt, get_all_receipts, get_receipt_stats,
    get_all_labels, update_receipt_labels, add_receipt_item,
    delete_receipt_item, get_receipt_items
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

def apply_auto_categorization(store_name, existing_labels):
    """Apply auto-categorization rules based on store name.
    
    Args:
        store_name: Normalized store name from receipt
        existing_labels: List of labels already assigned
        
    Returns:
        Updated list of labels with auto-applied categories
    """
    labels = list(existing_labels) if existing_labels else []
    
    if not store_name:
        return labels
    
    store_lower = store_name.lower()
    
    for category, patterns in CATEGORIZATION_RULES.items():
        # Check if any pattern matches the store name
        if any(pattern in store_lower for pattern in patterns):
            # Only add if not already present
            if category not in labels:
                labels.append(category)
    
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
        labels = apply_auto_categorization(store_name, labels)
        
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
        label: Filter by category label
    """
    store_filter = request.args.get('store')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    label_filter = request.args.get('label')
    
    receipts = get_all_receipts(
        store_filter=store_filter,
        date_from=date_from,
        date_to=date_to,
        label_filter=label_filter
    )
    return jsonify(receipts)


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


@app.route('/stats', methods=['GET'])
def receipt_stats():
    """Get receipt statistics."""
    return jsonify(get_receipt_stats())


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


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})


# Initialize database on startup
init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)
