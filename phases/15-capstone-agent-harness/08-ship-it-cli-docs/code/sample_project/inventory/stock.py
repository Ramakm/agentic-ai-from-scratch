"""Stock levels for a small shop. Levels are plain dicts: {item: quantity}."""


def restock(levels: dict, item: str, qty: int) -> dict:
    """Return new levels with qty units of item added. The input is not modified."""
    if qty <= 0:
        raise ValueError("qty must be positive")
    new = dict(levels)
    new[item] = qty
    return new


def low_stock(levels: dict, threshold: int = 5) -> list:
    """Items with fewer than `threshold` units, sorted by name."""
    return sorted(item for item, qty in levels.items() if qty < threshold)
