"""Voucher marshmallow schemas for request validation."""

from marshmallow import Schema, fields, validate


class CreateVoucherTypeSchema(Schema):
    name = fields.String(required=True, validate=validate.Length(min=1, max=100))
    face_value = fields.Float(required=True, validate=validate.Range(min=0.01))
    validity_days = fields.Integer(required=True, validate=validate.Range(min=90))
    max_issuable = fields.Integer(load_default=None, validate=validate.Range(min=1))
    color_hex = fields.String(load_default=None, validate=validate.Regexp(r"^#[0-9A-Fa-f]{6}$"))
    design_template = fields.String(
        load_default="default",
        validate=validate.OneOf(["default", "compact", "premium"]),
    )
    notes = fields.String(load_default=None, validate=validate.Length(max=500))


class UpdateVoucherTypeSchema(Schema):
    name = fields.String(validate=validate.Length(min=1, max=100))
    validity_days = fields.Integer(validate=validate.Range(min=90))
    max_issuable = fields.Integer(validate=validate.Range(min=1), allow_none=True)
    status = fields.String(validate=validate.OneOf(["active", "inactive"]))
    color_hex = fields.String(validate=validate.Regexp(r"^#[0-9A-Fa-f]{6}$"), allow_none=True)
    design_template = fields.String(validate=validate.OneOf(["default", "compact", "premium"]))
    notes = fields.String(validate=validate.Length(max=500), allow_none=True)


class EmitVoucherSchema(Schema):
    type_id = fields.UUID(required=True)
    quantity = fields.Integer(load_default=1, validate=validate.Range(min=1, max=200))
    idempotency_key = fields.String(load_default=None)


class SellVoucherSchema(Schema):
    code = fields.String(required=True, validate=validate.Length(min=10, max=25))
    sale_id = fields.UUID(required=True)
    buyer_name = fields.String(load_default=None, validate=validate.Length(max=255))
    buyer_customer_id = fields.UUID(load_default=None)
    buyer_id_document = fields.String(load_default=None, validate=validate.Length(max=30))
    idempotency_key = fields.String(required=True)


class ValidateVoucherSchema(Schema):
    code = fields.String(required=True, validate=validate.Length(min=10, max=25))


class RedeemVoucherSchema(Schema):
    code = fields.String(required=True, validate=validate.Length(min=10, max=25))
    sale_id = fields.UUID(required=True)
    amount = fields.Float(required=True, validate=validate.Range(min=0.01))
    payment_id = fields.UUID(load_default=None)
    idempotency_key = fields.String(required=True)


class CancelVoucherSchema(Schema):
    reason = fields.String(required=True, validate=validate.Length(min=1, max=255))
