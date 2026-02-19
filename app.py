"""
Receipt Scanner API
Flask backend for OCR-based receipt processing.
"""

import csv
import io
import json
import os
from flask import Flask, request, jsonify, make_response, send_file, after_this_request
from flask_cors import CORS

from database import (
    init_db, get_all_receipts, get_receipt_stats,
    get_all_labels, seed_default_category_rules,
    export_backup_data, create_db_backup_file, import_backup_data,
)
from server.services.default_rules import DEFAULT_CATEGORY_RULES
from server.routes.categories import categories_bp
from server.routes.receipts import receipts_bp

app = Flask(__name__)
CORS(app)
app.register_blueprint(categories_bp)
app.register_blueprint(receipts_bp)



@app.route('/labels', methods=['GET'])
def list_labels():
    """Get all unique labels."""
    return jsonify(get_all_labels())


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


@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint."""
    return jsonify({'status': 'ok'})


# Initialize database on startup
init_db()
seed_default_category_rules(DEFAULT_CATEGORY_RULES)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
