import csv
import io
import json
import os

from flask import Blueprint, jsonify, make_response, request, send_file, after_this_request

from database import (
    create_db_backup_file,
    export_backup_data,
    get_all_receipts,
    import_backup_data,
)

exports_bp = Blueprint("exports", __name__)


@exports_bp.route("/export/json", methods=["GET"])
def export_json():
    """Export full backup as JSON."""
    data = export_backup_data()
    payload = json.dumps(data, ensure_ascii=False, indent=2)
    response = make_response(payload)
    response.headers["Content-Type"] = "application/json"
    response.headers["Content-Disposition"] = "attachment; filename=bonscanner-backup.json"
    return response


@exports_bp.route("/export/csv", methods=["GET"])
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
    for receipt in receipts:
        writer.writerow([
            receipt.get("id"),
            receipt.get("store_name"),
            receipt.get("date"),
            receipt.get("total"),
            receipt.get("payment_method"),
            ", ".join(receipt.get("labels") or []),
            receipt.get("created_at"),
        ])
    response = make_response(output.getvalue())
    response.headers["Content-Type"] = "text/csv"
    response.headers["Content-Disposition"] = "attachment; filename=bonscanner-receipts.csv"
    return response


@exports_bp.route("/export/db", methods=["GET"])
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


@exports_bp.route("/import/json", methods=["POST"])
def import_json():
    """Import JSON backup."""
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    try:
        data = json.load(file)
    except json.JSONDecodeError:
        return jsonify({"error": "Invalid JSON"}), 400

    try:
        result = import_backup_data(data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"success": True, "imported": result})
