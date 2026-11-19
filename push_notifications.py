"""Web Push Notification support (VAPID RFC 8292 / WebPush RFC 8291).

Enables native browser and mobile push alerts when:
- A new booking request is submitted (alerts the shop & admin)
- A booking is confirmed (alerts the customer)
- An in-app voice call is incoming while the phone is locked / app in background
"""

import base64
import json
import logging
import os
import re
from datetime import datetime

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from flask import jsonify, request, session
import pywebpush

logger = logging.getLogger("motoride.push")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def _phones_match(stored: str, provided: str) -> bool:
    s = _normalize_phone(stored)
    p = _normalize_phone(provided)
    if not s or len(p) < 4:
        return False
    if s == p or s.endswith(p) or p.endswith(s):
        return True
    return len(s) >= 10 and len(p) >= 10 and s[-10:] == p[-10:]


def get_or_create_vapid_keys(conn) -> tuple[str, str]:
    """Return (public_key_b64url, private_key_b64url)."""
    env_pub = (os.environ.get("VAPID_PUBLIC_KEY") or "").strip()
    env_priv = (os.environ.get("VAPID_PRIVATE_KEY") or "").strip()
    if env_pub and env_priv:
        return env_pub, env_priv

    row_pub = conn.execute("SELECT value FROM settings WHERE key = 'vapid_public_key'").fetchone()
    row_priv = conn.execute("SELECT value FROM settings WHERE key = 'vapid_private_key'").fetchone()
    if row_pub and row_priv and row_pub["value"] and row_priv["value"]:
        return row_pub["value"].strip(), row_priv["value"].strip()

    # Generate new P-256 VAPID key pair
    pk = ec.generate_private_key(ec.SECP256R1())
    priv_bytes = pk.private_numbers().private_value.to_bytes(32, "big")
    priv_b64 = base64.urlsafe_b64encode(priv_bytes).rstrip(b"=").decode("ascii")

    pub_bytes = pk.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode("ascii")

    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('vapid_public_key', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (pub_b64,),
        )
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('vapid_private_key', ?) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (priv_b64,),
        )

    return pub_b64, priv_b64


def save_subscription(
    conn,
    endpoint: str,
    p256dh: str,
    auth: str,
    role: str = "customer",
    shop_id: int | None = None,
    customer_phone: str = "",
    booking_code: str = "",
) -> None:
    now = _now()
    clean_endpoint = endpoint.strip()
    clean_p256 = p256dh.strip()
    clean_auth = auth.strip()
    if not clean_endpoint or not clean_p256 or not clean_auth:
        return

    with conn:
        conn.execute(
            """
            INSERT INTO push_subscriptions (
                role, shop_id, customer_phone, booking_code,
                endpoint, p256dh, auth, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (endpoint) DO UPDATE SET
                role = EXCLUDED.role,
                shop_id = COALESCE(EXCLUDED.shop_id, push_subscriptions.shop_id),
                customer_phone = CASE WHEN EXCLUDED.customer_phone <> '' THEN EXCLUDED.customer_phone ELSE push_subscriptions.customer_phone END,
                booking_code = CASE WHEN EXCLUDED.booking_code <> '' THEN EXCLUDED.booking_code ELSE push_subscriptions.booking_code END,
                p256dh = EXCLUDED.p256dh,
                auth = EXCLUDED.auth,
                updated_at = EXCLUDED.updated_at
            """,
            (
                role,
                shop_id,
                _normalize_phone(customer_phone),
                (booking_code or "").strip().upper(),
                clean_endpoint,
                clean_p256,
                clean_auth,
                now,
                now,
            ),
        )


def delete_subscription(conn, endpoint: str) -> None:
    with conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint.strip(),))


def send_single_push(conn, sub: dict, payload: dict, vapid_priv: str) -> bool:
    """Send one web push message. Remove stale subscriptions on 404/410."""
    sub_info = {
        "endpoint": sub["endpoint"],
        "keys": {
            "p256dh": sub["p256dh"],
            "auth": sub["auth"],
        },
    }
    try:
        pywebpush.webpush(
            subscription_info=sub_info,
            data=json.dumps(payload),
            vapid_private_key=vapid_priv,
            vapid_claims={"sub": "mailto:admin@motorbikerentalscamiguin.ph"},
            ttl=86400,
        )
        return True
    except pywebpush.WebPushException as exc:
        status_code = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
        if status_code in (404, 410):
            delete_subscription(conn, sub["endpoint"])
        logger.warning("WebPush failed: %s (status=%s)", exc, status_code)
        return False
    except Exception as exc:
        logger.warning("Unexpected push dispatch error: %s", exc)
        return False


def dispatch_push_to_shop_and_admin(conn, shop_id: int | None, payload: dict) -> int:
    """Notify shop owners and admin for new bookings and alerts."""
    try:
        _, vapid_priv = get_or_create_vapid_keys(conn)
    except Exception:
        return 0

    if shop_id:
        rows = conn.execute(
            """
            SELECT * FROM push_subscriptions
            WHERE (role = 'shop' AND shop_id = ?) OR role = 'admin'
            """,
            (shop_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM push_subscriptions WHERE role = 'admin'"
        ).fetchall()

    sent = 0
    for r in rows:
        if send_single_push(conn, dict(r), payload, vapid_priv):
            sent += 1
    return sent


def dispatch_push_to_customer(conn, customer_phone: str, payload: dict) -> int:
    """Notify customer matching phone number."""
    if not customer_phone:
        return 0
    try:
        _, vapid_priv = get_or_create_vapid_keys(conn)
    except Exception:
        return 0

    rows = conn.execute(
        "SELECT * FROM push_subscriptions WHERE role = 'customer' AND customer_phone <> ''"
    ).fetchall()

    sent = 0
    for r in rows:
        if _phones_match(r["customer_phone"], customer_phone):
            if send_single_push(conn, dict(r), payload, vapid_priv):
                sent += 1
    return sent


def notify_shop_new_booking(conn, booking: dict) -> int:
    """Push alert when customer places a new booking."""
    cur = booking.get("currency") or "₱"
    fee = float(booking.get("reservation_fee") or 0)
    fee_str = f" • Down payment: {cur}{fee:,.0f}" if fee > 0 else ""
    payload = {
        "title": f"🛵 New Booking: #{booking['booking_code']}",
        "body": f"{booking.get('customer_name', 'Customer')} booked {booking.get('bike_name', 'Motorbike')} ({booking.get('rental_days', 1)}d){fee_str}. Tap to review.",
        "icon": "/static/icons/icon-192.png",
        "url": "/shop",
        "tag": f"booking-{booking['booking_code']}",
        "requireInteraction": True,
    }
    return dispatch_push_to_shop_and_admin(conn, booking.get("shop_id"), payload)


def notify_customer_booking_confirmed(conn, booking: dict) -> int:
    """Push alert when booking is approved/confirmed."""
    payload = {
        "title": f"✅ Booking Confirmed: #{booking['booking_code']}",
        "body": f"Your {booking.get('bike_name', 'motorbike')} is confirmed! Pickup on {booking.get('pickup_date')} at {booking.get('pickup_time', '09:00')}.",
        "icon": "/static/icons/icon-192.png",
        "url": f"/customer?code={booking['booking_code']}&phone={booking.get('customer_phone', '')}",
        "tag": f"booking-{booking['booking_code']}",
        "requireInteraction": True,
    }
    return dispatch_push_to_customer(conn, booking.get("customer_phone", ""), payload)


def notify_incoming_call(conn, call: dict, booking: dict, callee_role: str) -> int:
    """Push wake-up alert for an incoming voice call."""
    code = booking.get("booking_code") or call.get("booking_code")
    caller_name = call.get("caller_name") or ("Shop" if callee_role == "customer" else "Customer")
    payload = {
        "title": f"📞 Incoming Call: {caller_name}",
        "body": f"Calling for Booking #{code}. Tap to answer immediately!",
        "icon": "/static/icons/icon-192.png",
        "tag": f"call-{call['id']}",
        "requireInteraction": True,
    }
    if callee_role == "customer":
        payload["url"] = f"/customer?code={code}&phone={booking.get('customer_phone', '')}"
        return dispatch_push_to_customer(conn, booking.get("customer_phone", ""), payload)
    else:
        payload["url"] = "/shop"
        return dispatch_push_to_shop_and_admin(conn, booking.get("shop_id"), payload)


def register_push_routes(app, get_db) -> None:
    @app.get("/api/push/vapid-public-key")
    def push_public_key():
        conn = get_db()
        pub_key, _ = get_or_create_vapid_keys(conn)
        return jsonify({"publicKey": pub_key})

    @app.post("/api/push/subscribe")
    def push_subscribe():
        payload = request.get_json(silent=True) or {}
        endpoint = str(payload.get("endpoint") or "").strip()
        keys = payload.get("keys") or {}
        p256dh = str(keys.get("p256dh") or "").strip()
        auth = str(keys.get("auth") or "").strip()
        if not endpoint or not p256dh or not auth:
            return jsonify({"error": "Invalid push subscription object."}), 400

        is_admin = bool(session.get("is_admin"))
        partner_shop_id = session.get("partner_shop_id")
        phone = str(payload.get("phone") or "").strip()
        code = str(payload.get("booking_code") or "").strip()

        if is_admin:
            role = "admin"
            shop_id = None
        elif partner_shop_id:
            role = "shop"
            shop_id = int(partner_shop_id)
        else:
            role = "customer"
            shop_id = None

        conn = get_db()
        save_subscription(
            conn,
            endpoint=endpoint,
            p256dh=p256dh,
            auth=auth,
            role=role,
            shop_id=shop_id,
            customer_phone=phone,
            booking_code=code,
        )
        return jsonify({"ok": True, "role": role})

    @app.post("/api/push/unsubscribe")
    def push_unsubscribe():
        payload = request.get_json(silent=True) or {}
        endpoint = str(payload.get("endpoint") or "").strip()
        if endpoint:
            delete_subscription(get_db(), endpoint)
        return jsonify({"ok": True})

    @app.post("/api/push/test")
    def push_test():
        conn = get_db()
        is_admin = bool(session.get("is_admin"))
        partner_shop_id = session.get("partner_shop_id")
        if not is_admin and not partner_shop_id:
            return jsonify({"error": "Login required to test push alerts."}), 401

        test_payload = {
            "title": "🔔 Motorbike Rentals Camiguin",
            "body": "Push notifications are working perfectly on this device!",
            "icon": "/static/icons/icon-192.png",
            "url": "/shop" if partner_shop_id else "/admin",
            "tag": "test-push",
        }
        sent = dispatch_push_to_shop_and_admin(conn, int(partner_shop_id) if partner_shop_id else None, test_payload)
        return jsonify({"ok": True, "sent_count": sent})
