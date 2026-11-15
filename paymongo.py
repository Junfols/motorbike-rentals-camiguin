import base64
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

PAYMONGO_API_BASE = "https://api.paymongo.com/v1"


def _build_auth_header(secret_key: str) -> str:
    """PayMongo uses Basic Auth with secret_key as username and empty password."""
    token = base64.b64encode(f"{secret_key.strip()}:".encode("utf-8")).decode("utf-8")
    return f"Basic {token}"


def create_payment_link(
    secret_key: str,
    amount_php: float,
    description: str,
    remarks: str = "",
    timeout: int = 10,
) -> tuple[bool, dict[str, Any] | str]:
    """
    Create a PayMongo Payment Link supporting QR Ph, GCash, Maya, and Cards.
    
    amount_php: Amount in Philippine Pesos (converted to centavos for PayMongo API).
    Returns (True, {"link_id": str, "checkout_url": str, "status": str}) or (False, error_message).
    """
    key = (secret_key or "").strip()
    if not key:
        return False, "PayMongo Secret Key is not configured."

    amount_centavos = int(round(float(amount_php) * 100))
    if amount_centavos < 2000:  # Minimum 20.00 PHP for PayMongo links
        return False, "Minimum payment amount is ₱20.00."

    url = f"{PAYMONGO_API_BASE}/links"
    payload = {
        "data": {
            "attributes": {
                "amount": amount_centavos,
                "description": description[:250],
                "remarks": (remarks or "")[:250],
                "payment_method_types": ["qrph", "gcash", "paymaya", "card", "dob", "billease"],
            }
        }
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": _build_auth_header(key),
            "User-Agent": "MotorideCamiguin-PWA/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        attr = data.get("data", {}).get("attributes", {})
        link_id = data.get("data", {}).get("id")
        checkout_url = attr.get("checkout_url")
        if not checkout_url:
            return False, "PayMongo returned an empty checkout URL."
        return True, {
            "link_id": link_id,
            "checkout_url": checkout_url,
            "status": attr.get("status", "unpaid"),
            "reference_number": attr.get("reference_number", ""),
        }
    except urllib.error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(raw_body)
            errors = err_json.get("errors", [])
            detail = ", ".join(e.get("detail", str(e)) for e in errors) if errors else f"HTTP {exc.code}"
        except Exception:
            detail = f"HTTP {exc.code}: {raw_body[:200]}"
        return False, f"PayMongo API error: {detail}"
    except Exception as exc:
        return False, f"PayMongo connection error: {exc}"


def get_payment_link(
    secret_key: str,
    link_id: str,
    timeout: int = 10,
) -> tuple[bool, dict[str, Any] | str]:
    """Retrieve the status and payment details of an existing PayMongo payment link."""
    key = (secret_key or "").strip()
    lid = (link_id or "").strip()
    if not key or not lid:
        return False, "Secret key or Link ID missing."

    url = f"{PAYMONGO_API_BASE}/links/{lid}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": _build_auth_header(key),
            "User-Agent": "MotorideCamiguin-PWA/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        attr = data.get("data", {}).get("attributes", {})
        payments = attr.get("payments", [])
        payment_id = payments[0].get("id") if payments else ""
        return True, {
            "link_id": lid,
            "status": attr.get("status", "unpaid"),
            "checkout_url": attr.get("checkout_url"),
            "payment_id": payment_id,
            "payments": payments,
        }
    except Exception as exc:
        return False, f"PayMongo error: {exc}"


def verify_webhook_signature(
    raw_payload: bytes,
    signature_header: str,
    webhook_secret: str,
    tolerance_seconds: int = 300,
) -> bool:
    """
    Verify PayMongo webhook HMAC signature from Paymongo-Signature header.
    Format: t=<timestamp>,te=<test_signature>,li=<live_signature>
    """
    secret = (webhook_secret or "").strip()
    header = (signature_header or "").strip()
    if not secret or not header or not raw_payload:
        return False

    parts: dict[str, str] = {}
    for item in header.split(","):
        if "=" in item:
            k, v = item.strip().split("=", 1)
            parts[k.strip()] = v.strip()

    timestamp = parts.get("t")
    if not timestamp:
        return False

    expected_sig = parts.get("li") or parts.get("te")
    if not expected_sig:
        return False

    try:
        to_sign = f"{timestamp}.".encode("utf-8") + raw_payload
        computed = hmac.new(secret.encode("utf-8"), to_sign, hashlib.sha256).hexdigest()
        return hmac.compare_digest(computed.lower(), expected_sig.lower())
    except Exception as exc:
        logger.warning("Error verifying webhook signature: %s", exc)
        return False


def extract_payment_details_from_webhook(event_data: dict[str, Any]) -> dict[str, Any] | None:
    """
    Extract link_id, payment_id, amount_php, and status from a PayMongo webhook payload.
    Supports 'link.payment.paid', 'payment.paid', and related events.
    """
    try:
        data = event_data.get("data", {})
        attr = data.get("attributes", {})
        event_type = attr.get("type", "")
        resource_data = attr.get("data", {})
        resource_attr = resource_data.get("attributes", {})

        if "link" in event_type or resource_data.get("type") == "link":
            link_id = resource_data.get("id") or resource_attr.get("id")
            payments = resource_attr.get("payments", [])
            payment_id = payments[0].get("id") if payments else ""
            amount_centavos = resource_attr.get("amount") or (payments[0].get("amount") if payments else 0)
            return {
                "event_type": event_type,
                "link_id": link_id,
                "payment_id": payment_id or link_id,
                "amount_php": float(amount_centavos or 0) / 100.0,
                "status": "paid",
                "remarks": resource_attr.get("remarks", ""),
            }
        elif "payment" in event_type or resource_data.get("type") == "payment":
            payment_id = resource_data.get("id")
            amount_centavos = resource_attr.get("amount") or 0
            description = resource_attr.get("description", "")
            return {
                "event_type": event_type,
                "link_id": None,
                "payment_id": payment_id,
                "amount_php": float(amount_centavos or 0) / 100.0,
                "status": "paid",
                "remarks": description,
            }
    except Exception as exc:
        logger.warning("Failed to extract payment details from PayMongo webhook: %s", exc)
    return None
