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

from database import init_db, save_receipt, get_all_receipts, get_receipt_stats
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

    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
            file.save(tmp.name)
            image = Image.open(tmp.name)
            text = pytesseract.image_to_string(image, lang='deu+eng')
            os.unlink(tmp.name)

        result = extract_receipt_data(text)
        save_receipt(result)
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
