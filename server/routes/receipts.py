from flask import Blueprint, jsonify, request

from database import (
    add_receipt_item,
    delete_receipt_item,
    get_all_receipts,
    get_receipt_items,
    save_receipt,
    set_receipt_item_categories,
    update_receipt_item,
    update_receipt,
    update_receipt_labels,
)
from extractor import extract_receipt_data
from server.services.categorization import apply_auto_categorization
from server.services.ocr import ocr_image_file
from server.utils.labels import parse_labels_from_request

receipts_bp = Blueprint("receipts", __name__)


@receipts_bp.route("/upload", methods=["POST"])
def upload_receipt():
    """Process uploaded receipt image."""
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded"}), 400

    file = request.files["image"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    labels = parse_labels_from_request(request)

    try:
        text = ocr_image_file(file)
        result = extract_receipt_data(text)

        store_name = result.get("store_name", "")
        if labels:
            final_labels = labels
        else:
            final_labels = apply_auto_categorization(
                store_name,
                labels,
                raw_text=result.get("raw_text"),
                payment_method=result.get("payment_method"),
                items=result.get("items"),
            )

        result["labels"] = final_labels
        receipt_id = save_receipt(result, labels=final_labels)
        result["id"] = receipt_id
        return jsonify(result)

    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@receipts_bp.route("/scan", methods=["POST"])
def scan_receipt():
    """Alias for /upload (backwards compatibility)."""
    return upload_receipt()


@receipts_bp.route("/receipts", methods=["GET"])
def list_receipts():
    """List all stored receipts with optional filtering."""
    store_filter = request.args.get("store")
    date_from = request.args.get("date_from")
    date_to = request.args.get("date_to")
    label_filter = request.args.get("label")
    category_filter = request.args.get("category")
    text_filter = request.args.get("text") or request.args.get("q")
    payment_method = request.args.get("payment_method")

    amount_min = request.args.get("amount_min")
    amount_max = request.args.get("amount_max")
    try:
        amount_min = float(amount_min) if amount_min is not None else None
    except ValueError:
        amount_min = None
    try:
        amount_max = float(amount_max) if amount_max is not None else None
    except ValueError:
        amount_max = None

    page = request.args.get("page")
    page_size = request.args.get("page_size")
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
        limit = max(1, min(size_val, 200))
        offset = (page_val - 1) * limit

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
        receipts = receipts_result
        total_count = None

    response = jsonify(receipts)
    if include_total and total_count is not None:
        response.headers["X-Total-Count"] = str(total_count)
    return response


@receipts_bp.route("/receipts/<int:receipt_id>/labels", methods=["PATCH"])
def patch_receipt_labels(receipt_id):
    """Update labels for receipt."""
    data = request.get_json() or {}
    labels = data.get("labels")
    if labels is None:
        return jsonify({"error": "No labels provided"}), 400

    update_receipt_labels(receipt_id, labels)
    receipts = get_all_receipts()[0]
    receipt = next((r for r in receipts if r["id"] == receipt_id), None)
    if not receipt:
        return jsonify({"error": "Receipt not found"}), 404
    return jsonify(receipt)


@receipts_bp.route("/receipts/<int:receipt_id>", methods=["PATCH"])
def patch_receipt(receipt_id):
    """Update receipt fields."""
    data = request.get_json()
    update_receipt(receipt_id, data)
    return jsonify({"success": True})


@receipts_bp.route("/receipts/<int:receipt_id>/items", methods=["GET"])
def list_receipt_items(receipt_id):
    """Get items for a receipt."""
    items = get_receipt_items(receipt_id)
    return jsonify(items)


@receipts_bp.route("/receipts/<int:receipt_id>/items", methods=["POST"])
def add_receipt_item_route(receipt_id):
    """Add a new item to a receipt."""
    data = request.get_json() or {}
    name = data.get("name")
    price = data.get("price")
    quantity = data.get("quantity")
    unit_price = data.get("unit_price")
    total_price = data.get("total_price")
    discount = data.get("discount")
    vat_rate = data.get("vat_rate")
    vat_amount = data.get("vat_amount")

    if not name or price is None:
        return jsonify({"error": "Name and price are required"}), 400

    item_id = add_receipt_item(
        receipt_id,
        name,
        price,
        quantity=quantity,
        unit_price=unit_price,
        total_price=total_price,
        discount=discount,
        vat_rate=vat_rate,
        vat_amount=vat_amount,
    )
    items = get_receipt_items(receipt_id)
    return jsonify({"success": True, "items": items, "item_id": item_id})


@receipts_bp.route("/receipts/<int:receipt_id>/items/<int:item_id>", methods=["DELETE"])
def delete_receipt_item_route(receipt_id, item_id):
    """Delete an item from a receipt."""
    success = delete_receipt_item(item_id)
    if not success:
        return jsonify({"error": "Item not found"}), 404

    items = get_receipt_items(receipt_id)
    return jsonify({"success": True, "items": items})


@receipts_bp.route("/receipts/<int:receipt_id>/items/<int:item_id>", methods=["PATCH"])
def update_receipt_item_route(receipt_id, item_id):
    """Update an item for a receipt."""
    data = request.get_json() or {}
    try:
        updated_receipt_id = update_receipt_item(item_id, data)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    if updated_receipt_id != receipt_id:
        return jsonify({"error": "Item does not belong to receipt"}), 404

    items = get_receipt_items(receipt_id)
    return jsonify({"success": True, "items": items})


@receipts_bp.route("/receipts/<int:receipt_id>/items/<int:item_id>/categories", methods=["PATCH"])
def update_item_categories(receipt_id, item_id):
    """Update categories for a receipt item."""
    data = request.get_json() or {}
    categories = data.get("categories", [])
    try:
        set_receipt_item_categories(item_id, categories)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    items = get_receipt_items(receipt_id)
    return jsonify({"success": True, "items": items})
