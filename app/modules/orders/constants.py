"""Order module constants — state machine, transitions, number prefix."""


class OrderStatus:
    DRAFT = "draft"
    CONFIRMED = "confirmed"
    IN_PREPARATION = "in_preparation"
    READY = "ready"
    CLOSED = "closed"
    CANCELLED = "cancelled"
    CLOSE_FAILED = "close_failed"

    ALL = {DRAFT, CONFIRMED, IN_PREPARATION, READY, CLOSED, CANCELLED, CLOSE_FAILED}
    ACTIVE = {DRAFT, CONFIRMED, IN_PREPARATION, READY, CLOSE_FAILED}
    TERMINAL = {CLOSED, CANCELLED}
    KDS_VISIBLE = {CONFIRMED, IN_PREPARATION, READY}


# Allowed state transitions: {from_status: [to_statuses]}
TRANSITION_MAP = {
    OrderStatus.DRAFT: [OrderStatus.CONFIRMED, OrderStatus.CANCELLED],
    OrderStatus.CONFIRMED: [OrderStatus.IN_PREPARATION, OrderStatus.READY, OrderStatus.CANCELLED],
    OrderStatus.IN_PREPARATION: [OrderStatus.READY, OrderStatus.CANCELLED],
    OrderStatus.READY: [OrderStatus.CLOSED, OrderStatus.CLOSE_FAILED, OrderStatus.CANCELLED],
    OrderStatus.CLOSE_FAILED: [OrderStatus.CLOSED, OrderStatus.CANCELLED],
    OrderStatus.CLOSED: [],  # Terminal — no transitions allowed
    OrderStatus.CANCELLED: [],  # Terminal
}

ORDER_NUMBER_PREFIX = "ORD"

# Vertical types
VERTICAL_RESTAURANT = "restaurant"
VERTICAL_CAFE = "cafe"
VERTICAL_DRUGSTORE = "drugstore"
VERTICAL_CATERING = "catering"

ELIGIBLE_VERTICALS = {VERTICAL_RESTAURANT, VERTICAL_CAFE, VERTICAL_DRUGSTORE, VERTICAL_CATERING}

# Vertical presets for orders_config
VERTICAL_PRESETS = {
    VERTICAL_RESTAURANT: {
        "kds_enabled": True,
        "tables_enabled": True,
        "delivery_address_required": False,
        "max_open_orders": 80,
    },
    VERTICAL_CAFE: {
        "kds_enabled": True,
        "tables_enabled": False,
        "delivery_address_required": False,
        "max_open_orders": 40,
    },
    VERTICAL_DRUGSTORE: {
        "kds_enabled": False,
        "tables_enabled": False,
        "delivery_address_required": True,
        "max_open_orders": 30,
    },
    VERTICAL_CATERING: {
        "kds_enabled": False,
        "tables_enabled": False,
        "delivery_address_required": True,
        "max_open_orders": 15,
    },
}

DEFAULT_ORDERS_CONFIG = {
    "enabled": False,
    "vertical_type": None,
    "kds_enabled": False,
    "tables_enabled": False,
    "delivery_address_required": False,
    "max_open_orders": 50,
    "trial_started_at": None,
    "addon_active_until": None,
}
