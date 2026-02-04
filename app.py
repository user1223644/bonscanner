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
    get_all_labels, update_receipt_labels
)
from extractor import extract_receipt_data

app = Flask(__name__)
CORS(app)


@app.route('/upload', methods=['POST'])
def upload_receipt():
    """Process uploaded receipt image."""
    if 'image' not in request.files:
        return jsonify({'error': 'No image uploaded'}), 400

    file = request.files['image']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Get labels from form data
    labels = request.form.getlist('labels')
    if not labels and request.form.get('labels'):
        # Handle comma-separated labels
        labels = [l.strip() for l in request.form.get('labels').split(',') if l.strip()]

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            file.save(tmp.name)
            image = Image.open(tmp.name)
            text = pytesseract.image_to_string(image, lang='deu+eng')
            os.unlink(tmp.name)

        result = extract_receipt_data(text)
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
    """List all stored receipts."""
    return jsonify(get_all_receipts())


@app.route('/receipts/<int:receipt_id>/labels', methods=['PATCH'])
def patch_receipt_labels(receipt_id):
    """Update labels for a specific receipt."""
    data = request.get_json()
    labels = data.get('labels', [])
    update_receipt_labels(receipt_id, labels)
    return jsonify({'success': True, 'labels': labels})


@app.route('/labels', methods=['GET'])
def list_labels():
    """Get all unique labels."""
    return jsonify(get_all_labels())


@app.route('/stats', methods=['GET'])
def receipt_stats():
    """Get receipt statistics."""
    return jsonify(get_receipt_stats())


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})


# Initialize database on startup
init_db()

if __name__ == '__main__':
    app.run(debug=True, port=5000)

