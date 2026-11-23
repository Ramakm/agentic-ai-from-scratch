"""Business logic: plain functions with no framework imports. These port anywhere."""


def lookup_order(order_id: str) -> dict:
    return {"id": order_id, "total": 79.0}


def issue_refund(order_id: str, amount: float) -> str:
    return f"refunded {amount} on {order_id}"
