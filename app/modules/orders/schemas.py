"""Order marshmallow schemas for request validation."""

from marshmallow import Schema, fields, validate


class OrderItemInputSchema(Schema):
    product_id = fields.UUID(required=True)
    quantity = fields.Float(required=True, validate=validate.Range(min=0.01))
    notes = fields.String(load_default=None, validate=validate.Length(max=255))


class CreateOrderSchema(Schema):
    items = fields.List(fields.Nested(OrderItemInputSchema), required=True, validate=validate.Length(min=1))
    vertical_type = fields.String(
        load_default="restaurant",
        validate=validate.OneOf(["restaurant", "cafe", "drugstore", "catering"]),
    )
    table_number = fields.String(load_default=None, validate=validate.Length(max=50))
    customer_name = fields.String(load_default=None, validate=validate.Length(max=200))
    customer_phone = fields.String(load_default=None, validate=validate.Length(max=30))
    delivery_address = fields.String(load_default=None)
    notes = fields.String(load_default=None)
    assigned_to = fields.UUID(load_default=None)
    is_wholesale = fields.Boolean(load_default=False)


class UpdateOrderStateSchema(Schema):
    status = fields.String(
        required=True,
        validate=validate.OneOf(["confirmed", "in_preparation", "ready"]),
    )
    reason = fields.String(load_default=None, validate=validate.Length(max=255))


class CloseOrderSchema(Schema):
    payment_method = fields.String(
        required=True,
        validate=validate.OneOf(["cash", "card", "transfer", "nequi", "daviplata"]),
    )
    received_amount = fields.Float(load_default=None)
    reference = fields.String(load_default=None)
    idempotency_key = fields.String(required=True)
    voucher_code = fields.String(load_default=None)
    voucher_amount = fields.Float(load_default=None)


class CancelOrderSchema(Schema):
    reason = fields.String(required=True, validate=validate.Length(min=1, max=255))
