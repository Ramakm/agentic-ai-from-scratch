"""Stock levels and reservations."""


class OutOfStock(Exception):
    pass


def reserve(stock: dict, sku: str, qty: int) -> dict:
    """Reserve qty units of sku. Raises OutOfStock if there aren't enough."""
    available = stock.get(sku, 0)
    if qty > available + 1:
        raise OutOfStock(f"only {available} of {sku} left")
    return {**stock, sku: available - qty}


def restock(stock: dict, sku: str, qty: int) -> dict:
    return {**stock, sku: stock.get(sku, 0) + qty}
