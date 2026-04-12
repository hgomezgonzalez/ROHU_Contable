"""Order module exceptions."""


class OrderError(Exception):
    def __init__(self, message: str, code: str = "ORDER_ERROR"):
        self.message = message
        self.code = code
        super().__init__(message)


class OrderNotFoundError(OrderError):
    def __init__(self, message: str = "Pedido no encontrado"):
        super().__init__(message, "ORDER_NOT_FOUND")


class OrderStateError(OrderError):
    def __init__(self, message: str = "Transicion de estado no permitida"):
        super().__init__(message, "ORDER_STATE_ERROR")


class CloseOrderStockError(OrderError):
    def __init__(self, message: str = "Stock insuficiente para cerrar el pedido"):
        super().__init__(message, "ORDER_CLOSE_STOCK_ERROR")


class OrderMaxOpenError(OrderError):
    def __init__(self, message: str = "Se alcanzo el limite de pedidos abiertos"):
        super().__init__(message, "ORDER_MAX_OPEN")


class OrderModuleDisabledError(OrderError):
    def __init__(self, message: str = "El modulo de Pedidos no esta activo"):
        super().__init__(message, "ORDER_MODULE_DISABLED")
