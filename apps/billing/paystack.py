"""
The few Paystack calls billing needs, and the webhook signature check.

    https://paystack.com/docs/api/transaction/
    https://paystack.com/docs/payments/webhooks/

Amounts are always in kobo. Nothing here decides what a payment means —
see services.py for that.
"""

import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request

from django.conf import settings

logger = logging.getLogger(__name__)

API_BASE = "https://api.paystack.co"
TIMEOUT_SECONDS = 30


class PaystackError(Exception):
    """Paystack couldn't be reached, or said no."""


def is_configured():
    return bool(settings.PAYSTACK_SECRET_KEY)


def is_live():
    return settings.PAYSTACK_SECRET_KEY.startswith("sk_live_")


def _call(method, path, payload=None):
    if not is_configured():
        raise PaystackError("Payments aren't set up yet (PAYSTACK_SECRET_KEY is missing).")
    request = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        method=method,
        headers={
            "Authorization": f"Bearer {settings.PAYSTACK_SECRET_KEY}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "dictionmasters/1.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        try:
            message = json.loads(error.read().decode("utf-8")).get("message", "")
        except (ValueError, UnicodeDecodeError):
            message = ""
        logger.warning("Paystack %s %s answered %s: %s", method, path, error.code, message)
        raise PaystackError(message or f"Paystack answered HTTP {error.code}.") from error
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        logger.warning("Couldn't reach Paystack for %s %s: %s", method, path, error)
        raise PaystackError("Couldn't reach Paystack. Please try again in a moment.") from error

    if not body.get("status"):
        raise PaystackError(body.get("message") or "Paystack didn't accept that.")
    return body.get("data") or {}


def initialize(*, email, amount_kobo, reference, callback_url, metadata, currency="NGN"):
    """Start a payment. Returns Paystack's data, including authorization_url."""
    return _call("POST", "/transaction/initialize", {
        "email": email,
        "amount": amount_kobo,
        "currency": currency,
        "reference": reference,
        "callback_url": callback_url,
        "metadata": metadata,
    })


def verify(reference):
    """Paystack's own record of a payment — the only thing ever trusted
    about whether it was paid."""
    return _call("GET", f"/transaction/verify/{urllib.parse.quote(reference, safe='')}")


def signature_is_valid(body, signature):
    """A webhook really came from Paystack: its HMAC-SHA512 of the raw body
    with our secret key matches the x-paystack-signature header."""
    if not is_configured() or not signature:
        return False
    expected = hmac.new(settings.PAYSTACK_SECRET_KEY.encode("utf-8"), body, hashlib.sha512).hexdigest()
    return hmac.compare_digest(expected, signature)
