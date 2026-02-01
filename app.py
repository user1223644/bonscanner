"""
Minimal Receipt Scanner Backend
Flask API with Tesseract OCR
"""

import os
import re
import tempfile
from flask import Flask, request, jsonify
from flask_cors import CORS
import pytesseract
from PIL import Image

app = Flask(__name__)
CORS(app)


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
    for line in lines:
        match = re.match(item_pattern, line)
        if match:
            name = match.group(1).strip()
            price = match.group(2)
            # Filter out obvious non-items
            if len(name) > 2 and not re.match(r'^(total|summe|gesamt|mwst|ust|steuer)', name, re.IGNORECASE):
                items.append({'name': name, 'price': price})
    
    return {
        'date': date,
        'total': total,
        'items': items,
        'raw_text': text
    }


@app.route('/scan', methods=['POST'])
def scan_receipt():
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
        return jsonify(result)
    
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})


if __name__ == '__main__':
    app.run(debug=True, port=5000)
