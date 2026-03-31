"""Inventory routes — REST API endpoints."""

from flask import g, jsonify, request

from app.modules.auth_rbac.services import require_permission
from app.modules.inventory.blueprint import inventory_bp
from app.modules.inventory import services as inv


# ── Categories ────────────────────────────────────────────────────

@inventory_bp.route("/categories", methods=["GET"])
@require_permission("products", "read")
def list_categories():
    categories = inv.get_categories(g.tenant_id)
    return jsonify(success=True, data=categories)


@inventory_bp.route("/categories", methods=["POST"])
@require_permission("products", "create")
def create_category():
    data = request.get_json()
    if not data.get("name"):
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR", "message": "Nombre es requerido"
        }), 400

    cat = inv.create_category(
        tenant_id=g.tenant_id, name=data["name"],
        tax_type=data.get("tax_type", "iva_19"),
        parent_id=data.get("parent_id"),
    )
    return jsonify(success=True, data=cat), 201


# ── Products ──────────────────────────────────────────────────────

# QR Scan must be registered BEFORE /products/<product_id> to avoid Flask matching "scan" as ID
@inventory_bp.route("/products/scan", methods=["GET"])
@require_permission("products", "read")
def scan_product():
    qr = request.args.get("qr", "").strip()
    if not qr:
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR", "message": "Parámetro 'qr' es requerido"
        }), 400

    product = inv.get_product_by_qr(g.tenant_id, qr)
    if not product:
        return jsonify(success=False, error={
            "code": "PRODUCT_NOT_FOUND",
            "message": f"No se encontró producto con código QR: {qr}"
        }), 404

    return jsonify(success=True, data=product)


@inventory_bp.route("/products", methods=["GET"])
@require_permission("products", "read")
def list_products():
    result = inv.search_products(
        tenant_id=g.tenant_id,
        query=request.args.get("q", ""),
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 20)),
        category_id=request.args.get("category_id"),
        low_stock_only=request.args.get("low_stock") == "true",
        include_drafts=True,  # Inventory shows drafts so user can complete them
    )
    return jsonify(success=True, **result)


@inventory_bp.route("/products", methods=["POST"])
@require_permission("products", "create")
def create_product():
    data = request.get_json()
    required = ["name", "sale_price"]
    missing = [f for f in required if not data.get(f)]
    if missing:
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR",
            "message": f"Campos requeridos: {', '.join(missing)}",
        }), 400

    try:
        product = inv.create_product(
            tenant_id=g.tenant_id,
            created_by=g.current_user.id,
            name=data["name"],
            sale_price=data["sale_price"],
            purchase_price=data.get("purchase_price", 0),
            qr_code=data.get("qr_code"),
            barcode=data.get("barcode"),
            sku=data.get("sku"),
            category_id=data.get("category_id"),
            unit=data.get("unit", "unit"),
            tax_type=data.get("tax_type", "iva_19"),
            stock_minimum=data.get("stock_minimum", 0),
            initial_stock=data.get("initial_stock", 0),
            description=data.get("description", ""),
        )
        return jsonify(success=True, data=product), 201
    except Exception as e:
        return jsonify(success=False, error={
            "code": "PRODUCT_CREATE_ERROR", "message": str(e)
        }), 400


@inventory_bp.route("/products/<product_id>", methods=["GET"])
@require_permission("products", "read")
def get_product(product_id):
    product = inv.get_product_by_id(g.tenant_id, product_id)
    if not product:
        return jsonify(success=False, error={
            "code": "PRODUCT_NOT_FOUND", "message": "Producto no encontrado"
        }), 404
    return jsonify(success=True, data=product)


@inventory_bp.route("/products/<product_id>", methods=["PATCH"])
@require_permission("products", "update")
def update_product(product_id):
    data = request.get_json()
    try:
        product = inv.update_product(g.tenant_id, product_id, **data)
        return jsonify(success=True, data=product)
    except ValueError as e:
        return jsonify(success=False, error={
            "code": "PRODUCT_UPDATE_ERROR", "message": str(e)
        }), 404


# ── Import (OCR) ─────────────────────────────────────────────────

@inventory_bp.route("/import/ocr", methods=["POST"])
@require_permission("products", "create")
def import_ocr():
    """Upload an invoice image and extract products via OCR."""
    if 'image' not in request.files:
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR", "message": "Se requiere un archivo de imagen (campo 'image')"
        }), 400

    image_file = request.files['image']
    if not image_file.filename:
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR", "message": "Archivo vacío"
        }), 400

    try:
        from app.modules.inventory.ocr_service import process_invoice_image
        items = process_invoice_image(image_file)
        return jsonify(success=True, data=items, count=len(items))
    except Exception as e:
        return jsonify(success=False, error={
            "code": "OCR_ERROR", "message": f"Error procesando imagen: {str(e)}"
        }), 422


@inventory_bp.route("/import/confirm", methods=["POST"])
@require_permission("products", "create")
def import_confirm():
    """Confirm and create products from OCR results.
    items: [{"name": str, "quantity": float, "unit_cost": float, "sale_price": float}]
    """
    data = request.get_json()
    if not data.get("items"):
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR", "message": "items es requerido"
        }), 400

    created = []
    for item_data in data["items"]:
        try:
            product = inv.create_product(
                tenant_id=g.tenant_id, created_by=str(g.current_user.id),
                name=item_data["name"],
                sale_price=item_data.get("sale_price", item_data.get("unit_cost", 0) * 1.3),
                purchase_price=item_data.get("unit_cost", 0),
                initial_stock=item_data.get("quantity", 0),
            )
            created.append(product)
        except Exception as e:
            created.append({"name": item_data["name"], "error": str(e)})

    return jsonify(success=True, data=created, created_count=len([c for c in created if "error" not in c]))


# ── Stock ─────────────────────────────────────────────────────────

@inventory_bp.route("/stock", methods=["GET"])
@require_permission("inventory", "read")
def stock_levels():
    low_only = request.args.get("low_stock") == "true"
    levels = inv.get_stock_levels(g.tenant_id, low_stock_only=low_only)
    return jsonify(success=True, data=levels)


@inventory_bp.route("/stock/<product_id>/adjust", methods=["POST"])
@require_permission("inventory", "update")
def adjust_stock(product_id):
    """Adjust stock. Send new_quantity (absolute) OR quantity_delta (+/-)."""
    data = request.get_json()

    # Support quantity_delta as alternative to new_quantity
    if data.get("quantity_delta") is not None and data.get("new_quantity") is None:
        product = inv.get_product_by_id(g.tenant_id, product_id)
        if product:
            data["new_quantity"] = product["stock_current"] + float(data["quantity_delta"])

    if data.get("new_quantity") is None or not data.get("reason"):
        return jsonify(success=False, error={
            "code": "VALIDATION_ERROR",
            "message": "new_quantity y reason son requeridos"
        }), 400

    try:
        result = inv.adjust_stock(
            tenant_id=g.tenant_id, product_id=product_id,
            created_by=str(g.current_user.id),
            new_quantity=data["new_quantity"], reason=data["reason"],
        )
        return jsonify(success=True, data=result)
    except ValueError as e:
        return jsonify(success=False, error={
            "code": "STOCK_ADJUST_ERROR", "message": str(e)
        }), 404


# ── Movements ─────────────────────────────────────────────────────

@inventory_bp.route("/movements", methods=["GET"])
@require_permission("inventory", "read")
def list_movements():
    result = inv.get_movements(
        tenant_id=g.tenant_id,
        product_id=request.args.get("product_id"),
        page=int(request.args.get("page", 1)),
        per_page=int(request.args.get("per_page", 50)),
    )
    return jsonify(success=True, **result)
