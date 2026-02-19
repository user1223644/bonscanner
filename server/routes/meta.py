from flask import Blueprint, jsonify

from database import get_all_labels, get_receipt_stats

meta_bp = Blueprint("meta", __name__)


@meta_bp.route("/labels", methods=["GET"])
def list_labels():
    """Get all unique labels."""
    return jsonify(get_all_labels())


@meta_bp.route("/stats", methods=["GET"])
def receipt_stats():
    """Get receipt statistics."""
    return jsonify(get_receipt_stats())


@meta_bp.route("/health", methods=["GET"])
def health_check():
    """Health check endpoint."""
    return jsonify({"status": "ok"})
