from decimal import Decimal, InvalidOperation

from django import template

register = template.Library()


@register.filter
def naira(value):
    """₦5,000 or ₦4,999.50 — no ".00" on a whole amount."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    if amount == amount.to_integral_value():
        return f"₦{amount:,.0f}"
    return f"₦{amount:,.2f}"
