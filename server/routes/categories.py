from flask import Blueprint, jsonify, request

from database import (
    create_category,
    create_category_rule,
    delete_category,
    delete_category_rule,
    get_categories,
    get_category_rules,
    seed_default_category_rules,
    update_category,
    update_category_rule,
)
from server.services.default_rules import DEFAULT_CATEGORY_RULES

categories_bp = Blueprint("categories", __name__)


@categories_bp.route("/categories", methods=["GET"])
def list_categories():
    """Get all categories."""
    return jsonify(get_categories())


@categories_bp.route("/categories", methods=["POST"])
def create_category_route():
    """Create a category."""
    data = request.get_json() or {}
    name = data.get("name", "").strip()
    color = data.get("color")
    try:
        category_id = create_category(name, color=color)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"id": category_id, "name": name, "color": color})


@categories_bp.route("/categories/<int:category_id>", methods=["PATCH"])
def update_category_route(category_id):
    """Update a category."""
    data = request.get_json() or {}
    name = data.get("name")
    color = data.get("color")
    try:
        update_category(category_id, name=name, color=color)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True})


@categories_bp.route("/categories/<int:category_id>", methods=["DELETE"])
def delete_category_route(category_id):
    """Delete a category (soft delete)."""
    try:
        delete_category(category_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True})


@categories_bp.route("/category-rules", methods=["GET"])
def list_category_rules():
    """Get category rules."""
    rule_type = request.args.get("rule_type")
    return jsonify(get_category_rules(rule_type=rule_type))


@categories_bp.route("/category-rules", methods=["POST"])
def create_category_rule_route():
    """Create a category rule."""
    data = request.get_json() or {}
    try:
        rule_id = create_category_rule(
            category_id=data.get("category_id"),
            rule_type=data.get("rule_type"),
            pattern=data.get("pattern"),
            match_type=data.get("match_type") or "contains",
            priority=data.get("priority") or 100,
            name=data.get("name"),
            is_active=data.get("is_active", True),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"id": rule_id})


@categories_bp.route("/category-rules/<int:rule_id>", methods=["PATCH"])
def update_category_rule_route(rule_id):
    """Update a category rule."""
    data = request.get_json() or {}
    try:
        update_category_rule(
            rule_id,
            category_id=data.get("category_id"),
            rule_type=data.get("rule_type"),
            pattern=data.get("pattern"),
            match_type=data.get("match_type"),
            priority=data.get("priority"),
            name=data.get("name"),
            is_active=data.get("is_active"),
        )
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True})


@categories_bp.route("/category-rules/<int:rule_id>", methods=["DELETE"])
def delete_category_rule_route(rule_id):
    """Delete a category rule."""
    try:
        delete_category_rule(rule_id)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify({"success": True})


@categories_bp.route("/category-rules/seed", methods=["POST"])
def seed_category_rules_route():
    """Seed default category rules if none exist."""
    seed_default_category_rules(DEFAULT_CATEGORY_RULES)
    return jsonify({"success": True})
