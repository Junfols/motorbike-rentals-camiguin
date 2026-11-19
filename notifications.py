import json
import logging
import smtplib
import ssl
import threading
import urllib.error
import urllib.request
from email.message import EmailMessage

logger = logging.getLogger(__name__)


def _to_bool(val, default: bool = False) -> bool:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    return str(val).strip().lower() in ("1", "true", "yes", "on")


def _currency(settings: dict) -> str:
    return (settings.get("currency") or "₱").strip() or "₱"


def send_telegram_message(bot_token: str, chat_id: str, text: str, timeout: int = 8) -> tuple[bool, str]:
    """Send a plain/HTML-safe message via Telegram Bot API using stdlib urllib."""
    token = (bot_token or "").strip()
    cid = (chat_id or "").strip()
    if not token:
        return False, "Telegram Bot Token is not configured."
    if not cid:
        return False, "Telegram Chat ID is empty."

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = json.dumps(
        {
            "chat_id": cid,
            "text": text,
            "disable_web_page_preview": True,
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        if data.get("ok"):
            return True, "Telegram alert sent."
        return False, data.get("description") or "Telegram API returned an error."
    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_body)
            desc = err_json.get("description") or f"HTTP {exc.code}"
        except Exception:
            desc = f"HTTP {exc.code}"
        return False, f"Telegram error: {desc}"
    except Exception as exc:
        return False, f"Telegram error: {exc}"


def send_email_message(
    settings: dict,
    to_email: str,
    subject: str,
    body_text: str,
    timeout: int = 10,
) -> tuple[bool, str]:
    """Send an email notification using SMTP settings (STARTTLS on 587 or SSL on 465)."""
    recipient = (to_email or "").strip()
    if not recipient or "@" not in recipient:
        return False, "Valid recipient email address is missing."

    host = (settings.get("smtp_host") or "").strip()
    username = (settings.get("smtp_username") or "").strip()
    password = (settings.get("smtp_password") or "").strip()
    from_email = (settings.get("smtp_from_email") or "").strip() or username
    try:
        port = int(settings.get("smtp_port") or 587)
    except (TypeError, ValueError):
        port = 587

    if not host:
        return False, "SMTP Host is not configured."
    if not from_email:
        return False, "SMTP Username or From Email is required."

    msg = EmailMessage()
    platform_name = (settings.get("shop_name") or "Motorbike Rentals Camiguin").strip()
    msg["Subject"] = subject
    msg["From"] = f"{platform_name} <{from_email}>"
    msg["To"] = recipient
    msg.set_content(body_text)

    try:
        context = ssl.create_default_context()
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=context) as server:
                if username and password:
                    server.login(username, password)
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as server:
                server.ehlo()
                try:
                    server.starttls(context=context)
                    server.ehlo()
                except smtplib.SMTPNotSupportedError:
                    pass
                if username and password:
                    server.login(username, password)
                server.send_message(msg)
        return True, f"Email sent to {recipient}."
    except Exception as exc:
        return False, f"Email error: {exc}"


def format_new_booking_message(settings: dict, shop: dict, booking: dict) -> tuple[str, str]:
    """Build subject and body for new booking notifications."""
    cur = _currency(settings)
    platform = settings.get("shop_name") or "Motorbike Rentals Camiguin"
    maps_link = booking.get("google_maps_url") or ""
    if booking.get("pickup_method") == "delivery":
        method_label = f"Delivery ({booking.get('delivery_address')})"
        if maps_link:
            method_label += f"\n   Map/GPS: {maps_link}"
    else:
        method_label = f"Shop Pickup ({shop.get('address') or shop.get('municipality')})"
    addons = []
    if booking.get("extra_helmet"):
        addons.append("Extra Helmet")
    if booking.get("top_box"):
        addons.append("Rear Top Box")
    addons_text = ", ".join(addons) if addons else "None"

    subject = f"[{platform}] New Booking {booking.get('booking_code')} — {booking.get('bike_name')}"
    body = (
        f"NEW BOOKING REQUEST\n"
        f"Ref: {booking.get('booking_code')}\n"
        f"Shop: {shop.get('shop_name')} ({shop.get('municipality')})\n"
        f"Motorbike: {booking.get('bike_name')}\n"
        f"Dates: {booking.get('pickup_date')} to {booking.get('return_date')} "
        f"({booking.get('rental_days')} day(s), Pickup {booking.get('pickup_time')})\n"
        f"Handoff: {method_label}\n"
        f"Add-ons: {addons_text}\n\n"
        f"Customer: {booking.get('customer_name')}\n"
        f"Phone: {booking.get('customer_phone')}\n"
        + (f"Address: {booking.get('customer_address')}\n" if booking.get("customer_address") else "")
        + f"License: {booking.get('license_number')}\n"
        + (f"Notes: {booking.get('notes')}\n" if booking.get("notes") else "")
        + f"\nTotal: {cur}{float(booking.get('total_amount') or 0):,.2f}\n"
        + (
            f"Down Payment ({(booking.get('payment_channel') or 'gcash').upper()} - "
            f"{booking.get('payment_status') or 'submitted'}): "
            f"{cur}{float(booking.get('reservation_fee') or 0):,.2f}"
            + (f" (Ref: {booking.get('payment_reference')})" if booking.get("payment_reference") else "")
            + f"\nBalance Due at Pickup: {cur}{float(booking.get('balance_due') or 0):,.2f}\n"
            if float(booking.get("reservation_fee") or 0) > 0 or booking.get("payment_reference")
            else ""
        )
        + f"Shop Payout: {cur}{float(booking.get('shop_payout') or 0):,.2f}"
    )
    return subject, body


def notify_new_booking(settings: dict, shop: dict, booking: dict) -> dict:
    """Send new booking notifications to Main Admin, owning Partner Shop, and optionally Customer."""
    subject, body = format_new_booking_message(settings, shop, booking)
    results: dict[str, dict] = {}
    token = (settings.get("telegram_bot_token") or "").strip()
    admin_chat = (settings.get("admin_telegram_chat_id") or "").strip()
    partner_chat = (shop.get("telegram_chat_id") or "").strip()

    if token and admin_chat:
        ok, detail = send_telegram_message(token, admin_chat, body)
        results["admin_telegram"] = {"ok": ok, "detail": detail}
    if token and partner_chat and partner_chat != admin_chat:
        ok, detail = send_telegram_message(token, partner_chat, body)
        results["partner_telegram"] = {"ok": ok, "detail": detail}

    smtp_ready = bool((settings.get("smtp_host") or "").strip())
    if smtp_ready:
        admin_email = (settings.get("admin_notify_email") or "").strip()
        if admin_email:
            ok, detail = send_email_message(settings, admin_email, subject, body)
            results["admin_email"] = {"ok": ok, "detail": detail}

        partner_email = (shop.get("email") or "").strip()
        if (
            _to_bool(settings.get("notify_partner_email"), default=True)
            and partner_email
            and partner_email.lower() != admin_email.lower()
        ):
            ok, detail = send_email_message(settings, partner_email, subject, body)
            results["partner_email"] = {"ok": ok, "detail": detail}

        cust_email = (booking.get("customer_email") or "").strip()
        if _to_bool(settings.get("notify_customer_email"), default=True) and cust_email:
            cur = _currency(settings)
            cust_subject = (
                f"Booking Request Received ({booking.get('booking_code')}) — {settings.get('shop_name')}"
            )
            cust_body = (
                f"Hi {booking.get('customer_name')},\n\n"
                f"Your booking request has been submitted!\n\n"
                f"Booking Code: {booking.get('booking_code')}\n"
                f"Motorbike: {booking.get('bike_name')}\n"
                f"Rental Shop: {shop.get('shop_name')} ({shop.get('municipality')})\n"
                f"Shop Contact: {shop.get('phone')}\n"
                f"Dates: {booking.get('pickup_date')} to {booking.get('return_date')} "
                f"({booking.get('rental_days')} day(s))\n"
                f"Estimated Total: {cur}{float(booking.get('total_amount') or 0):,.2f}\n\n"
                f"Keep your Booking Code ({booking.get('booking_code')}) to check status anytime on My Bookings."
            )
            ok, detail = send_email_message(settings, cust_email, cust_subject, cust_body)
            results["customer_email"] = {"ok": ok, "detail": detail}

    return results


def notify_booking_cancelled_by_customer(settings: dict, shop: dict, booking: dict) -> dict:
    """Alert Admin and Partner when a customer cancels a pending booking."""
    platform = settings.get("shop_name") or "Motorbike Rentals Camiguin"
    subject = f"[{platform}] Booking Cancelled ({booking.get('booking_code')})"
    body = (
        f"BOOKING CANCELLED BY CUSTOMER\n"
        f"Ref: {booking.get('booking_code')}\n"
        f"Shop: {shop.get('shop_name')}\n"
        f"Motorbike: {booking.get('bike_name')}\n"
        f"Customer: {booking.get('customer_name')} ({booking.get('customer_phone')})\n"
        f"Dates Freed: {booking.get('pickup_date')} to {booking.get('return_date')}"
    )
    results: dict[str, dict] = {}
    token = (settings.get("telegram_bot_token") or "").strip()
    admin_chat = (settings.get("admin_telegram_chat_id") or "").strip()
    partner_chat = (shop.get("telegram_chat_id") or "").strip()

    if token and admin_chat:
        ok, detail = send_telegram_message(token, admin_chat, body)
        results["admin_telegram"] = {"ok": ok, "detail": detail}
    if token and partner_chat and partner_chat != admin_chat:
        ok, detail = send_telegram_message(token, partner_chat, body)
        results["partner_telegram"] = {"ok": ok, "detail": detail}

    if (settings.get("smtp_host") or "").strip():
        admin_email = (settings.get("admin_notify_email") or "").strip()
        if admin_email:
            ok, detail = send_email_message(settings, admin_email, subject, body)
            results["admin_email"] = {"ok": ok, "detail": detail}
        partner_email = (shop.get("email") or "").strip()
        if (
            _to_bool(settings.get("notify_partner_email"), default=True)
            and partner_email
            and partner_email.lower() != admin_email.lower()
        ):
            ok, detail = send_email_message(settings, partner_email, subject, body)
            results["partner_email"] = {"ok": ok, "detail": detail}

    return results


def notify_new_partner_registration(settings: dict, shop: dict) -> dict:
    """Alert Main Admin when a new partner rental shop registers and needs approval."""
    platform = settings.get("shop_name") or "Motorbike Rentals Camiguin"
    subject = f"[{platform}] New Partner Application — {shop.get('shop_name')}"
    body = (
        f"NEW PARTNER SHOP APPLICATION (Pending Approval)\n"
        f"Shop Name: {shop.get('shop_name')}\n"
        f"Owner: {shop.get('owner_name')}\n"
        f"Municipality: {shop.get('municipality')}, Camiguin\n"
        f"Phone: {shop.get('phone')}\n"
        f"Email: {shop.get('email')}\n"
        f"Open Main Admin -> Partner Shops tab to Approve or Review."
    )
    results: dict[str, dict] = {}
    token = (settings.get("telegram_bot_token") or "").strip()
    admin_chat = (settings.get("admin_telegram_chat_id") or "").strip()
    if token and admin_chat:
        ok, detail = send_telegram_message(token, admin_chat, body)
        results["admin_telegram"] = {"ok": ok, "detail": detail}

    if (settings.get("smtp_host") or "").strip():
        admin_email = (settings.get("admin_notify_email") or "").strip()
        if admin_email:
            ok, detail = send_email_message(settings, admin_email, subject, body)
            results["admin_email"] = {"ok": ok, "detail": detail}
    return results


def notify_partner_status_change(settings: dict, shop: dict) -> dict:
    """Notify a partner rental shop when Main Admin approves or suspends their account."""
    status = (shop.get("status") or "").lower()
    if status not in ("approved", "suspended"):
        return {}
    platform = settings.get("shop_name") or "Motorbike Rentals Camiguin"
    if status == "approved":
        subject = f"[{platform}] Your Shop Is Approved!"
        body = (
            f"Good news, {shop.get('owner_name')}!\n\n"
            f"Your rental shop '{shop.get('shop_name')}' is now APPROVED on {platform}.\n"
            f"Any available motorbikes you add in the Partner Portal are now live to renters!"
        )
    else:
        subject = f"[{platform}] Shop Account Status Update"
        body = (
            f"Hi {shop.get('owner_name')},\n\n"
            f"Your rental shop '{shop.get('shop_name')}' has been temporarily set to SUSPENDED "
            f"on {platform}. Please contact the Main Admin for assistance."
        )

    results: dict[str, dict] = {}
    token = (settings.get("telegram_bot_token") or "").strip()
    partner_chat = (shop.get("telegram_chat_id") or "").strip()
    if token and partner_chat:
        ok, detail = send_telegram_message(token, partner_chat, body)
        results["partner_telegram"] = {"ok": ok, "detail": detail}

    if (settings.get("smtp_host") or "").strip() and (shop.get("email") or "").strip():
        ok, detail = send_email_message(settings, shop["email"], subject, body)
        results["partner_email"] = {"ok": ok, "detail": detail}
    return results


def notify_payment_verified(settings: dict, shop: dict, booking: dict, payment_info: dict) -> dict:
    """Alert Admin, Partner Shop, and Customer when an online payment is verified via PayMongo/Gateway."""
    cur = _currency(settings)
    platform = settings.get("shop_name") or "Motorbike Rentals Camiguin"
    amount = float(payment_info.get("amount_php") or booking.get("reservation_fee") or 0)
    pay_id = payment_info.get("payment_id") or booking.get("payment_reference") or ""

    subject = f"[{platform}] Payment Confirmed ({booking.get('booking_code')}) — {cur}{amount:,.2f}"
    body = (
        f"ONLINE PAYMENT CONFIRMED\n"
        f"Booking Ref: {booking.get('booking_code')}\n"
        f"Amount Paid: {cur}{amount:,.2f}\n"
        f"Channel: PayMongo (QR Ph / GCash)\n"
        f"Payment ID: {pay_id}\n"
        f"Motorbike: {booking.get('bike_name')}\n"
        f"Shop: {shop.get('shop_name')} ({shop.get('municipality')})\n"
        f"Customer: {booking.get('customer_name')} ({booking.get('customer_phone')})\n"
        f"Dates: {booking.get('pickup_date')} to {booking.get('return_date')}\n"
        f"Status: Booking is now CONFIRMED automatically!"
    )
    results: dict[str, dict] = {}
    token = (settings.get("telegram_bot_token") or "").strip()
    admin_chat = (settings.get("admin_telegram_chat_id") or "").strip()
    partner_chat = (shop.get("telegram_chat_id") or "").strip()
    if token and admin_chat:
        ok, detail = send_telegram_message(token, admin_chat, body)
        results["admin_telegram"] = {"ok": ok, "detail": detail}
    if token and partner_chat and partner_chat != admin_chat:
        ok, detail = send_telegram_message(token, partner_chat, body)
        results["partner_telegram"] = {"ok": ok, "detail": detail}

    if (settings.get("smtp_host") or "").strip():
        admin_email = (settings.get("admin_notify_email") or "").strip()
        if admin_email:
            ok, detail = send_email_message(settings, admin_email, subject, body)
            results["admin_email"] = {"ok": ok, "detail": detail}
        partner_email = (shop.get("email") or "").strip()
        if partner_email and partner_email.lower() != admin_email.lower():
            ok, detail = send_email_message(settings, partner_email, subject, body)
            results["partner_email"] = {"ok": ok, "detail": detail}
        cust_email = (booking.get("customer_email") or "").strip()
        if cust_email:
            cust_subject = f"Payment Confirmed! ({booking.get('booking_code')}) — {platform}"
            cust_body = (
                f"Hi {booking.get('customer_name')},\n\n"
                f"Great news! Your online reservation payment of {cur}{amount:,.2f} has been verified.\n\n"
                f"Booking Code: {booking.get('booking_code')}\n"
                f"Status: CONFIRMED\n"
                f"Motorbike: {booking.get('bike_name')}\n"
                f"Pickup Date: {booking.get('pickup_date')} at {booking.get('pickup_time')}\n"
                f"Rental Shop: {shop.get('shop_name')} ({shop.get('phone')})\n\n"
                f"Show your Booking Code ({booking.get('booking_code')}) when picking up your motorbike."
            )
            ok, detail = send_email_message(settings, cust_email, cust_subject, cust_body)
            results["customer_email"] = {"ok": ok, "detail": detail}
    return results


def send_test_alert(
    settings: dict,
    telegram_chat_id: str | None = None,
    email_to: str | None = None,
    label: str = "Admin",
) -> dict:
    """Synchronously test Telegram and/or Email delivery and return per-channel status."""
    platform = settings.get("shop_name") or "Motorbike Rentals Camiguin"
    msg = (
        f"TEST ALERT — {platform}\n"
        f"Target: {label}\n"
        f"Instant notifications are working properly!"
    )
    out: dict[str, dict] = {}

    if telegram_chat_id is not None and telegram_chat_id.strip():
        ok, detail = send_telegram_message(
            settings.get("telegram_bot_token") or "",
            telegram_chat_id.strip(),
            msg,
        )
        out["telegram"] = {"ok": ok, "detail": detail}
    elif telegram_chat_id is not None:
        out["telegram"] = {"ok": False, "detail": "No Telegram Chat ID entered."}

    if email_to is not None and email_to.strip():
        ok, detail = send_email_message(
            settings,
            email_to.strip(),
            f"[{platform}] Test Notification ({label})",
            msg,
        )
        out["email"] = {"ok": ok, "detail": detail}
    elif email_to is not None and (settings.get("smtp_host") or "").strip():
        out["email"] = {"ok": False, "detail": "No alert email address entered."}

    return out


def dispatch_background(fn, *args) -> None:
    """Run notification callback in a daemon thread so HTTP responses never block."""

    def _runner():
        try:
            fn(*args)
        except Exception as exc:
            logger.warning("Notification task %s failed: %s", getattr(fn, "__name__", fn), exc)

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
