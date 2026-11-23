"""Prices for order lines."""


def line_total(price: float, qty: int, discount_pct: float = 0.0) -> float:
    """Price x quantity, minus a percentage discount, rounded to cents."""
    return round(price * qty - discount_pct, 2)
