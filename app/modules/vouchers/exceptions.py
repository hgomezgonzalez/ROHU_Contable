"""Voucher module exceptions."""


class VoucherError(Exception):
    """Base exception for voucher module."""

    def __init__(self, message: str, code: str = "VOUCHER_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class VoucherNotFoundError(VoucherError):
    def __init__(self, message: str = "Bono no encontrado"):
        super().__init__(message, "VOUCHER_NOT_FOUND")


class VoucherAlreadyRedeemedError(VoucherError):
    def __init__(self, message: str = "Este bono ya fue redimido"):
        super().__init__(message, "VOUCHER_ALREADY_REDEEMED")


class VoucherExpiredError(VoucherError):
    def __init__(self, message: str = "Este bono ha expirado"):
        super().__init__(message, "VOUCHER_EXPIRED")


class VoucherNotSoldError(VoucherError):
    def __init__(self, message: str = "Este bono no ha sido vendido aún"):
        super().__init__(message, "VOUCHER_NOT_SOLD")


class VoucherCancelledError(VoucherError):
    def __init__(self, message: str = "Este bono fue cancelado"):
        super().__init__(message, "VOUCHER_CANCELLED")


class VoucherInsufficientBalanceError(VoucherError):
    def __init__(self, message: str = "Saldo insuficiente en el bono"):
        super().__init__(message, "VOUCHER_INSUFFICIENT_BALANCE")


class VoucherConcurrencyError(VoucherError):
    def __init__(self, message: str = "El bono está siendo procesado, intente de nuevo"):
        super().__init__(message, "VOUCHER_CONCURRENCY")


class VoucherInvalidCodeError(VoucherError):
    def __init__(self, message: str = "Código de bono inválido"):
        super().__init__(message, "VOUCHER_INVALID_CODE")


class VoucherTypeInactiveError(VoucherError):
    def __init__(self, message: str = "Este tipo de bono está inactivo"):
        super().__init__(message, "VOUCHER_TYPE_INACTIVE")


class VoucherMaxIssuedError(VoucherError):
    def __init__(self, message: str = "Se alcanzó el límite de emisión para este tipo de bono"):
        super().__init__(message, "VOUCHER_MAX_ISSUED")


class VoucherPrintLimitError(VoucherError):
    def __init__(self, message: str = "Se alcanzó el límite de impresiones para este bono"):
        super().__init__(message, "VOUCHER_PRINT_LIMIT")


class VoucherHighValueRequiresIdError(VoucherError):
    def __init__(self, message: str = "Bonos de alto valor requieren documento de identidad del comprador"):
        super().__init__(message, "VOUCHER_HIGH_VALUE_REQUIRES_ID")
