import base64
import json
import os
import re
import secrets
from datetime import date, datetime
from functools import wraps
from urllib.parse import urlparse

from flask import (
    Flask,
    Response,
    g,
    jsonify,
    make_response,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
)
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash
from werkzeug.utils import secure_filename

from db import (
    BASE_DIR,
    BLOCKING_STATUSES,
    CAMIGUIN_MUNICIPALITIES,
    DEFAULT_CONTRACT_TERMS,
    DEFAULT_DB_PATH,
    VALID_BIKE_STATUSES,
    VALID_BOOKING_STATUSES,
    VALID_CATEGORIES,
    VALID_PAYMENT_STATUSES,
    VALID_RESERVATION_MODES,
    VALID_SHOP_STATUSES,
    VALID_TRANSMISSIONS,
    build_bike_schedules,
    calculate_quote,
    count_overlapping_bookings,
    create_review,
    delete_unused_uploaded_media,
    generate_booking_code,
    get_admin_settings_view,
    get_all_bike_rating_stats,
    get_all_shop_rating_stats,
    get_bike_rating_stats,
    get_bike_reviews,
    get_connection,
    get_database_url,
    get_recent_reviews,
    get_settings,
    get_shop_rating_stats,
    get_shop_reviews,
    get_uploaded_media,
    init_db,
    is_postgres_url,
    is_reservation_payment_configured,
    parse_iso_date,
    save_uploaded_media,
    slugify_name,
    slugify_shop_name,
    verify_admin_password,
    verify_shop_password,
)
from calls import register_call_routes
from icons import ensure_icons
from notifications import (
    dispatch_background,
    notify_booking_cancelled_by_customer,
    notify_new_booking,
    notify_new_partner_registration,
    notify_partner_status_change,
    notify_payment_verified,
    send_test_alert,
)
from paymongo import (
    create_payment_link,
    extract_payment_details_from_webhook,
    get_payment_link,
    verify_webhook_signature,
)

ALLOWED_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "jfif", "webp"}


def _normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def _phones_match(stored: str, provided: str) -> bool:
    s = _normalize_phone(stored)
    p = _normalize_phone(provided)
    if not s or len(p) < 4:
        return False
    if s == p or s.endswith(p):
        return True
    if len(s) >= 10 and len(p) >= 10 and s[-10:] == p[-10:]:
        return True
    return False


def _allowed_image(filename: str) -> bool:
    if "." not in filename:
        return False
    ext = filename.rsplit(".", 1)[1].lower()
    return ext in ALLOWED_IMAGE_EXTENSIONS


def _as_bool(value, default: bool = False) -> bool:
    """Parse boolean flags coming from JSON booleans or multipart form fields."""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _validate_image_upload(
    image_file,
    prefix: str = "",
    max_bytes: int = 8 * 1024 * 1024,
) -> tuple[str, bytes, str | None] | None:
    """Validate an uploaded image file and prepare its storage tuple without touching DB."""
    if not image_file or not getattr(image_file, "filename", ""):
        return None
    orig_name = str(image_file.filename)
    if not _allowed_image(orig_name):
        raise ValueError("Uploaded image must be PNG, JPG, JPEG, JFIF, or WEBP.")
    raw_bytes = image_file.read()
    if not raw_bytes:
        raise ValueError("Uploaded image file is empty.")
    if len(raw_bytes) > max_bytes:
        limit_mb = max(1, max_bytes // (1024 * 1024))
        raise ValueError(f"Uploaded image must be {limit_mb} MB or smaller.")
    ext = orig_name.rsplit(".", 1)[1].lower()
    safe_name = secure_filename(orig_name) or f"image.{ext}"
    if "." not in safe_name:
        safe_name = f"{safe_name}.{ext}"
    prefix_clean = f"{prefix.strip('_')}_" if prefix.strip("_") else ""
    unique_name = f"{prefix_clean}{secrets.token_hex(6)}_{safe_name}"
    mime = (getattr(image_file, "mimetype", None) or "").strip() or None
    return unique_name, raw_bytes, mime


def _save_validated_image(
    conn,
    validated: tuple[str, bytes, str | None],
    use_tx: bool = True,
) -> str:
    """Persist a validated image tuple in uploaded_media and return its /uploads URL."""
    unique_name, raw_bytes, mime = validated
    save_uploaded_media(conn, unique_name, raw_bytes, content_type=mime, use_tx=use_tx)
    return f"/uploads/{unique_name}"


def _serialize_shop(row, include_private: bool = False, rating_stats: dict | None = None) -> dict:
    keys = row.keys()
    raw_contract = (row["contract_terms"] if "contract_terms" in keys else "") or ""
    r_avg = float(rating_stats.get("avg_rating", 5.0)) if rating_stats else (float(row["rating_avg"]) if "rating_avg" in keys and row["rating_avg"] is not None else 5.0)
    r_cnt = int(rating_stats.get("review_count", 0)) if rating_stats else (int(row["review_count"]) if "review_count" in keys and row["review_count"] is not None else 0)
    data = {
        "id": row["id"],
        "shop_name": row["shop_name"],
        "slug": row["slug"],
        "municipality": row["municipality"],
        "address": row["address"],
        "description": row["description"],
        "delivery_fee": float(row["delivery_fee"] or 0),
        "phone": row["phone"],
        "whatsapp_number": row["whatsapp_number"],
        "logo_url": (row["logo_url"] if "logo_url" in keys else "") or "",
        "cover_url": (row["cover_url"] if "cover_url" in keys else "") or "",
        "contract_terms": raw_contract.strip() or DEFAULT_CONTRACT_TERMS,
        "custom_contract_terms": raw_contract.strip(),
        "default_contract_terms": DEFAULT_CONTRACT_TERMS,
        "share_url": f"/shop/{row['slug']}",
        "status": row["status"],
        "is_main": bool(row["is_main"]),
        "rating_avg": round(r_avg, 1),
        "review_count": r_cnt,
    }
    if "bike_count" in keys:
        data["bike_count"] = int(row["bike_count"] or 0)
    if "booking_count" in keys:
        data["booking_count"] = int(row["booking_count"] or 0)
    if "gross_revenue" in keys:
        data["gross_revenue"] = float(row["gross_revenue"] or 0)
    if "platform_fee_total" in keys:
        data["platform_fee_total"] = float(row["platform_fee_total"] or 0)
    if "shop_payout_total" in keys:
        data["shop_payout_total"] = float(row["shop_payout_total"] or 0)
    if include_private:
        data["owner_name"] = row["owner_name"]
        data["email"] = row["email"]
        data["telegram_chat_id"] = row["telegram_chat_id"] if "telegram_chat_id" in keys else ""
        data["created_at"] = row["created_at"]
    return data


def _serialize_bike(row, booked_units: int = 0, schedule: dict | None = None, rating_stats: dict | None = None) -> dict:
    keys = row.keys()
    units_count = int(row["units_count"] or 1)
    available_units = max(0, units_count - booked_units) if row["status"] == "available" else 0
    r_avg = float(rating_stats.get("avg_rating", 5.0)) if rating_stats else (float(row["rating_avg"]) if "rating_avg" in keys and row["rating_avg"] is not None else 5.0)
    r_cnt = int(rating_stats.get("review_count", 0)) if rating_stats else (int(row["rating_count"]) if "rating_count" in keys and row["rating_count"] is not None else 0)
    raw_shop_contract = (row["shop_contract_terms"] if "shop_contract_terms" in keys else "") or ""
    data = {
        "id": row["id"],
        "shop_id": int(row["shop_id"]),
        "shop_name": row["shop_name"] if "shop_name" in keys else None,
        "shop_slug": row["shop_slug"] if "shop_slug" in keys else None,
        "shop_logo_url": (row["shop_logo_url"] if "shop_logo_url" in keys else "") or "",
        "shop_cover_url": (row["shop_cover_url"] if "shop_cover_url" in keys else "") or "",
        "shop_municipality": row["shop_municipality"] if "shop_municipality" in keys else None,
        "shop_address": row["shop_address"] if "shop_address" in keys else None,
        "shop_phone": row["shop_phone"] if "shop_phone" in keys else None,
        "shop_whatsapp": row["shop_whatsapp"] if "shop_whatsapp" in keys else None,
        "shop_delivery_fee": (
            float(row["shop_delivery_fee"] or 0) if "shop_delivery_fee" in keys else None
        ),
        "shop_contract_terms": raw_shop_contract.strip() or DEFAULT_CONTRACT_TERMS,
        "shop_status": row["shop_status"] if "shop_status" in keys else None,
        "name": row["name"],
        "slug": row["slug"],
        "category": row["category"],
        "engine_cc": int(row["engine_cc"]),
        "transmission": row["transmission"],
        "fuel_type": row["fuel_type"],
        "daily_rate": float(row["daily_rate"]),
        "weekly_rate": float(row["weekly_rate"] or 0),
        "deposit": float(row["deposit"] or 0),
        "units_count": units_count,
        "booked_units": booked_units,
        "available_units": available_units,
        "is_available": row["status"] == "available" and available_units > 0,
        "rating_avg": r_avg,
        "rating_count": r_cnt,
        "plate_number": row["plate_number"],
        "inclusions": row["inclusions"],
        "description": row["description"],
        "image_url": row["image_url"],
        "status": row["status"],
        "featured": bool(row["featured"]),
        "created_at": row["created_at"],
    }
    if schedule:
        data.update(schedule)
    return data


def _fetch_bike_with_shop(conn, bike_id: int):
    return conn.execute(
        "SELECT b.*, s.shop_name AS shop_name, s.slug AS shop_slug, s.logo_url AS shop_logo_url, "
        "s.cover_url AS shop_cover_url, s.contract_terms AS shop_contract_terms, "
        "s.municipality AS shop_municipality, s.status AS shop_status "
        "FROM bikes b JOIN shops s ON s.id = b.shop_id WHERE b.id = ?",
        (bike_id,),
    ).fetchone()


def _serialize_bike_with_schedule(conn, bike_row, include_calendar: bool = False, include_admin_details: bool = True) -> dict:
    today_str = date.today().isoformat()
    sched = build_bike_schedules(
        conn,
        [bike_row],
        ref_pickup_date=today_str,
        ref_return_date=today_str,
        include_calendar=include_calendar,
        include_admin_details=include_admin_details,
    ).get(int(bike_row["id"]))
    booked = int((sched or {}).get("ref_booked_units", 0))
    return _serialize_bike(bike_row, booked_units=booked, schedule=sched)


def _apply_bike_availability_patch(conn, bike_row, payload: dict) -> tuple[dict | None, str | None, int]:
    """Shared handler to quick-update motorbike status or unit count."""
    new_status = existing_status = bike_row["status"]
    if "status" in payload and payload["status"] is not None:
        new_status = str(payload["status"]).strip().lower()
        if new_status not in VALID_BIKE_STATUSES:
            return None, "Status must be available, maintenance, or hidden.", 400

    new_units = int(bike_row["units_count"] or 1)
    if "units_count" in payload and payload["units_count"] is not None:
        try:
            new_units = int(payload["units_count"])
        except (TypeError, ValueError):
            return None, "Units count must be a valid integer.", 400
        if new_units < 1:
            return None, "Units count must be at least 1.", 400

    if new_status == existing_status and new_units == int(bike_row["units_count"] or 1):
        fresh = _fetch_bike_with_shop(conn, bike_row["id"])
        return {"bike": _serialize_bike_with_schedule(conn, fresh, include_calendar=True)}, None, 200

    with conn:
        conn.execute(
            "UPDATE bikes SET status = ?, units_count = ? WHERE id = ?",
            (new_status, new_units, bike_row["id"]),
        )
    fresh = _fetch_bike_with_shop(conn, bike_row["id"])
    return {"bike": _serialize_bike_with_schedule(conn, fresh, include_calendar=True)}, None, 200


def _create_bike_block_entry(conn, bike_row, payload: dict) -> tuple[dict | None, str | None, int]:
    """Create a manual date block (walk-in / offline reservation / maintenance hold)."""
    start_date = str(payload.get("start_date") or "").strip()
    end_date = str(payload.get("end_date") or start_date).strip()
    reason = str(payload.get("reason") or "Walk-in / Offline Booking").strip()[:120] or "Walk-in / Offline Booking"

    if not start_date or not end_date:
        return None, "Start date and end date are required.", 400
    try:
        s_dt = parse_iso_date(start_date)
        e_dt = parse_iso_date(end_date)
    except ValueError:
        return None, "Invalid date format. Use YYYY-MM-DD.", 400
    if e_dt < s_dt:
        return None, "End date cannot be earlier than start date.", 400

    units_count = max(1, int(bike_row["units_count"] or 1))
    raw_units = payload.get("units_blocked")
    if raw_units in (None, ""):
        units_blocked = units_count
    else:
        try:
            units_blocked = int(raw_units)
        except (TypeError, ValueError):
            return None, "Units blocked must be a whole number.", 400
    if units_blocked < 1 or units_blocked > units_count:
        return None, f"Units blocked must be between 1 and {units_count}.", 400

    now = datetime.now().isoformat(timespec="seconds")
    try:
        locked = conn.begin_booking_lock(bike_row["id"])
        if not locked:
            conn.rollback()
            return None, "Motorbike not found.", 404
        existing_peak = count_overlapping_bookings(conn, bike_row["id"], start_date, end_date)
        if existing_peak + units_blocked > units_count:
            conn.rollback()
            return (
                None,
                (
                    f"Cannot block {units_blocked} unit(s): {existing_peak} of {units_count} unit(s) "
                    f"are already booked or blocked between {start_date} and {end_date}."
                ),
                409,
            )
        conn.insert_returning_id(
            """
            INSERT INTO bike_blocks (bike_id, shop_id, start_date, end_date, units_blocked, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (bike_row["id"], bike_row["shop_id"], start_date, end_date, units_blocked, reason, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise

    fresh = _fetch_bike_with_shop(conn, bike_row["id"])
    return {"bike": _serialize_bike_with_schedule(conn, fresh, include_calendar=True)}, None, 201


def _delete_bike_block_entry(conn, bike_row, block_id: int) -> tuple[dict | None, str | None, int]:
    """Delete a manual date block belonging to this motorbike."""
    existing = conn.execute(
        "SELECT id FROM bike_blocks WHERE id = ? AND bike_id = ?",
        (block_id, bike_row["id"]),
    ).fetchone()
    if not existing:
        return None, "Date block not found for this motorbike.", 404
    with conn:
        conn.execute("DELETE FROM bike_blocks WHERE id = ? AND bike_id = ?", (block_id, bike_row["id"]))
    fresh = _fetch_bike_with_shop(conn, bike_row["id"])
    return {"bike": _serialize_bike_with_schedule(conn, fresh, include_calendar=True)}, None, 200


def _serialize_booking(row) -> dict:
    keys = row.keys()
    return {
        "id": row["id"],
        "booking_code": row["booking_code"],
        "bike_id": row["bike_id"],
        "shop_id": int(row["shop_id"]),
        "shop_name": row["shop_name"] if "shop_name" in keys else None,
        "shop_slug": row["shop_slug"] if "shop_slug" in keys else None,
        "shop_logo_url": (row["shop_logo_url"] if "shop_logo_url" in keys else "") or "",
        "shop_cover_url": (row["shop_cover_url"] if "shop_cover_url" in keys else "") or "",
        "shop_municipality": row["shop_municipality"] if "shop_municipality" in keys else None,
        "shop_address": row["shop_address"] if "shop_address" in keys else None,
        "shop_phone": row["shop_phone"] if "shop_phone" in keys else None,
        "shop_whatsapp": row["shop_whatsapp"] if "shop_whatsapp" in keys else None,
        "bike_name": row["bike_name"] if "bike_name" in keys else None,
        "bike_image": row["bike_image"] if "bike_image" in keys else None,
        "bike_category": row["bike_category"] if "bike_category" in keys else None,
        "bike_transmission": row["bike_transmission"] if "bike_transmission" in keys else None,
        "plate_number": row["plate_number"] if "plate_number" in keys else None,
        "customer_name": row["customer_name"],
        "customer_phone": row["customer_phone"],
        "customer_email": row["customer_email"],
        "customer_address": (row["customer_address"] if "customer_address" in keys else "") or "",
        "license_number": row["license_number"],
        "pickup_date": row["pickup_date"],
        "return_date": row["return_date"],
        "pickup_time": row["pickup_time"],
        "pickup_method": row["pickup_method"],
        "delivery_address": row["delivery_address"],
        "extra_helmet": bool(row["extra_helmet"]),
        "top_box": bool(row["top_box"]),
        "rental_days": int(row["rental_days"]),
        "base_subtotal": float(row["base_subtotal"]),
        "addons_total": float(row["addons_total"]),
        "delivery_total": float(row["delivery_total"]),
        "total_amount": float(row["total_amount"]),
        "commission_rate": float(row["commission_rate"] or 0),
        "platform_fee": float(row["platform_fee"] or 0),
        "shop_payout": float(row["shop_payout"] or 0),
        "reservation_fee": float(row["reservation_fee"] if "reservation_fee" in row.keys() and row["reservation_fee"] is not None else 0),
        "balance_due": float(
            row["balance_due"]
            if "balance_due" in row.keys() and row["balance_due"] is not None
            else row["total_amount"]
        ),
        "payment_channel": (row["payment_channel"] if "payment_channel" in row.keys() else "") or "pay_at_shop",
        "payment_reference": (row["payment_reference"] if "payment_reference" in row.keys() else "") or "",
        "payment_proof_url": (row["payment_proof_url"] if "payment_proof_url" in row.keys() else "") or "",
        "payment_status": (row["payment_status"] if "payment_status" in row.keys() else "") or "unpaid",
        "payment_link_id": (row["payment_link_id"] if "payment_link_id" in row.keys() else "") or "",
        "payment_checkout_url": (row["payment_checkout_url"] if "payment_checkout_url" in row.keys() else "") or "",
        "delivery_lat": (
            float(row["delivery_lat"])
            if "delivery_lat" in row.keys() and row["delivery_lat"] is not None
            else None
        ),
        "delivery_lng": (
            float(row["delivery_lng"])
            if "delivery_lng" in row.keys() and row["delivery_lng"] is not None
            else None
        ),
        "license_photo_url": (row["license_photo_url"] if "license_photo_url" in row.keys() else "") or "",
        "signature_url": (row["signature_url"] if "signature_url" in row.keys() else "") or "",
        "contract_agreed": bool(row["contract_agreed"]) if "contract_agreed" in row.keys() else False,
        "contract_signed_at": (row["contract_signed_at"] if "contract_signed_at" in row.keys() else "") or "",
        "google_maps_url": (
            f"https://www.google.com/maps/dir/?api=1&destination={row['delivery_lat']},{row['delivery_lng']}"
            if "delivery_lat" in row.keys()
            and row["delivery_lat"] is not None
            and "delivery_lng" in row.keys()
            and row["delivery_lng"] is not None
            else ""
        ),
        "balance_paid": _row_balance_paid(row),
        "deposit_amount": float(row["deposit_amount"]),
        "notes": row["notes"],
        "admin_notes": row["admin_notes"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _row_balance_paid(row) -> bool:
    """True when the shop already collected the remaining balance for this booking."""
    if "balance_paid" not in row.keys():
        return False
    return bool(int(row["balance_paid"] or 0))


def _resolve_balance_paid(payload: dict, existing_row) -> tuple[bool, str | None]:
    """Return (new_balance_paid, error). Cancelled bookings cannot be marked paid."""
    current = _row_balance_paid(existing_row)
    if "balance_paid" not in payload or payload["balance_paid"] is None:
        return current, None
    wanted = _as_bool(payload["balance_paid"])
    new_status = str(payload.get("status") or existing_row["status"]).strip().lower()
    if wanted and new_status == "cancelled":
        return current, "Cancelled bookings cannot be marked as paid."
    return wanted, None


def create_app(test_config: dict | None = None) -> Flask:
    """Create and configure the centralized Flask PWA application."""
    app = Flask(
        __name__,
        static_folder=os.path.join(BASE_DIR, "static"),
        template_folder=os.path.join(BASE_DIR, "templates"),
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

    data_dir = os.environ.get("MOTORIDE_DATA_DIR")
    if data_dir:
        os.makedirs(data_dir, exist_ok=True)
    default_db = os.path.join(data_dir, "motoride.db") if data_dir else DEFAULT_DB_PATH
    default_uploads = (
        os.path.join(data_dir, "uploads")
        if data_dir
        else os.path.join(BASE_DIR, "static", "uploads")
    )

    db_path = (test_config or {}).get("DB_PATH") or os.environ.get("MOTORIDE_DB_PATH") or default_db
    if test_config and "DB_PATH" in test_config and "DATABASE_URL" not in test_config:
        db_url = ""
    else:
        db_url = (test_config or {}).get("DATABASE_URL") or get_database_url() or ""

    upload_dir = (test_config or {}).get("UPLOAD_FOLDER") or default_uploads
    os.makedirs(upload_dir, exist_ok=True)

    if not (test_config or {}).get("SKIP_ICONS"):
        ensure_icons(force=False)

    seed_demo = bool(
        (test_config or {}).get(
            "SEED_DEMO",
            bool((test_config or {}).get("TESTING"))
            or os.environ.get("SEED_DEMO_DATA", "").strip().lower() in ("1", "true", "yes"),
        )
    )
    init_db(db_path=db_path, db_url=db_url, seed_demo=seed_demo)
    conn = get_connection(db_path=db_path, db_url=db_url)
    try:
        settings_with_secrets = get_settings(conn, include_secrets=True)
        secret_key = (
            os.environ.get("SECRET_KEY")
            or settings_with_secrets.get("secret_key")
            or secrets.token_hex(32)
        )
    finally:
        conn.close()

    app.config.update(
        DB_PATH=db_path,
        DATABASE_URL=db_url,
        UPLOAD_FOLDER=upload_dir,
        MAX_CONTENT_LENGTH=10 * 1024 * 1024,
        SECRET_KEY=(test_config or {}).get("SECRET_KEY", secret_key),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    if test_config:
        app.config.update(test_config)

    def get_db():
        if "db" not in g:
            g.db = get_connection(
                db_path=app.config["DB_PATH"],
                db_url=app.config["DATABASE_URL"],
            )
        return g.db

    @app.teardown_appcontext
    def close_db(exception=None):
        db = g.pop("db", None)
        if db is not None:
            db.close()

    def _dispatch_alert(fn, *args):
        custom = app.config.get("NOTIFICATION_DISPATCHER")
        if custom:
            custom(fn, *args)
        elif app.config.get("NOTIFICATION_SYNC"):
            fn(*args)
        else:
            dispatch_background(fn, *args)

    @app.context_processor
    def inject_shop_settings():
        conn = get_db()
        return {
            "shop": get_settings(conn),
            "municipalities": CAMIGUIN_MUNICIPALITIES,
        }

    def admin_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not session.get("is_admin"):
                return jsonify({"error": "Main Admin authentication required."}), 401
            return fn(*args, **kwargs)

        return wrapper

    def partner_required(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            shop_id = session.get("partner_shop_id")
            if not shop_id:
                return jsonify({"error": "Partner shop login required."}), 401
            shop_row = get_db().execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
            if not shop_row:
                session.pop("partner_shop_id", None)
                return jsonify({"error": "Partner shop account no longer exists."}), 401
            g.partner_shop = shop_row
            return fn(*args, **kwargs)

        return wrapper

    def _find_featured_shop(conn, shop_ref: str | None) -> dict | None:
        ref = (shop_ref or "").strip()
        if not ref:
            return None
        partner_id = int(session.get("partner_shop_id") or 0)
        is_admin = bool(session.get("is_admin"))
        row = conn.execute(
            """
            SELECT s.*,
                   COUNT(CASE WHEN b.status != 'hidden' THEN 1 END) AS bike_count
            FROM shops s
            LEFT JOIN bikes b ON b.shop_id = s.id
            WHERE (LOWER(s.slug) = LOWER(?) OR CAST(s.id AS TEXT) = ?)
              AND (s.status = 'approved' OR s.id = ? OR ? = 1)
            GROUP BY s.id
            LIMIT 1
            """,
            (ref, ref, partner_id, 1 if is_admin else 0),
        ).fetchone()
        if not row:
            return None
        stats = get_shop_rating_stats(conn, int(row["id"]))
        shop_dict = _serialize_shop(row, rating_stats=stats)
        shop_dict["reviews"] = get_shop_reviews(conn, int(row["id"]), limit=15)
        return shop_dict

    def _build_storefront_bootstrap(conn, featured_shop: dict | None = None) -> dict:
        today_str = date.today().isoformat()
        shop_rows = conn.execute(
            """
            SELECT s.*,
                   COUNT(CASE WHEN b.status != 'hidden' THEN 1 END) AS bike_count
            FROM shops s
            LEFT JOIN bikes b ON b.shop_id = s.id
            WHERE s.status = 'approved'
            GROUP BY s.id
            ORDER BY s.is_main DESC, s.shop_name ASC
            """
        ).fetchall()
        shop_stats = get_all_shop_rating_stats(conn)
        shops_list = [_serialize_shop(r, rating_stats=shop_stats.get(int(r["id"]))) for r in shop_rows]

        bike_sql = """
            SELECT b.*,
                   s.shop_name AS shop_name,
                   s.slug AS shop_slug,
                   s.logo_url AS shop_logo_url,
                   s.cover_url AS shop_cover_url,
                   s.municipality AS shop_municipality,
                   s.address AS shop_address,
                   s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp,
                   s.delivery_fee AS shop_delivery_fee,
                   s.contract_terms AS shop_contract_terms,
                   s.status AS shop_status
            FROM bikes b
            JOIN shops s ON s.id = b.shop_id
            WHERE b.status != 'hidden'
              AND s.status = 'approved'
        """
        bike_params: list = []
        if featured_shop and featured_shop.get("id"):
            bike_sql += " AND b.shop_id = ?"
            bike_params.append(int(featured_shop["id"]))
        bike_sql += " ORDER BY b.featured DESC, b.daily_rate ASC"
        bike_rows = conn.execute(bike_sql, bike_params).fetchall()
        schedules = build_bike_schedules(
            conn,
            bike_rows,
            ref_pickup_date=today_str,
            ref_return_date=None,
            include_calendar=False,
            include_admin_details=False,
        )
        bikes_list = []
        ratings_map = get_all_bike_rating_stats(conn)
        for row in bike_rows:
            sched = schedules.get(int(row["id"]))
            booked = int((sched or {}).get("ref_booked_units", 0))
            bikes_list.append(
                _serialize_bike(
                    row,
                    booked_units=booked,
                    schedule=sched,
                    rating_stats=ratings_map.get(int(row["id"])),
                )
            )
        return {
            "shops": shops_list,
            "bikes": bikes_list,
            "pickup_date": today_str,
            "shop_id": str(featured_shop["id"]) if featured_shop and featured_shop.get("id") else "",
        }

    # ------------------------------------------------------------------
    # Page & PWA Routes
    # ------------------------------------------------------------------
    @app.get("/")
    def home():
        conn = get_db()
        shop_ref = (request.args.get("shop") or "").strip()
        featured_shop = _find_featured_shop(conn, shop_ref) if shop_ref else None
        return render_template(
            "index.html",
            active_nav="fleet",
            featured_shop=featured_shop,
            storefront_bootstrap=_build_storefront_bootstrap(conn, featured_shop),
            recent_reviews=get_recent_reviews(conn, limit=6),
        )

    @app.get("/shop/<slug>")
    def public_shop_profile_page(slug: str):
        conn = get_db()
        featured_shop = _find_featured_shop(conn, slug)
        return render_template(
            "index.html",
            active_nav="fleet",
            featured_shop=featured_shop,
            storefront_bootstrap=_build_storefront_bootstrap(conn, featured_shop),
            recent_reviews=get_recent_reviews(conn, limit=6),
        )

    @app.get("/customer")
    @app.get("/bookings")
    def bookings_page():
        return render_template("bookings.html", active_nav="customer")

    @app.get("/bookings/<booking_code>/contract")
    @app.get("/bookings/<booking_code>/receipt")
    def view_booking_contract(booking_code: str):
        conn = get_db()
        code = booking_code.strip().upper()
        row = conn.execute(
            """
            SELECT b.*,
                   k.name AS bike_name, k.image_url AS bike_image,
                   k.category AS bike_category, k.transmission AS bike_transmission,
                   k.plate_number AS plate_number,
                   s.shop_name AS shop_name, s.municipality AS shop_municipality,
                   s.address AS shop_address, s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp,
                   s.contract_terms AS shop_contract_terms
            FROM bookings b
            JOIN bikes k ON k.id = b.bike_id
            JOIN shops s ON s.id = b.shop_id
            WHERE UPPER(b.booking_code) = ?
            """,
            (code,),
        ).fetchone()

        if not row:
            return redirect("/customer?not_found=1")

        partner_id = int(session.get("partner_shop_id") or 0)
        is_admin = bool(session.get("is_admin"))
        is_shop = partner_id == int(row["shop_id"])
        phone_param = (request.args.get("phone") or "").strip()
        is_customer = bool(phone_param and _phones_match(row["customer_phone"], phone_param))

        if not (is_admin or is_shop or is_customer):
            return redirect(f"/customer?code={code}")

        booking_data = _serialize_booking(row)
        return render_template(
            "contract_print.html",
            b=booking_data,
        )

    @app.get("/shop")
    @app.get("/rider")
    @app.get("/partner")
    def partner_page():
        return render_template("partner.html", active_nav="shop")

    @app.get("/admin")
    def admin_page():
        return render_template("admin.html", active_nav="admin")

    @app.get("/offline")
    def offline_page():
        return render_template("offline.html", active_nav="")

    @app.get("/admin.webmanifest")
    def admin_manifest():
        return manifest(admin_app=True)

    @app.get("/manifest.webmanifest")
    def manifest(admin_app: bool = False):
        shop = get_settings(get_db())
        shop_name = shop.get("shop_name", "Motorbike Rentals Camiguin")
        short_name = (
            shop_name
            if len(shop_name) <= 15
            else (shop_name.split()[-1] if len(shop_name.split()[-1]) <= 15 else shop_name[:12].strip())
        )
        payload = {
            "id": "/",
            "name": shop_name,
            "short_name": short_name,
            "description": shop.get(
                "tagline",
                "Centralized Camiguin island motorbike rentals from verified local shops.",
            ),
            "start_url": "/?source=pwa",
            "scope": "/",
            "display": "standalone",
            "orientation": "portrait-primary",
            "background_color": "#0f172a",
            "theme_color": "#f97316",
            "categories": ["travel", "lifestyle", "navigation"],
            "icons": [
                {
                    "src": "/static/icons/icon-192.png",
                    "sizes": "192x192",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/static/icons/icon-512.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "any",
                },
                {
                    "src": "/static/icons/icon-maskable.png",
                    "sizes": "512x512",
                    "type": "image/png",
                    "purpose": "maskable",
                },
                {
                    "src": "/static/icons/icon.svg",
                    "sizes": "any",
                    "type": "image/svg+xml",
                    "purpose": "any",
                },
            ],
            "shortcuts": [
                {
                    "name": "Browse Motorbikes",
                    "short_name": "Fleet",
                    "url": "/#fleet",
                    "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"}],
                },
                {
                    "name": "My Bookings",
                    "short_name": "My Trips",
                    "url": "/bookings",
                    "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"}],
                },
                {
                    "name": "Shop Portal",
                    "short_name": "Shop",
                    "url": "/shop",
                    "icons": [{"src": "/static/icons/icon-192.png", "sizes": "192x192", "type": "image/png"}],
                },
            ],
        }
        if admin_app:
            payload["id"] = "/admin"
            payload["name"] = f"{shop_name} Admin"
            payload["short_name"] = "Admin"
            payload["description"] = "Admin dashboard for platform owner."
            payload["start_url"] = "/admin?source=pwa"
            payload["scope"] = "/admin"
            payload["shortcuts"] = []
        resp = make_response(jsonify(payload))
        resp.headers["Content-Type"] = "application/manifest+json; charset=utf-8"
        resp.headers["Cache-Control"] = "no-cache"
        return resp

    @app.get("/uploads/<path:filename>")
    def uploaded_file(filename: str):
        media = get_uploaded_media(get_db(), filename)
        if media:
            resp = Response(bytes(media["data"]), mimetype=media["content_type"])
            resp.headers["Cache-Control"] = "public, max-age=86400"
            return resp
        return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

    @app.get("/sw.js")
    def service_worker():
        sw_path = os.path.join(BASE_DIR, "static", "sw.js")
        with open(sw_path, "r", encoding="utf-8") as f:
            sw_code = f.read()
        resp = make_response(sw_code)
        resp.headers["Content-Type"] = "application/javascript; charset=utf-8"
        resp.headers["Service-Worker-Allowed"] = "/"
        resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        return resp

    # ------------------------------------------------------------------
    # Public API Routes
    # ------------------------------------------------------------------
    @app.get("/api/health")
    def health():
        backend = "postgresql" if is_postgres_url(app.config.get("DATABASE_URL")) else "sqlite"
        if (request.args.get("db") or "").strip().lower() in ("1", "true", "yes"):
            conn = get_db()
            conn.execute("SELECT 1").fetchone()
            backend = conn.backend
        return jsonify({"status": "ok", "backend": backend, "date": date.today().isoformat()})

    @app.get("/api/settings")
    def public_settings():
        return jsonify({"settings": get_settings(get_db())})

    @app.get("/api/shops")
    def list_public_shops():
        conn = get_db()
        rows = conn.execute(
            """
            SELECT s.*,
                   COUNT(CASE WHEN b.status != 'hidden' THEN 1 END) AS bike_count
            FROM shops s
            LEFT JOIN bikes b ON b.shop_id = s.id
            WHERE s.status = 'approved'
            GROUP BY s.id
            ORDER BY s.is_main DESC, s.shop_name ASC
            """
        ).fetchall()
        shop_stats = get_all_shop_rating_stats(conn)
        return jsonify(
            {
                "shops": [_serialize_shop(r, rating_stats=shop_stats.get(int(r["id"]))) for r in rows],
                "municipalities": list(CAMIGUIN_MUNICIPALITIES),
            }
        )

    @app.get("/api/shops/<slug>")
    def get_public_shop(slug: str):
        shop_data = _find_featured_shop(get_db(), slug)
        if not shop_data:
            return jsonify({"error": "Partner shop not found."}), 404
        return jsonify({"shop": shop_data})

    @app.get("/api/bikes")
    def list_bikes():
        conn = get_db()
        category = (request.args.get("category") or "").strip()
        transmission = (request.args.get("transmission") or "").strip()
        municipality = (request.args.get("municipality") or "").strip()
        shop_id = request.args.get("shop_id", type=int)
        q = (request.args.get("q") or "").strip().lower()
        sort = (request.args.get("sort") or "featured").strip()
        pickup_date = (request.args.get("pickup_date") or "").strip()
        return_date = (request.args.get("return_date") or "").strip()
        available_only = (request.args.get("available_only") or "").lower() in ("1", "true")

        has_explicit_return = bool(return_date)
        if return_date and not pickup_date:
            return jsonify({"error": "Pickup date is required when return date is specified."}), 400

        if pickup_date:
            try:
                p_dt = parse_iso_date(pickup_date)
                effective_return = return_date or pickup_date
                r_dt = parse_iso_date(effective_return)
                if r_dt < p_dt:
                    return jsonify({"error": "Return date cannot be earlier than pickup date."}), 400
                return_date = effective_return
            except ValueError:
                return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400
        else:
            today_str = date.today().isoformat()
            pickup_date = today_str
            return_date = today_str

        sql = """
            SELECT b.*,
                   s.shop_name AS shop_name,
                   s.slug AS shop_slug,
                   s.logo_url AS shop_logo_url,
                   s.cover_url AS shop_cover_url,
                   s.municipality AS shop_municipality,
                   s.address AS shop_address,
                   s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp,
                   s.delivery_fee AS shop_delivery_fee,
                   s.contract_terms AS shop_contract_terms,
                   s.status AS shop_status
            FROM bikes b
            JOIN shops s ON s.id = b.shop_id
            WHERE b.status != 'hidden'
              AND s.status = 'approved'
        """
        params: list = []

        if category and category.lower() != "all":
            sql += " AND b.category = ?"
            params.append(category)
        if transmission and transmission.lower() != "all":
            sql += " AND b.transmission = ?"
            params.append(transmission)
        if municipality and municipality.lower() != "all":
            sql += " AND s.municipality = ?"
            params.append(municipality)
        if shop_id:
            sql += " AND b.shop_id = ?"
            params.append(shop_id)
        if q:
            sql += """
                AND (
                    LOWER(b.name) LIKE ?
                    OR LOWER(b.description) LIKE ?
                    OR LOWER(b.category) LIKE ?
                    OR LOWER(s.shop_name) LIKE ?
                    OR LOWER(s.municipality) LIKE ?
                )
            """
            like = f"%{q}%"
            params.extend([like, like, like, like, like])

        sort_map = {
            "featured": "b.featured DESC, b.daily_rate ASC",
            "price_asc": "b.daily_rate ASC, b.engine_cc ASC",
            "price_desc": "b.daily_rate DESC, b.engine_cc DESC",
            "cc_desc": "b.engine_cc DESC, b.daily_rate ASC",
        }
        order_clause = sort_map.get(sort, sort_map["featured"])
        sql += f" ORDER BY {order_clause}"

        rows = conn.execute(sql, params).fetchall()
        schedules = build_bike_schedules(
            conn,
            rows,
            ref_pickup_date=pickup_date,
            ref_return_date=return_date if has_explicit_return else None,
            include_calendar=False,
            include_admin_details=False,
        )
        today_iso = date.today().isoformat()
        ratings_map = get_all_bike_rating_stats(conn)
        bikes = []
        for row in rows:
            sched = schedules.get(int(row["id"]))
            if pickup_date >= today_iso and sched is not None and "ref_booked_units" in sched:
                booked = int(sched["ref_booked_units"])
            else:
                booked = count_overlapping_bookings(conn, row["id"], pickup_date, return_date)
            item = _serialize_bike(
                row,
                booked_units=booked,
                schedule=sched,
                rating_stats=ratings_map.get(int(row["id"])),
            )
            if available_only and not item["is_available"]:
                continue
            bikes.append(item)

        return jsonify(
            {
                "bikes": bikes,
                "pickup_date": pickup_date,
                "return_date": return_date,
                "categories": list(VALID_CATEGORIES),
            }
        )

    @app.get("/api/bikes/<int:bike_id>")
    def get_bike(bike_id: int):
        conn = get_db()
        row = conn.execute(
            """
            SELECT b.*,
                   s.shop_name AS shop_name,
                   s.slug AS shop_slug,
                   s.logo_url AS shop_logo_url,
                   s.cover_url AS shop_cover_url,
                   s.municipality AS shop_municipality,
                   s.address AS shop_address,
                   s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp,
                   s.delivery_fee AS shop_delivery_fee,
                   s.contract_terms AS shop_contract_terms,
                   s.status AS shop_status
            FROM bikes b
            JOIN shops s ON s.id = b.shop_id
            WHERE b.id = ? AND b.status != 'hidden' AND s.status = 'approved'
            """,
            (bike_id,),
        ).fetchone()
        if not row:
            return jsonify({"error": "Motorbike not found."}), 404

        pickup_date = (request.args.get("pickup_date") or date.today().isoformat()).strip()
        explicit_return = (request.args.get("return_date") or "").strip()
        return_date = explicit_return or pickup_date
        try:
            p_dt = parse_iso_date(pickup_date)
            r_dt = parse_iso_date(return_date)
            if r_dt < p_dt:
                return jsonify({"error": "Return date cannot be earlier than pickup date."}), 400
        except ValueError:
            return jsonify({"error": "Invalid date format."}), 400

        booked = count_overlapping_bookings(conn, bike_id, pickup_date, return_date)
        sched = build_bike_schedules(
            conn,
            [row],
            ref_pickup_date=pickup_date,
            ref_return_date=explicit_return or None,
            include_calendar=True,
            include_admin_details=False,
        ).get(bike_id)
        rating_stats = get_bike_rating_stats(conn, bike_id)
        reviews = get_bike_reviews(conn, bike_id, limit=6)
        bike_data = _serialize_bike(row, booked_units=booked, schedule=sched, rating_stats=rating_stats)
        bike_data["reviews"] = reviews
        return jsonify({"bike": bike_data})

    @app.get("/api/quote")
    def quote_booking():
        conn = get_db()
        bike_id = request.args.get("bike_id", type=int)
        pickup_date = (request.args.get("pickup_date") or "").strip()
        return_date = (request.args.get("return_date") or "").strip()
        pickup_method = (request.args.get("pickup_method") or "shop").strip().lower()
        extra_helmet = (request.args.get("extra_helmet") or "").lower() in ("1", "true", "yes")
        top_box = (request.args.get("top_box") or "").lower() in ("1", "true", "yes")

        if not bike_id or not pickup_date or not return_date:
            return jsonify({"error": "bike_id, pickup_date, and return_date are required."}), 400
        if pickup_method not in ("shop", "delivery"):
            return jsonify({"error": "pickup_method must be 'shop' or 'delivery'."}), 400

        bike = conn.execute(
            """
            SELECT b.*, s.delivery_fee AS shop_delivery_fee, s.status AS shop_status
            FROM bikes b
            JOIN shops s ON s.id = b.shop_id
            WHERE b.id = ? AND b.status != 'hidden' AND s.status = 'approved'
            """,
            (bike_id,),
        ).fetchone()
        if not bike:
            return jsonify({"error": "Motorbike not found."}), 404

        shop_row = conn.execute("SELECT * FROM shops WHERE id = ?", (bike["shop_id"],)).fetchone()
        try:
            settings = get_settings(conn)
            quote = calculate_quote(
                bike,
                settings,
                pickup_date,
                return_date,
                pickup_method=pickup_method,
                extra_helmet=extra_helmet,
                top_box=top_box,
                shop=shop_row,
            )
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        booked = count_overlapping_bookings(conn, bike_id, pickup_date, return_date)
        units_count = int(bike["units_count"] or 1)
        available_units = max(0, units_count - booked) if bike["status"] == "available" else 0
        quote["units_count"] = units_count
        quote["booked_units"] = booked
        quote["available_units"] = available_units
        quote["is_available"] = bike["status"] == "available" and available_units > 0
        quote["bike_status"] = bike["status"]
        return jsonify({"quote": quote})

    @app.post("/api/bookings")
    def create_booking():
        if request.content_type and "multipart/form-data" in request.content_type:
            payload = request.form
            proof_file = request.files.get("payment_proof")
            license_file = request.files.get("license_photo")
        else:
            payload = request.get_json(silent=True) or {}
            proof_file = None
            license_file = None

        signature_data = (payload.get("signature_data") or "").strip()
        contract_agreed = _as_bool(payload.get("contract_agreed"), default=False)

        bike_id = payload.get("bike_id")
        customer_name = (payload.get("customer_name") or "").strip()
        customer_phone = (payload.get("customer_phone") or "").strip()
        customer_email = (payload.get("customer_email") or "").strip()
        customer_address = (payload.get("customer_address") or "").strip()
        license_number = (payload.get("license_number") or "").strip()
        pickup_date = (payload.get("pickup_date") or "").strip()
        return_date = (payload.get("return_date") or "").strip()
        pickup_time = (payload.get("pickup_time") or "09:00").strip()
        pickup_method = (payload.get("pickup_method") or "shop").strip().lower()
        delivery_address = (payload.get("delivery_address") or "").strip()
        delivery_lat_raw = payload.get("delivery_lat")
        delivery_lng_raw = payload.get("delivery_lng")
        delivery_lat = None
        delivery_lng = None
        if delivery_lat_raw is not None and str(delivery_lat_raw).strip():
            try:
                delivery_lat = float(delivery_lat_raw)
            except (ValueError, TypeError):
                delivery_lat = None
        if delivery_lng_raw is not None and str(delivery_lng_raw).strip():
            try:
                delivery_lng = float(delivery_lng_raw)
            except (ValueError, TypeError):
                delivery_lng = None
        extra_helmet = _as_bool(payload.get("extra_helmet"), default=False)
        top_box = _as_bool(payload.get("top_box"), default=False)
        notes = (payload.get("notes") or "").strip()
        payment_channel = str(payload.get("payment_channel") or "pay_at_shop").strip().lower()
        payment_reference = str(payload.get("payment_reference") or "").strip()

        if not bike_id or not isinstance(bike_id, int):
            try:
                bike_id = int(bike_id)
            except (TypeError, ValueError):
                return jsonify({"error": "Please select a valid motorbike."}), 400

        if not customer_name:
            return jsonify({"error": "Full name is required."}), 400
        if len(_normalize_phone(customer_phone)) < 7:
            return jsonify({"error": "Please provide a valid mobile or WhatsApp number."}), 400
        if not license_number:
            return jsonify({"error": "Driver's license number is required."}), 400
        if pickup_method not in ("shop", "delivery"):
            return jsonify({"error": "Invalid pickup method."}), 400
        if pickup_method == "delivery" and not delivery_address:
            return jsonify({"error": "Please enter your resort, port, or delivery address."}), 400
        if payment_channel not in ("pay_at_shop", "gcash", "maya", "paymongo"):
            return jsonify({"error": "Invalid payment method selected."}), 400
        try:
            validated_proof = _validate_image_upload(proof_file, prefix="proof")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        validated_license = None
        if license_file:
            try:
                validated_license = _validate_image_upload(license_file, prefix="license")
            except ValueError as exc:
                return jsonify({"error": f"Driver's License upload: {exc}"}), 400

        validated_signature = None
        if signature_data:
            try:
                raw_b64 = signature_data.split(",", 1)[1] if "," in signature_data else signature_data
                sig_bytes = base64.b64decode(raw_b64)
                if len(sig_bytes) > 0 and len(sig_bytes) <= 2 * 1024 * 1024:
                    sig_name = f"sig_{secrets.token_hex(8)}.png"
                    validated_signature = (sig_name, sig_bytes, "image/png")
            except Exception:
                pass

        try:
            p_dt = parse_iso_date(pickup_date)
            r_dt = parse_iso_date(return_date)
        except ValueError:
            return jsonify({"error": "Please choose valid pickup and return dates."}), 400

        if p_dt < date.today():
            return jsonify({"error": "Pickup date cannot be in the past."}), 400
        if r_dt < p_dt:
            return jsonify({"error": "Return date cannot be earlier than pickup date."}), 400

        conn = get_db()
        try:
            bike = conn.begin_booking_lock(bike_id)
            if not bike or bike["status"] == "hidden":
                conn.rollback()
                return jsonify({"error": "Selected motorbike was not found."}), 404

            shop_row = conn.execute("SELECT * FROM shops WHERE id = ?", (bike["shop_id"],)).fetchone()
            if not shop_row or shop_row["status"] != "approved":
                conn.rollback()
                return jsonify({"error": "This rental partner shop is not currently accepting bookings."}), 409

            if bike["status"] != "available":
                conn.rollback()
                return jsonify({"error": f"{bike['name']} is currently under maintenance."}), 409

            booked = count_overlapping_bookings(conn, bike_id, pickup_date, return_date)
            units_count = int(bike["units_count"] or 1)
            if booked >= units_count:
                conn.rollback()
                return (
                    jsonify(
                        {
                            "error": (
                                f"Sorry, all units of {bike['name']} are already booked for "
                                f"{pickup_date} to {return_date}. Please pick different dates or another bike."
                            )
                        }
                    ),
                    409,
                )

            settings = get_settings(conn, include_secrets=True)
            quote = calculate_quote(
                bike,
                settings,
                pickup_date,
                return_date,
                pickup_method=pickup_method,
                extra_helmet=extra_helmet,
                top_box=top_box,
                shop=shop_row,
            )

            payment_active = (
                (
                    quote["reservation_mode"] != "off"
                    and quote["reservation_configured"]
                    and quote["reservation_fee"] > 0
                )
                or (payment_channel == "paymongo" and is_reservation_payment_configured(settings))
            )
            if not payment_active:
                stored_channel = "pay_at_shop"
                stored_reference = ""
                stored_proof_url = ""
                stored_payment_status = "unpaid"
                stored_reservation_fee = 0.0
                stored_balance_due = quote["total_amount"]
            elif payment_channel == "pay_at_shop":
                if quote["reservation_mode"] == "required":
                    conn.rollback()
                    return (
                        jsonify(
                            {
                                "error": (
                                    "Reservation fee payment via GCash or Maya is required to "
                                    "submit this booking request."
                                )
                            }
                        ),
                        400,
                    )
                stored_channel = "pay_at_shop"
                stored_reference = ""
                stored_proof_url = ""
                stored_payment_status = "unpaid"
                stored_reservation_fee = 0.0
                stored_balance_due = quote["total_amount"]
            elif payment_channel == "paymongo":
                stored_channel = "paymongo"
                stored_reference = ""
                stored_proof_url = ""
                stored_payment_status = "unpaid"
                stored_reservation_fee = (
                    quote["reservation_fee"]
                    if quote["reservation_fee"] > 0
                    else quote["total_amount"]
                )
                stored_balance_due = max(0.0, round(quote["total_amount"] - stored_reservation_fee, 2))
            else:
                if payment_reference and len(payment_reference) < 6:
                    conn.rollback()
                    return (
                        jsonify(
                            {
                                "error": (
                                    "Please enter your full GCash / Maya Reference No. "
                                    "(at least 6 characters)."
                                )
                            }
                        ),
                        400,
                    )
                if not payment_reference and validated_proof is None:
                    conn.rollback()
                    return (
                        jsonify(
                            {
                                "error": (
                                    "Please enter your GCash / Maya Reference No. or upload "
                                    "your payment receipt screenshot."
                                )
                            }
                        ),
                        400,
                    )
                stored_proof_url = (
                    _save_validated_image(conn, validated_proof, use_tx=False)
                    if validated_proof is not None
                    else ""
                )
                stored_channel = payment_channel
                stored_reference = payment_reference
                stored_payment_status = "submitted"
                stored_reservation_fee = quote["reservation_fee"]
                stored_balance_due = quote["balance_due"]

            booking_code = generate_booking_code(conn)
            now = datetime.now().isoformat(timespec="seconds")

            booking_id = conn.insert_returning_id(
                """
                INSERT INTO bookings (
                    booking_code, bike_id, shop_id, customer_name, customer_phone, customer_email,
                    customer_address, license_number, pickup_date, return_date, pickup_time, pickup_method,
                    delivery_address, delivery_lat, delivery_lng, extra_helmet, top_box, rental_days, base_subtotal,
                    addons_total, delivery_total, total_amount, commission_rate, platform_fee,
                    shop_payout, reservation_fee, balance_due, payment_channel, payment_reference,
                    payment_proof_url, payment_status, deposit_amount, notes, admin_notes, status,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', 'pending', ?, ?)
                """,
                (
                    booking_code,
                    bike_id,
                    shop_row["id"],
                    customer_name,
                    customer_phone,
                    customer_email,
                    customer_address,
                    license_number,
                    pickup_date,
                    return_date,
                    pickup_time,
                    pickup_method,
                    delivery_address,
                    delivery_lat,
                    delivery_lng,
                    1 if extra_helmet else 0,
                    1 if top_box else 0,
                    quote["rental_days"],
                    quote["base_subtotal"],
                    quote["addons_total"],
                    quote["delivery_total"],
                    quote["total_amount"],
                    quote["commission_rate"],
                    quote["platform_fee"],
                    quote["shop_payout"],
                    stored_reservation_fee,
                    stored_balance_due,
                    stored_channel,
                    stored_reference,
                    stored_proof_url,
                    stored_payment_status,
                    quote["deposit_amount"],
                    notes,
                    now,
                    now,
                ),
            )

            stored_license_url = ""
            if validated_license:
                stored_license_url = _save_validated_image(conn, validated_license, use_tx=False)
            stored_sig_url = ""
            if validated_signature:
                stored_sig_url = _save_validated_image(conn, validated_signature, use_tx=False)
            contract_signed_at = now if (contract_agreed or stored_sig_url) else None

            if stored_license_url or stored_sig_url or contract_agreed:
                conn.execute(
                    "UPDATE bookings SET license_photo_url = ?, signature_url = ?, contract_agreed = ?, contract_signed_at = ? WHERE id = ?",
                    (stored_license_url, stored_sig_url, 1 if contract_agreed else 0, contract_signed_at, booking_id),
                )

            conn.commit()
        except Exception:
            conn.rollback()
            raise

        created = _fetch_booking_by_id(conn, booking_id)
        booking_data = _serialize_booking(created)

        checkout_url = ""
        if stored_channel == "paymongo":
            secret_settings = get_settings(conn, include_secrets=True)
            pm_key = secret_settings.get("paymongo_secret_key")
            if pm_key:
                charge_amount = stored_reservation_fee if stored_reservation_fee >= 20 else quote["total_amount"]
                ok, link_res = create_payment_link(
                    secret_key=pm_key,
                    amount_php=charge_amount,
                    description=f"Motoride Camiguin — {quote['rental_days']}d {bike['name']} ({booking_code})",
                    remarks=booking_code,
                )
                if ok and isinstance(link_res, dict):
                    checkout_url = link_res.get("checkout_url", "")
                    link_id = link_res.get("link_id", "")
                    with conn:
                        conn.execute(
                            "UPDATE bookings SET payment_link_id = ?, payment_checkout_url = ? WHERE id = ?",
                            (link_id, checkout_url, booking_id),
                        )
                    created = _fetch_booking_by_id(conn, booking_id)
                    booking_data = _serialize_booking(created)

        _dispatch_alert(
            notify_new_booking,
            get_settings(conn, include_secrets=True),
            _serialize_shop(shop_row, include_private=True),
            booking_data,
        )
        resp_data = {"booking": booking_data, "quote": quote}
        if checkout_url:
            resp_data["checkout_url"] = checkout_url
        return jsonify(resp_data), 201

    def _fetch_booking_by_id(conn, booking_id: int):
        return conn.execute(
            """
            SELECT b.*,
                   k.name AS bike_name, k.image_url AS bike_image,
                   k.category AS bike_category, k.transmission AS bike_transmission,
                   k.plate_number AS plate_number,
                   s.shop_name AS shop_name, s.municipality AS shop_municipality,
                   s.address AS shop_address, s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp
            FROM bookings b
            JOIN bikes k ON k.id = b.bike_id
            JOIN shops s ON s.id = b.shop_id
            WHERE b.id = ?
            """,
            (booking_id,),
        ).fetchone()

    @app.get("/api/bookings/lookup")
    def lookup_booking():
        code = (request.args.get("code") or "").strip().upper()
        phone = _normalize_phone(request.args.get("phone") or "")
        if not code or len(phone) < 4:
            return (
                jsonify(
                    {
                        "error": "Enter both your Booking Code and phone number (or last 4+ digits)."
                    }
                ),
                400,
            )

        conn = get_db()
        row = conn.execute(
            """
            SELECT b.*,
                   k.name AS bike_name, k.image_url AS bike_image,
                   k.category AS bike_category, k.transmission AS bike_transmission,
                   k.plate_number AS plate_number,
                   s.shop_name AS shop_name, s.municipality AS shop_municipality,
                   s.address AS shop_address, s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp
            FROM bookings b
            JOIN bikes k ON k.id = b.bike_id
            JOIN shops s ON s.id = b.shop_id
            WHERE UPPER(b.booking_code) = ?
            """,
            (code,),
        ).fetchone()

        if not row:
            return jsonify({"error": "No booking found with that reference code."}), 404

        if not _phones_match(row["customer_phone"], request.args.get("phone") or ""):
            return jsonify({"error": "Phone number does not match this booking reference."}), 403

        return jsonify({"booking": _serialize_booking(row)})

    @app.post("/api/bookings/cancel")
    def customer_cancel_booking():
        payload = request.get_json(silent=True) or {}
        code = (payload.get("booking_code") or "").strip().upper()
        raw_phone = payload.get("customer_phone") or ""
        if not code or len(_normalize_phone(raw_phone)) < 4:
            return jsonify({"error": "Booking code and phone number are required."}), 400

        conn = get_db()
        row = conn.execute("SELECT * FROM bookings WHERE UPPER(booking_code) = ?", (code,)).fetchone()
        if not row:
            return jsonify({"error": "Booking not found."}), 404

        if not _phones_match(row["customer_phone"], raw_phone):
            return jsonify({"error": "Phone number does not match this booking."}), 403

        if row["status"] != "pending":
            return (
                jsonify(
                    {
                        "error": (
                            f"Only pending bookings can be self-cancelled (current status: {row['status']}). "
                            "Please contact the rental shop directly."
                        )
                    }
                ),
                409,
            )

        now = datetime.now().isoformat(timespec="seconds")
        with conn:
            conn.execute(
                "UPDATE bookings SET status = 'cancelled', updated_at = ? WHERE id = ?",
                (now, row["id"]),
            )
        updated = _fetch_booking_by_id(conn, row["id"])
        booking_data = _serialize_booking(updated)
        shop_row = conn.execute("SELECT * FROM shops WHERE id = ?", (row["shop_id"],)).fetchone()
        if shop_row:
            _dispatch_alert(
                notify_booking_cancelled_by_customer,
                get_settings(conn, include_secrets=True),
                _serialize_shop(shop_row, include_private=True),
                booking_data,
            )
        return jsonify({"booking": booking_data})

    # ------------------------------------------------------------------
    # Customer Reviews & 5-Star Rating Routes
    # ------------------------------------------------------------------
    @app.post("/api/reviews")
    def submit_review():
        conn = get_db()
        payload = request.get_json(silent=True) or {}
        bike_id = payload.get("bike_id")
        booking_code = (payload.get("booking_code") or "").strip().upper()
        customer_name = (payload.get("customer_name") or "").strip()
        comment = (payload.get("comment") or "").strip()
        rating_raw = payload.get("rating")

        try:
            rating = int(rating_raw)
            if rating < 1 or rating > 5:
                raise ValueError()
        except (TypeError, ValueError):
            return jsonify({"error": "Please provide a valid rating between 1 and 5 stars."}), 400

        booking_id = None
        shop_id = None

        if booking_code:
            b_row = conn.execute("SELECT * FROM bookings WHERE UPPER(booking_code) = ?", (booking_code,)).fetchone()
            if b_row:
                booking_id = int(b_row["id"])
                bike_id = int(b_row["bike_id"])
                shop_id = int(b_row["shop_id"])
                if not customer_name:
                    customer_name = b_row["customer_name"]

        if not customer_name:
            return jsonify({"error": "Please provide your name or nickname."}), 400

        if not bike_id:
            return jsonify({"error": "Please specify which motorbike you are reviewing."}), 400

        if not shop_id:
            bike_row = conn.execute("SELECT shop_id FROM bikes WHERE id = ?", (bike_id,)).fetchone()
            if not bike_row:
                return jsonify({"error": "Motorbike not found."}), 404
            shop_id = int(bike_row["shop_id"])

        rev_id = create_review(
            conn=conn,
            bike_id=bike_id,
            shop_id=shop_id,
            customer_name=customer_name,
            rating=rating,
            comment=comment,
            booking_id=booking_id,
        )
        conn.commit()
        return jsonify({
            "ok": True,
            "success": True,
            "review_id": rev_id,
            "review": {
                "id": rev_id,
                "bike_id": bike_id,
                "rating": rating,
                "customer_name": customer_name,
                "comment": comment,
            },
            "message": "Thank you! Your review has been submitted.",
        }), 201

    @app.get("/api/reviews")
    def list_recent_reviews():
        conn = get_db()
        limit = min(50, max(1, request.args.get("limit", default=12, type=int)))
        return jsonify({"reviews": get_recent_reviews(conn, limit=limit)})

    @app.get("/api/reviews/bike/<int:bike_id>")
    def list_bike_reviews(bike_id: int):
        conn = get_db()
        return jsonify({
            "reviews": get_bike_reviews(conn, bike_id, limit=20),
            "stats": get_bike_rating_stats(conn, bike_id),
        })

    @app.get("/api/reviews/shop/<int:shop_id>")
    def list_shop_reviews(shop_id: int):
        conn = get_db()
        return jsonify({
            "reviews": get_shop_reviews(conn, shop_id, limit=20),
            "stats": get_shop_rating_stats(conn, shop_id),
        })

    # ------------------------------------------------------------------
    # PayMongo Online Payment & Webhook Routes
    # ------------------------------------------------------------------
    @app.post("/api/webhooks/paymongo")
    def paymongo_webhook():
        conn = get_db()
        raw_payload = request.get_data()
        signature_header = request.headers.get("Paymongo-Signature", "")

        secret_settings = get_settings(conn, include_secrets=True)
        webhook_secret = secret_settings.get("paymongo_webhook_secret", "")

        if webhook_secret:
            if not verify_webhook_signature(raw_payload, signature_header, webhook_secret):
                return jsonify({"error": "Invalid signature"}), 400

        try:
            event_payload = json.loads(raw_payload.decode("utf-8"))
        except Exception:
            return jsonify({"error": "Invalid JSON"}), 400

        details = extract_payment_details_from_webhook(event_payload)
        if not details:
            return jsonify({"received": True, "handled": False}), 200

        link_id = details.get("link_id")
        remarks = details.get("remarks")

        booking_row = None
        if link_id:
            booking_row = conn.execute(
                "SELECT * FROM bookings WHERE payment_link_id = ?", (link_id,)
            ).fetchone()
        if not booking_row and remarks:
            booking_row = conn.execute(
                "SELECT * FROM bookings WHERE booking_code = ?", (remarks,)
            ).fetchone()

        if not booking_row:
            return jsonify({"received": True, "booking_not_found": True}), 200

        booking_id = int(booking_row["id"])
        now = datetime.now().isoformat(timespec="seconds")

        if booking_row["payment_status"] == "verified":
            return jsonify({"received": True, "already_verified": True}), 200

        payment_id = details.get("payment_id") or ""
        ref_to_save = payment_id or booking_row["payment_reference"] or ""

        with conn:
            conn.execute(
                """
                UPDATE bookings
                SET status = CASE WHEN status = 'pending' THEN 'confirmed' ELSE status END,
                    payment_status = 'verified',
                    payment_channel = 'paymongo',
                    payment_reference = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (ref_to_save, now, booking_id),
            )

        updated_row = _fetch_booking_by_id(conn, booking_id)
        if updated_row:
            booking_data = _serialize_booking(updated_row)
            shop_row = conn.execute(
                "SELECT * FROM shops WHERE id = ?", (updated_row["shop_id"],)
            ).fetchone()
            shop_data = _serialize_shop(shop_row, include_private=True) if shop_row else {}
            _dispatch_alert(
                notify_payment_verified,
                secret_settings,
                shop_data,
                booking_data,
                details,
            )

        return jsonify({"received": True, "verified": True, "booking_code": booking_row["booking_code"]}), 200

    @app.post("/api/bookings/<int:booking_id>/paymongo-link")
    def generate_booking_paymongo_link(booking_id: int):
        conn = get_db()
        booking = _fetch_booking_by_id(conn, booking_id)
        if not booking:
            return jsonify({"error": "Booking not found."}), 404

        if booking["payment_status"] == "verified":
            return jsonify({"error": "Booking payment has already been verified."}), 400

        if booking["payment_checkout_url"]:
            return jsonify(
                {
                    "checkout_url": booking["payment_checkout_url"],
                    "link_id": booking["payment_link_id"],
                    "booking_code": booking["booking_code"],
                }
            )

        secret_settings = get_settings(conn, include_secrets=True)
        pm_key = secret_settings.get("paymongo_secret_key")
        if not pm_key:
            return jsonify({"error": "Online payment is not configured on this platform."}), 400

        res_fee = float(booking["reservation_fee"] or 0)
        total_amt = float(booking["total_price"] or 0)
        charge_amount = res_fee if res_fee >= 20 else total_amt

        bike_name = booking["bike_name"] if "bike_name" in booking.keys() else "Motorbike"
        desc = f"Motoride Camiguin — {booking['booking_code']} ({bike_name})"
        ok, link_res = create_payment_link(
            secret_key=pm_key,
            amount_php=charge_amount,
            description=desc,
            remarks=booking["booking_code"],
        )
        if not ok or not isinstance(link_res, dict):
            return jsonify({"error": f"Failed to generate payment link: {link_res}"}), 502

        checkout_url = link_res.get("checkout_url", "")
        link_id = link_res.get("link_id", "")
        with conn:
            conn.execute(
                "UPDATE bookings SET payment_link_id = ?, payment_checkout_url = ?, payment_channel = 'paymongo' WHERE id = ?",
                (link_id, checkout_url, booking_id),
            )

        return jsonify(
            {
                "checkout_url": checkout_url,
                "link_id": link_id,
                "booking_code": booking["booking_code"],
            }
        )

    @app.get("/api/bookings/<int:booking_id>/paymongo-sync")
    def sync_booking_paymongo_status(booking_id: int):
        conn = get_db()
        booking = _fetch_booking_by_id(conn, booking_id)
        if not booking:
            return jsonify({"error": "Booking not found."}), 404

        if booking["payment_status"] == "verified":
            return jsonify({"booking": _serialize_booking(booking), "status": "already_verified"})

        link_id = booking["payment_link_id"]
        if not link_id:
            return jsonify({"error": "No PayMongo payment link associated with this booking."}), 400

        secret_settings = get_settings(conn, include_secrets=True)
        pm_key = secret_settings.get("paymongo_secret_key")
        if not pm_key:
            return jsonify({"error": "Online payment is not configured on this platform."}), 400

        ok, link_res = get_payment_link(pm_key, link_id)
        if not ok or not isinstance(link_res, dict):
            return jsonify({"error": f"Failed to fetch payment link status: {link_res}"}), 502

        link_status = link_res.get("status", "")
        if link_status == "paid":
            payments = link_res.get("payments", [])
            payment_id = payments[0].get("id", "") if payments else ""
            now = datetime.now().isoformat(timespec="seconds")
            with conn:
                conn.execute(
                    """
                    UPDATE bookings
                    SET status = CASE WHEN status = 'pending' THEN 'confirmed' ELSE status END,
                        payment_status = 'verified',
                        payment_reference = COALESCE(NULLIF(payment_reference, ''), ?),
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (payment_id, now, booking_id),
                )
            updated_booking = _fetch_booking_by_id(conn, booking_id)
            booking_data = _serialize_booking(updated_booking)
            shop_row = conn.execute(
                "SELECT * FROM shops WHERE id = ?", (updated_booking["shop_id"],)
            ).fetchone()
            shop_data = _serialize_shop(shop_row, include_private=True) if shop_row else {}
            _dispatch_alert(
                notify_payment_verified,
                secret_settings,
                shop_data,
                booking_data,
                {
                    "link_id": link_id,
                    "payment_id": payment_id,
                    "amount_paid": link_res.get("amount", 0) / 100.0,
                    "fee": 0,
                    "net_amount": link_res.get("amount", 0) / 100.0,
                    "status": "paid",
                },
            )
            return jsonify({"booking": booking_data, "status": "paid", "updated": True})

        return jsonify({"booking": _serialize_booking(booking), "status": link_status, "updated": False})

    # ------------------------------------------------------------------
    # Shared Bike Extraction Helper (Admin & Partner)
    # ------------------------------------------------------------------
    def _extract_bike_payload(existing=None):
        if request.content_type and "multipart/form-data" in request.content_type:
            data = request.form
            image_file = request.files.get("image")
        else:
            data = request.get_json(silent=True) or {}
            image_file = None

        name = (data.get("name") or (existing["name"] if existing else "")).strip()
        category = (data.get("category") or (existing["category"] if existing else "Scooter")).strip()
        transmission = (
            data.get("transmission") or (existing["transmission"] if existing else "Automatic")
        ).strip()
        fuel_type = (data.get("fuel_type") or (existing["fuel_type"] if existing else "Gasoline")).strip()
        plate_number = (
            data.get("plate_number") if "plate_number" in data else (existing["plate_number"] if existing else "")
        )
        inclusions = (
            data.get("inclusions")
            if "inclusions" in data
            else (existing["inclusions"] if existing else "2 Helmets, Phone Mount, Rain Poncho")
        )
        description = (
            data.get("description") if "description" in data else (existing["description"] if existing else "")
        )
        status = (data.get("status") or (existing["status"] if existing else "available")).strip().lower()
        image_url = (
            data.get("image_url") if "image_url" in data else (existing["image_url"] if existing else "")
        ).strip()

        if not name:
            raise ValueError("Motorbike name is required.")
        if category not in VALID_CATEGORIES:
            raise ValueError(f"Category must be one of: {', '.join(VALID_CATEGORIES)}.")
        if transmission not in VALID_TRANSMISSIONS:
            raise ValueError("Transmission must be Automatic or Manual.")
        if status not in VALID_BIKE_STATUSES:
            raise ValueError("Invalid bike status.")

        try:
            engine_cc = int(data.get("engine_cc", existing["engine_cc"] if existing else 125))
            daily_rate = float(data.get("daily_rate", existing["daily_rate"] if existing else 0))
            weekly_rate = float(data.get("weekly_rate", existing["weekly_rate"] if existing else 0))
            deposit = float(data.get("deposit", existing["deposit"] if existing else 0))
            units_count = int(data.get("units_count", existing["units_count"] if existing else 1))
        except (TypeError, ValueError):
            raise ValueError("Engine CC, rates, deposit, and units must be valid numbers.")

        if engine_cc <= 0 or daily_rate <= 0 or weekly_rate < 0 or deposit < 0 or units_count < 1:
            raise ValueError("Engine CC, daily rate, and units count must be positive.")

        featured_raw = data.get("featured", existing["featured"] if existing else False)
        if isinstance(featured_raw, str):
            featured = featured_raw.lower() in ("1", "true", "yes", "on")
        else:
            featured = bool(featured_raw)

        validated_image = _validate_image_upload(image_file)
        if validated_image is not None:
            image_url = _save_validated_image(get_db(), validated_image)
        elif not image_url:
            image_url = "/static/images/bike-click125.jpg"
        elif image_url.startswith("/"):
            pass
        else:
            parsed = urlparse(image_url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError("Image URL must be a local /static path or http/https URL.")

        return {
            "name": name,
            "category": category,
            "engine_cc": engine_cc,
            "transmission": transmission,
            "fuel_type": fuel_type or "Gasoline",
            "daily_rate": daily_rate,
            "weekly_rate": weekly_rate,
            "deposit": deposit,
            "units_count": units_count,
            "plate_number": (plate_number or "").strip(),
            "inclusions": (inclusions or "").strip(),
            "description": (description or "").strip(),
            "image_url": image_url,
            "status": status,
            "featured": 1 if featured else 0,
            "shop_id": data.get("shop_id"),
        }

    # ------------------------------------------------------------------
    # Partner Portal Auth & APIs (/api/partner/...)
    # ------------------------------------------------------------------
    def _platform_alert_flags(conn) -> dict:
        secret_cfg = get_settings(conn, include_secrets=True)
        telegram_ready = bool((secret_cfg.get("telegram_bot_token") or "").strip())
        email_ready = bool(
            (secret_cfg.get("smtp_host") or "").strip()
            and ((secret_cfg.get("smtp_from_email") or "").strip() or (secret_cfg.get("smtp_username") or "").strip())
        )
        return {
            "platform_telegram_enabled": telegram_ready,
            "platform_email_enabled": email_ready,
        }

    @app.get("/api/partner/me")
    def partner_me():
        shop_id = session.get("partner_shop_id")
        if not shop_id:
            return jsonify({"authenticated": False, "shop": None})
        conn = get_db()
        row = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if not row:
            session.pop("partner_shop_id", None)
            return jsonify({"authenticated": False, "shop": None})
        return jsonify(
            {
                "authenticated": True,
                "shop": _serialize_shop(row, include_private=True),
                **_platform_alert_flags(conn),
            }
        )

    @app.post("/api/partner/register")
    def partner_register():
        payload = request.get_json(silent=True) or {}
        shop_name = (payload.get("shop_name") or "").strip()
        owner_name = (payload.get("owner_name") or "").strip()
        email = (payload.get("email") or "").strip().lower()
        phone = (payload.get("phone") or "").strip()
        whatsapp_number = _normalize_phone(payload.get("whatsapp_number") or phone)
        telegram_chat_id = (payload.get("telegram_chat_id") or "").strip()
        municipality = (payload.get("municipality") or "Mambajao").strip()
        address = (payload.get("address") or "").strip()
        description = (payload.get("description") or "").strip()
        password = payload.get("password") or ""

        if not shop_name:
            return jsonify({"error": "Rental shop name is required."}), 400
        if not owner_name:
            return jsonify({"error": "Owner full name is required."}), 400
        if "@" not in email or "." not in email:
            return jsonify({"error": "Please enter a valid email address."}), 400
        if len(_normalize_phone(phone)) < 7:
            return jsonify({"error": "Please enter a valid mobile or WhatsApp number."}), 400
        if municipality not in CAMIGUIN_MUNICIPALITIES:
            return jsonify({"error": "Please select a Camiguin municipality."}), 400
        if len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters."}), 400

        try:
            delivery_fee = float(payload.get("delivery_fee", 250) or 0)
            if delivery_fee < 0:
                return jsonify({"error": "Delivery fee cannot be negative."}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "Delivery fee must be a valid number."}), 400

        conn = get_db()
        existing = conn.execute(
            "SELECT 1 FROM shops WHERE LOWER(email) = ?", (email,)
        ).fetchone()
        if existing:
            return jsonify({"error": "An account with that email already exists. Please sign in."}), 409

        slug = slugify_shop_name(shop_name, conn)
        now = datetime.now().isoformat(timespec="seconds")
        with conn:
            shop_id = conn.insert_returning_id(
                """
                INSERT INTO shops (
                    shop_name, slug, owner_name, email, phone, whatsapp_number,
                    telegram_chat_id, municipality, address, description, delivery_fee, password_hash,
                    status, is_main, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?)
                """,
                (
                    shop_name,
                    slug,
                    owner_name,
                    email,
                    phone,
                    whatsapp_number,
                    telegram_chat_id,
                    municipality,
                    address,
                    description,
                    delivery_fee,
                    generate_password_hash(password),
                    now,
                ),
            )

        session["partner_shop_id"] = shop_id
        created = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        secret_settings = get_settings(conn, include_secrets=True)
        _dispatch_alert(notify_new_partner_registration, secret_settings, dict(created))
        return jsonify(
            {
                "authenticated": True,
                "shop": _serialize_shop(created, include_private=True),
                **_platform_alert_flags(conn),
            }
        ), 201

    @app.post("/api/partner/login")
    def partner_login():
        payload = request.get_json(silent=True) or {}
        email = (payload.get("email") or "").strip().lower()
        password = payload.get("password") or ""
        conn = get_db()
        row = conn.execute("SELECT * FROM shops WHERE LOWER(email) = ?", (email,)).fetchone()
        if not row or not verify_shop_password(row, password):
            return jsonify({"error": "Incorrect email or password."}), 401
        session["partner_shop_id"] = row["id"]
        return jsonify({"authenticated": True, "shop": _serialize_shop(row, include_private=True)})

    @app.post("/api/partner/logout")
    def partner_logout():
        session.pop("partner_shop_id", None)
        return jsonify({"authenticated": False})

    @app.get("/api/partner/dashboard")
    @partner_required
    def partner_dashboard():
        conn = get_db()
        shop_id = g.partner_shop["id"]
        today_str = date.today().isoformat()
        month_prefix = date.today().strftime("%Y-%m")

        fleet_stats = conn.execute(
            """
            SELECT
                COUNT(*) AS total_models,
                COALESCE(SUM(CASE WHEN status != 'hidden' THEN units_count ELSE 0 END), 0) AS total_units,
                COALESCE(SUM(CASE WHEN status = 'available' THEN 1 ELSE 0 END), 0) AS available_models
            FROM bikes
            WHERE shop_id = ? AND status != 'hidden'
            """,
            (shop_id,),
        ).fetchone()

        status_counts = {st: 0 for st in VALID_BOOKING_STATUSES}
        for r in conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM bookings WHERE shop_id = ? GROUP BY status",
            (shop_id,),
        ).fetchall():
            if r["status"] in status_counts:
                status_counts[r["status"]] = int(r["cnt"])

        revenue_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status IN ('confirmed', 'active', 'completed') THEN total_amount ELSE 0 END), 0) AS gross_revenue,
                COALESCE(SUM(CASE WHEN status IN ('confirmed', 'active', 'completed') THEN platform_fee ELSE 0 END), 0) AS platform_fee_total,
                COALESCE(SUM(CASE WHEN status IN ('confirmed', 'active', 'completed') THEN shop_payout ELSE 0 END), 0) AS net_payout,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN shop_payout ELSE 0 END), 0) AS completed_payout,
                COALESCE(SUM(CASE WHEN status IN ('confirmed', 'active', 'completed') AND substr(pickup_date, 1, 7) = ? THEN shop_payout ELSE 0 END), 0) AS month_payout
            FROM bookings
            WHERE shop_id = ?
            """,
            (month_prefix, shop_id),
        ).fetchone()

        upcoming_rows = conn.execute(
            """
            SELECT b.*, k.name AS bike_name, k.image_url AS bike_image,
                   k.category AS bike_category, k.transmission AS bike_transmission,
                   k.plate_number AS plate_number,
                   s.shop_name AS shop_name, s.municipality AS shop_municipality,
                   s.address AS shop_address, s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp
            FROM bookings b
            JOIN bikes k ON k.id = b.bike_id
            JOIN shops s ON s.id = b.shop_id
            WHERE b.shop_id = ?
              AND b.status IN ('pending', 'confirmed', 'active')
              AND b.return_date >= ?
            ORDER BY b.pickup_date ASC, b.created_at DESC
            LIMIT 8
            """,
            (shop_id, today_str),
        ).fetchall()

        shop_rating = get_shop_rating_stats(conn, shop_id)
        settings = get_settings(conn)
        return jsonify(
            {
                "shop": _serialize_shop(g.partner_shop, include_private=True, rating_stats=shop_rating),
                **_platform_alert_flags(conn),
                "commission_rate": float(settings.get("commission_rate", "10") or 0),
                "kpis": {
                    "total_models": int(fleet_stats["total_models"]),
                    "total_units": int(fleet_stats["total_units"]),
                    "available_models": int(fleet_stats["available_models"]),
                    "pending_count": status_counts["pending"],
                    "confirmed_count": status_counts["confirmed"],
                    "active_count": status_counts["active"],
                    "completed_count": status_counts["completed"],
                    "cancelled_count": status_counts["cancelled"],
                    "gross_revenue": float(revenue_row["gross_revenue"]),
                    "platform_fee_total": float(revenue_row["platform_fee_total"]),
                    "net_payout": float(revenue_row["net_payout"]),
                    "completed_payout": float(revenue_row["completed_payout"]),
                    "month_payout": float(revenue_row["month_payout"]),
                    "rating_avg": shop_rating["avg_rating"],
                    "review_count": shop_rating["review_count"],
                },
                "upcoming": [_serialize_booking(r) for r in upcoming_rows],
                "reviews": get_shop_reviews(conn, shop_id, limit=8),
            }
        )

    @app.get("/api/partner/bookings")
    @partner_required
    def partner_list_bookings():
        conn = get_db()
        shop_id = g.partner_shop["id"]
        status_filter = (request.args.get("status") or "").strip().lower()
        q = (request.args.get("q") or "").strip().lower()

        sql = """
            SELECT b.*, k.name AS bike_name, k.image_url AS bike_image,
                   k.category AS bike_category, k.transmission AS bike_transmission,
                   k.plate_number AS plate_number,
                   s.shop_name AS shop_name, s.municipality AS shop_municipality,
                   s.address AS shop_address, s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp
            FROM bookings b
            JOIN bikes k ON k.id = b.bike_id
            JOIN shops s ON s.id = b.shop_id
            WHERE b.shop_id = ?
        """
        params: list = [shop_id]
        if status_filter and status_filter != "all":
            sql += " AND b.status = ?"
            params.append(status_filter)
        if q:
            sql += """
                AND (
                    LOWER(b.booking_code) LIKE ?
                    OR LOWER(b.customer_name) LIKE ?
                    OR LOWER(b.customer_phone) LIKE ?
                    OR LOWER(k.name) LIKE ?
                )
            """
            like = f"%{q}%"
            params.extend([like, like, like, like])

        sql += " ORDER BY CASE b.status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 WHEN 'confirmed' THEN 2 WHEN 'completed' THEN 3 ELSE 4 END, b.pickup_date ASC, b.id DESC"
        rows = conn.execute(sql, params).fetchall()
        return jsonify({"bookings": [_serialize_booking(r) for r in rows]})

    @app.patch("/api/partner/bookings/<int:booking_id>")
    @partner_required
    def partner_update_booking(booking_id: int):
        if g.partner_shop["status"] == "suspended":
            return jsonify({"error": "Account suspended. Contact Main Admin."}), 403

        payload = request.get_json(silent=True) or {}
        conn = get_db()
        shop_id = g.partner_shop["id"]
        existing = conn.execute(
            "SELECT * FROM bookings WHERE id = ? AND shop_id = ?",
            (booking_id, shop_id),
        ).fetchone()
        if not existing:
            return jsonify({"error": "Booking not found for your shop."}), 404

        new_status = (payload.get("status") or existing["status"]).strip().lower()
        if new_status not in VALID_BOOKING_STATUSES:
            return jsonify({"error": "Invalid booking status."}), 400

        admin_notes = (
            payload["admin_notes"].strip()
            if "admin_notes" in payload and payload["admin_notes"] is not None
            else existing["admin_notes"]
        )

        if new_status in BLOCKING_STATUSES and existing["status"] not in BLOCKING_STATUSES:
            bike = conn.execute("SELECT * FROM bikes WHERE id = ?", (existing["bike_id"],)).fetchone()
            booked = count_overlapping_bookings(
                conn,
                existing["bike_id"],
                existing["pickup_date"],
                existing["return_date"],
                exclude_booking_id=booking_id,
            )
            if bike and booked >= int(bike["units_count"] or 1):
                return jsonify({"error": "Cannot reactivate: all units already booked for those dates."}), 409

        new_balance_paid, balance_error = _resolve_balance_paid(payload, existing)
        if balance_error:
            return jsonify({"error": balance_error}), 400

        now = datetime.now().isoformat(timespec="seconds")
        with conn:
            conn.execute(
                "UPDATE bookings SET status = ?, admin_notes = ?, balance_paid = ?, updated_at = ? "
                "WHERE id = ? AND shop_id = ?",
                (new_status, admin_notes, 1 if new_balance_paid else 0, now, booking_id, shop_id),
            )
        updated = _fetch_booking_by_id(conn, booking_id)
        return jsonify({"booking": _serialize_booking(updated)})

    @app.get("/api/partner/bikes")
    @partner_required
    def partner_list_bikes():
        conn = get_db()
        shop_id = g.partner_shop["id"]
        today_str = date.today().isoformat()
        rows = conn.execute(
            """
            SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality,
                   s.status AS shop_status
            FROM bikes b
            JOIN shops s ON s.id = b.shop_id
            WHERE b.shop_id = ?
            ORDER BY b.id DESC
            """,
            (shop_id,),
        ).fetchall()
        schedules = build_bike_schedules(
            conn,
            rows,
            ref_pickup_date=today_str,
            ref_return_date=today_str,
            include_calendar=False,
            include_admin_details=True,
        )
        items = []
        for row in rows:
            sched = schedules.get(int(row["id"]))
            booked = int((sched or {}).get("ref_booked_units", 0))
            items.append(_serialize_bike(row, booked_units=booked, schedule=sched))
        return jsonify({"bikes": items})

    @app.post("/api/partner/bikes")
    @partner_required
    def partner_create_bike():
        if g.partner_shop["status"] == "suspended":
            return jsonify({"error": "Suspended accounts cannot add motorbikes."}), 403
        conn = get_db()
        try:
            fields = _extract_bike_payload()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        shop_id = g.partner_shop["id"]
        slug = slugify_name(fields["name"], conn)
        now = datetime.now().isoformat(timespec="seconds")
        with conn:
            bike_id = conn.insert_returning_id(
                """
                INSERT INTO bikes (
                    shop_id, name, slug, category, engine_cc, transmission, fuel_type,
                    daily_rate, weekly_rate, deposit, units_count, plate_number,
                    inclusions, description, image_url, status, featured, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    shop_id,
                    fields["name"],
                    slug,
                    fields["category"],
                    fields["engine_cc"],
                    fields["transmission"],
                    fields["fuel_type"],
                    fields["daily_rate"],
                    fields["weekly_rate"],
                    fields["deposit"],
                    fields["units_count"],
                    fields["plate_number"],
                    fields["inclusions"],
                    fields["description"],
                    fields["image_url"],
                    fields["status"],
                    now,
                ),
            )

        row = conn.execute(
            "SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality, s.status AS shop_status "
            "FROM bikes b JOIN shops s ON s.id = b.shop_id WHERE b.id = ?",
            (bike_id,),
        ).fetchone()
        return jsonify({"bike": _serialize_bike(row)}), 201

    @app.put("/api/partner/bikes/<int:bike_id>")
    @partner_required
    def partner_update_bike(bike_id: int):
        if g.partner_shop["status"] == "suspended":
            return jsonify({"error": "Suspended accounts cannot edit motorbikes."}), 403
        conn = get_db()
        shop_id = g.partner_shop["id"]
        existing = conn.execute(
            "SELECT * FROM bikes WHERE id = ? AND shop_id = ?", (bike_id, shop_id)
        ).fetchone()
        if not existing:
            return jsonify({"error": "Motorbike not found in your shop."}), 404

        try:
            fields = _extract_bike_payload(existing=existing)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        slug = slugify_name(fields["name"], conn, exclude_id=bike_id)
        with conn:
            conn.execute(
                """
                UPDATE bikes SET
                    name = ?, slug = ?, category = ?, engine_cc = ?, transmission = ?,
                    fuel_type = ?, daily_rate = ?, weekly_rate = ?, deposit = ?,
                    units_count = ?, plate_number = ?, inclusions = ?, description = ?,
                    image_url = ?, status = ?
                WHERE id = ? AND shop_id = ?
                """,
                (
                    fields["name"],
                    slug,
                    fields["category"],
                    fields["engine_cc"],
                    fields["transmission"],
                    fields["fuel_type"],
                    fields["daily_rate"],
                    fields["weekly_rate"],
                    fields["deposit"],
                    fields["units_count"],
                    fields["plate_number"],
                    fields["inclusions"],
                    fields["description"],
                    fields["image_url"],
                    fields["status"],
                    bike_id,
                    shop_id,
                ),
            )
        if fields["image_url"] != existing["image_url"]:
            delete_unused_uploaded_media(conn, existing["image_url"])
        row = conn.execute(
            "SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality, s.status AS shop_status "
            "FROM bikes b JOIN shops s ON s.id = b.shop_id WHERE b.id = ?",
            (bike_id,),
        ).fetchone()
        return jsonify({"bike": _serialize_bike(row)})

    @app.delete("/api/partner/bikes/<int:bike_id>")
    @partner_required
    def partner_delete_bike(bike_id: int):
        conn = get_db()
        shop_id = g.partner_shop["id"]
        existing = conn.execute(
            "SELECT * FROM bikes WHERE id = ? AND shop_id = ?", (bike_id, shop_id)
        ).fetchone()
        if not existing:
            return jsonify({"error": "Motorbike not found in your shop."}), 404

        booking_count = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE bike_id = ?", (bike_id,)
        ).fetchone()[0]
        if booking_count > 0:
            return (
                jsonify(
                    {
                        "error": (
                            f"Cannot delete {existing['name']} because it has {booking_count} booking record(s). "
                            "Set status to 'Hidden' or 'Maintenance' instead."
                        )
                    }
                ),
                409,
            )
        with conn:
            conn.execute("DELETE FROM bike_blocks WHERE bike_id = ?", (bike_id,))
            conn.execute("DELETE FROM bikes WHERE id = ? AND shop_id = ?", (bike_id, shop_id))
        delete_unused_uploaded_media(conn, existing["image_url"])
        return jsonify({"deleted": True, "id": bike_id})

    @app.patch("/api/partner/bikes/<int:bike_id>/status")
    @partner_required
    def partner_patch_bike_status(bike_id: int):
        if g.partner_shop["status"] == "suspended":
            return jsonify({"error": "Suspended accounts cannot update motorbikes."}), 403
        conn = get_db()
        existing = conn.execute(
            "SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality, s.status AS shop_status "
            "FROM bikes b JOIN shops s ON s.id = b.shop_id WHERE b.id = ? AND b.shop_id = ?",
            (bike_id, g.partner_shop["id"]),
        ).fetchone()
        if not existing:
            return jsonify({"error": "Motorbike not found in your shop."}), 404
        res, err, code = _apply_bike_availability_patch(conn, existing, request.get_json(silent=True) or {})
        if err:
            return jsonify({"error": err}), code
        return jsonify(res), code

    @app.get("/api/partner/bikes/<int:bike_id>/blocks")
    @partner_required
    def partner_get_bike_blocks(bike_id: int):
        conn = get_db()
        existing = conn.execute(
            "SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality, s.status AS shop_status "
            "FROM bikes b JOIN shops s ON s.id = b.shop_id WHERE b.id = ? AND b.shop_id = ?",
            (bike_id, g.partner_shop["id"]),
        ).fetchone()
        if not existing:
            return jsonify({"error": "Motorbike not found in your shop."}), 404
        return jsonify({"bike": _serialize_bike_with_schedule(conn, existing, include_calendar=True)})

    @app.post("/api/partner/bikes/<int:bike_id>/blocks")
    @partner_required
    def partner_add_bike_block(bike_id: int):
        if g.partner_shop["status"] == "suspended":
            return jsonify({"error": "Suspended accounts cannot block motorbike dates."}), 403
        conn = get_db()
        existing = conn.execute(
            "SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality, s.status AS shop_status "
            "FROM bikes b JOIN shops s ON s.id = b.shop_id WHERE b.id = ? AND b.shop_id = ?",
            (bike_id, g.partner_shop["id"]),
        ).fetchone()
        if not existing:
            return jsonify({"error": "Motorbike not found in your shop."}), 404
        res, err, code = _create_bike_block_entry(conn, existing, request.get_json(silent=True) or {})
        if err:
            return jsonify({"error": err}), code
        return jsonify(res), code

    @app.delete("/api/partner/bikes/<int:bike_id>/blocks/<int:block_id>")
    @partner_required
    def partner_remove_bike_block(bike_id: int, block_id: int):
        if g.partner_shop["status"] == "suspended":
            return jsonify({"error": "Suspended accounts cannot manage motorbike blocks."}), 403
        conn = get_db()
        existing = conn.execute(
            "SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality, s.status AS shop_status "
            "FROM bikes b JOIN shops s ON s.id = b.shop_id WHERE b.id = ? AND b.shop_id = ?",
            (bike_id, g.partner_shop["id"]),
        ).fetchone()
        if not existing:
            return jsonify({"error": "Motorbike not found in your shop."}), 404
        res, err, code = _delete_bike_block_entry(conn, existing, block_id)
        if err:
            return jsonify({"error": err}), code
        return jsonify(res), code

    @app.route("/api/partner/profile", methods=["PUT", "POST"])
    @partner_required
    def partner_update_profile():
        json_payload = request.get_json(silent=True)
        payload = json_payload if isinstance(json_payload, dict) else request.form.to_dict()
        conn = get_db()
        shop = g.partner_shop

        shop_name = (payload.get("shop_name") or shop["shop_name"]).strip()
        owner_name = (payload.get("owner_name") or shop["owner_name"]).strip()
        phone = (payload.get("phone") or shop["phone"]).strip()
        whatsapp_number = _normalize_phone(
            payload.get("whatsapp_number") if "whatsapp_number" in payload else shop["whatsapp_number"]
        )
        telegram_chat_id = (
            (payload.get("telegram_chat_id") if "telegram_chat_id" in payload else shop["telegram_chat_id"]) or ""
        ).strip()
        municipality = (payload.get("municipality") or shop["municipality"]).strip()
        address = (payload.get("address") if "address" in payload else shop["address"]).strip()
        description = (
            payload.get("description") if "description" in payload else shop["description"]
        ).strip()
        existing_contract = (shop["contract_terms"] if "contract_terms" in shop.keys() else "") or ""
        contract_terms = (
            (payload.get("contract_terms") if "contract_terms" in payload else existing_contract) or ""
        ).strip()

        if not shop_name or not owner_name:
            return jsonify({"error": "Shop name and owner name are required."}), 400
        if len(_normalize_phone(phone)) < 7:
            return jsonify({"error": "Please enter a valid contact number."}), 400
        if municipality not in CAMIGUIN_MUNICIPALITIES:
            return jsonify({"error": "Please select a valid Camiguin municipality."}), 400

        try:
            delivery_fee = float(
                payload.get("delivery_fee", shop["delivery_fee"]) or 0
            )
            if delivery_fee < 0:
                return jsonify({"error": "Delivery fee cannot be negative."}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "Delivery fee must be a valid number."}), 400

        password_hash = shop["password_hash"]
        new_password = (payload.get("new_password") or "").strip()
        if new_password:
            current_password = payload.get("current_password") or ""
            if not verify_shop_password(shop, current_password):
                return jsonify({"error": "Current password is incorrect."}), 400
            if len(new_password) < 6:
                return jsonify({"error": "New password must be at least 6 characters."}), 400
            password_hash = generate_password_hash(new_password)

        existing_logo = (shop["logo_url"] if "logo_url" in shop.keys() else "") or ""
        existing_cover = (shop["cover_url"] if "cover_url" in shop.keys() else "") or ""
        logo_url = existing_logo
        cover_url = existing_cover

        if _as_bool(payload.get("clear_logo")):
            logo_url = ""
        elif "logo_url" in payload and payload.get("logo_url") is not None:
            logo_url = str(payload.get("logo_url") or "").strip()

        if _as_bool(payload.get("clear_cover")):
            cover_url = ""
        elif "cover_url" in payload and payload.get("cover_url") is not None:
            cover_url = str(payload.get("cover_url") or "").strip()

        try:
            validated_logo = _validate_image_upload(request.files.get("logo_image"), prefix="shop_logo")
            validated_cover = _validate_image_upload(request.files.get("cover_image"), prefix="shop_cover")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        slug = slugify_shop_name(shop_name, conn, exclude_id=shop["id"])
        with conn:
            if validated_logo:
                logo_url = _save_validated_image(conn, validated_logo, use_tx=False)
            if validated_cover:
                cover_url = _save_validated_image(conn, validated_cover, use_tx=False)
            conn.execute(
                """
                UPDATE shops SET
                    shop_name = ?, slug = ?, owner_name = ?, phone = ?, whatsapp_number = ?,
                    telegram_chat_id = ?, municipality = ?, address = ?, description = ?, delivery_fee = ?,
                    logo_url = ?, cover_url = ?, contract_terms = ?, password_hash = ?
                WHERE id = ?
                """,
                (
                    shop_name,
                    slug,
                    owner_name,
                    phone,
                    whatsapp_number,
                    telegram_chat_id,
                    municipality,
                    address,
                    description,
                    delivery_fee,
                    logo_url,
                    cover_url,
                    contract_terms,
                    password_hash,
                    shop["id"],
                ),
            )
        if existing_logo and existing_logo != logo_url:
            delete_unused_uploaded_media(conn, existing_logo)
        if existing_cover and existing_cover != cover_url:
            delete_unused_uploaded_media(conn, existing_cover)
        updated = conn.execute("SELECT * FROM shops WHERE id = ?", (shop["id"],)).fetchone()
        return jsonify({"shop": _serialize_shop(updated, include_private=True), **_platform_alert_flags(conn)})

    @app.post("/api/partner/profile/media")
    @partner_required
    def partner_upload_profile_media():
        conn = get_db()
        shop = g.partner_shop
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            payload = request.form.to_dict()

        existing_logo = (shop["logo_url"] if "logo_url" in shop.keys() else "") or ""
        existing_cover = (shop["cover_url"] if "cover_url" in shop.keys() else "") or ""
        logo_url = existing_logo
        cover_url = existing_cover

        if _as_bool(payload.get("clear_logo")):
            logo_url = ""
        if _as_bool(payload.get("clear_cover")):
            cover_url = ""

        try:
            validated_logo = _validate_image_upload(request.files.get("logo_image"), prefix="shop_logo")
            validated_cover = _validate_image_upload(request.files.get("cover_image"), prefix="shop_cover")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        if (
            not validated_logo
            and not validated_cover
            and not _as_bool(payload.get("clear_logo"))
            and not _as_bool(payload.get("clear_cover"))
        ):
            return jsonify({"error": "Please select a profile picture or cover photo to upload."}), 400

        with conn:
            if validated_logo:
                logo_url = _save_validated_image(conn, validated_logo, use_tx=False)
            if validated_cover:
                cover_url = _save_validated_image(conn, validated_cover, use_tx=False)
            conn.execute(
                "UPDATE shops SET logo_url = ?, cover_url = ? WHERE id = ?",
                (logo_url, cover_url, shop["id"]),
            )
        if existing_logo and existing_logo != logo_url:
            delete_unused_uploaded_media(conn, existing_logo)
        if existing_cover and existing_cover != cover_url:
            delete_unused_uploaded_media(conn, existing_cover)
        updated = conn.execute("SELECT * FROM shops WHERE id = ?", (shop["id"],)).fetchone()
        return jsonify({"shop": _serialize_shop(updated, include_private=True)})

    @app.post("/api/partner/profile/test-alert")
    @partner_required
    def partner_test_alert():
        payload = request.get_json(silent=True) or {}
        conn = get_db()
        shop = g.partner_shop
        chat_id = (
            (payload.get("telegram_chat_id") if "telegram_chat_id" in payload else shop["telegram_chat_id"]) or ""
        ).strip()
        email_to = ((payload.get("email") if "email" in payload else shop["email"]) or "").strip()

        secret_settings = get_settings(conn, include_secrets=True)
        has_smtp = bool((secret_settings.get("smtp_host") or "").strip())
        results = send_test_alert(
            secret_settings,
            telegram_chat_id=chat_id if (chat_id or not has_smtp) else None,
            email_to=email_to if has_smtp else None,
            label=shop["shop_name"],
        )
        ok_any = any(item.get("ok") for item in results.values())
        return jsonify({"ok": ok_any, "results": results}), (200 if ok_any else 400)

    # ------------------------------------------------------------------
    # Main Super Admin Auth & Centralized Dashboard APIs (/api/admin/...)
    # ------------------------------------------------------------------
    @app.get("/api/admin/me")
    def admin_me():
        return jsonify({"authenticated": bool(session.get("is_admin"))})

    @app.post("/api/admin/login")
    def admin_login():
        payload = request.get_json(silent=True) or {}
        password = payload.get("password") or ""
        conn = get_db()
        if not verify_admin_password(conn, password):
            return jsonify({"error": "Incorrect admin password."}), 401
        session["is_admin"] = True
        return jsonify({"authenticated": True})

    @app.post("/api/admin/logout")
    def admin_logout():
        session.pop("is_admin", None)
        return jsonify({"authenticated": False})

    @app.get("/api/admin/dashboard")
    @admin_required
    def admin_dashboard():
        conn = get_db()
        today_str = date.today().isoformat()
        month_prefix = date.today().strftime("%Y-%m")

        shop_counts = {st: 0 for st in VALID_SHOP_STATUSES}
        for r in conn.execute("SELECT status, COUNT(*) AS cnt FROM shops GROUP BY status").fetchall():
            if r["status"] in shop_counts:
                shop_counts[r["status"]] = int(r["cnt"])

        fleet_stats = conn.execute(
            """
            SELECT
                COUNT(*) AS total_models,
                COALESCE(SUM(CASE WHEN b.status != 'hidden' THEN b.units_count ELSE 0 END), 0) AS total_units,
                COALESCE(SUM(CASE WHEN b.status = 'available' AND s.status = 'approved' THEN 1 ELSE 0 END), 0) AS available_models
            FROM bikes b
            JOIN shops s ON s.id = b.shop_id
            WHERE b.status != 'hidden'
            """
        ).fetchone()

        status_counts = {st: 0 for st in VALID_BOOKING_STATUSES}
        for r in conn.execute(
            "SELECT status, COUNT(*) AS cnt FROM bookings GROUP BY status"
        ).fetchall():
            if r["status"] in status_counts:
                status_counts[r["status"]] = int(r["cnt"])

        revenue_row = conn.execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN status IN ('confirmed', 'active', 'completed') THEN total_amount ELSE 0 END), 0) AS projected_revenue,
                COALESCE(SUM(CASE WHEN status IN ('confirmed', 'active', 'completed') THEN platform_fee ELSE 0 END), 0) AS platform_fee_total,
                COALESCE(SUM(CASE WHEN status IN ('confirmed', 'active', 'completed') THEN shop_payout ELSE 0 END), 0) AS partner_payout_total,
                COALESCE(SUM(CASE WHEN payment_status = 'verified' AND status != 'cancelled' THEN reservation_fee ELSE 0 END), 0) AS collected_reservation_total,
                COALESCE(SUM(CASE WHEN payment_status = 'submitted' AND status != 'cancelled' THEN reservation_fee ELSE 0 END), 0) AS pending_verification_total,
                COUNT(CASE WHEN payment_status = 'submitted' AND status != 'cancelled' THEN id END) AS pending_payment_verifications,
                COALESCE(SUM(CASE WHEN status = 'completed' THEN total_amount ELSE 0 END), 0) AS completed_revenue,
                COALESCE(SUM(CASE WHEN status IN ('confirmed', 'active', 'completed') AND substr(pickup_date, 1, 7) = ? THEN total_amount ELSE 0 END), 0) AS month_revenue,
                COALESCE(SUM(CASE WHEN status IN ('confirmed', 'active', 'completed') AND pickup_date = ? THEN total_amount ELSE 0 END), 0) AS today_revenue
            FROM bookings
            """,
            (month_prefix, today_str),
        ).fetchone()

        revenue_by_shop = conn.execute(
            """
            SELECT s.id, s.shop_name, s.municipality, s.status, s.is_main,
                   COUNT(CASE WHEN b.status IN ('confirmed', 'active', 'completed') THEN b.id END) AS booking_count,
                   COALESCE(SUM(CASE WHEN b.status IN ('confirmed', 'active', 'completed') THEN b.total_amount ELSE 0 END), 0) AS gross_revenue,
                   COALESCE(SUM(CASE WHEN b.status IN ('confirmed', 'active', 'completed') THEN b.platform_fee ELSE 0 END), 0) AS platform_fee_total,
                   COALESCE(SUM(CASE WHEN b.status IN ('confirmed', 'active', 'completed') THEN b.shop_payout ELSE 0 END), 0) AS shop_payout_total
            FROM shops s
            LEFT JOIN bookings b ON b.shop_id = s.id
            GROUP BY s.id, s.shop_name, s.municipality, s.status, s.is_main
            ORDER BY gross_revenue DESC, s.is_main DESC, s.shop_name ASC
            """
        ).fetchall()

        upcoming_rows = conn.execute(
            """
            SELECT b.*, k.name AS bike_name, k.image_url AS bike_image,
                   k.category AS bike_category, k.transmission AS bike_transmission,
                   k.plate_number AS plate_number,
                   s.shop_name AS shop_name, s.municipality AS shop_municipality,
                   s.address AS shop_address, s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp
            FROM bookings b
            JOIN bikes k ON k.id = b.bike_id
            JOIN shops s ON s.id = b.shop_id
            WHERE b.status IN ('pending', 'confirmed', 'active')
              AND b.return_date >= ?
            ORDER BY b.pickup_date ASC, b.created_at DESC
            LIMIT 8
            """,
            (today_str,),
        ).fetchall()

        settings = get_settings(conn)
        return jsonify(
            {
                "kpis": {
                    "pending_shops": shop_counts["pending"],
                    "approved_shops": shop_counts["approved"],
                    "suspended_shops": shop_counts["suspended"],
                    "total_models": int(fleet_stats["total_models"]),
                    "total_units": int(fleet_stats["total_units"]),
                    "available_models": int(fleet_stats["available_models"]),
                    "pending_count": status_counts["pending"],
                    "confirmed_count": status_counts["confirmed"],
                    "active_count": status_counts["active"],
                    "completed_count": status_counts["completed"],
                    "cancelled_count": status_counts["cancelled"],
                    "projected_revenue": float(revenue_row["projected_revenue"]),
                    "platform_fee_total": float(revenue_row["platform_fee_total"]),
                    "partner_payout_total": float(revenue_row["partner_payout_total"]),
                    "collected_reservation_total": float(revenue_row["collected_reservation_total"]),
                    "pending_verification_total": float(revenue_row["pending_verification_total"]),
                    "pending_payment_verifications": int(revenue_row["pending_payment_verifications"] or 0),
                    "completed_revenue": float(revenue_row["completed_revenue"]),
                    "month_revenue": float(revenue_row["month_revenue"]),
                    "today_revenue": float(revenue_row["today_revenue"]),
                    "commission_rate": float(settings.get("commission_rate", "10") or 0),
                    "reservation_mode": settings.get("reservation_mode", "off"),
                    "reservation_percent": float(settings.get("reservation_percent", "30") or 0),
                    "reservation_configured": is_reservation_payment_configured(settings),
                },
                "revenue_by_shop": [
                    {
                        "id": r["id"],
                        "shop_name": r["shop_name"],
                        "municipality": r["municipality"],
                        "status": r["status"],
                        "is_main": bool(r["is_main"]),
                        "booking_count": int(r["booking_count"]),
                        "gross_revenue": float(r["gross_revenue"]),
                        "platform_fee_total": float(r["platform_fee_total"]),
                        "shop_payout_total": float(r["shop_payout_total"]),
                    }
                    for r in revenue_by_shop
                ],
                "upcoming": [_serialize_booking(r) for r in upcoming_rows],
            }
        )

    @app.get("/api/admin/shops")
    @admin_required
    def admin_list_shops():
        conn = get_db()
        status_filter = (request.args.get("status") or "").strip().lower()
        sql = """
            SELECT s.*,
                   (SELECT COUNT(*) FROM bikes k WHERE k.shop_id = s.id AND k.status != 'hidden') AS bike_count,
                   (SELECT COUNT(*) FROM bookings b WHERE b.shop_id = s.id) AS booking_count,
                   (SELECT COALESCE(SUM(total_amount), 0) FROM bookings b WHERE b.shop_id = s.id AND b.status IN ('confirmed', 'active', 'completed')) AS gross_revenue,
                   (SELECT COALESCE(SUM(platform_fee), 0) FROM bookings b WHERE b.shop_id = s.id AND b.status IN ('confirmed', 'active', 'completed')) AS platform_fee_total,
                   (SELECT COALESCE(SUM(shop_payout), 0) FROM bookings b WHERE b.shop_id = s.id AND b.status IN ('confirmed', 'active', 'completed')) AS shop_payout_total
            FROM shops s
            WHERE 1=1
        """
        params: list = []
        if status_filter and status_filter != "all":
            sql += " AND s.status = ?"
            params.append(status_filter)
        sql += " ORDER BY CASE s.status WHEN 'pending' THEN 0 WHEN 'approved' THEN 1 ELSE 2 END, s.is_main DESC, s.id DESC"
        rows = conn.execute(sql, params).fetchall()
        return jsonify({"shops": [_serialize_shop(r, include_private=True) for r in rows]})

    @app.post("/api/admin/shops")
    @admin_required
    def admin_create_shop():
        payload = request.get_json(silent=True) or {}
        shop_name = (payload.get("shop_name") or "").strip()
        owner_name = (payload.get("owner_name") or "").strip()
        email = (payload.get("email") or "").strip().lower()
        phone = (payload.get("phone") or "").strip()
        whatsapp_number = _normalize_phone(payload.get("whatsapp_number") or phone)
        municipality = (payload.get("municipality") or "Mambajao").strip()
        address = (payload.get("address") or "").strip()
        description = (payload.get("description") or "").strip()
        status = (payload.get("status") or "approved").strip().lower()
        password = payload.get("password") or "partner1234"

        if not shop_name or not owner_name or "@" not in email:
            return jsonify({"error": "Shop name, owner name, and valid email are required."}), 400
        if len(_normalize_phone(phone)) < 7:
            return jsonify({"error": "Valid phone number is required."}), 400
        if municipality not in CAMIGUIN_MUNICIPALITIES:
            return jsonify({"error": "Invalid Camiguin municipality."}), 400
        if status not in VALID_SHOP_STATUSES:
            return jsonify({"error": "Invalid shop status."}), 400
        if len(password) < 6:
            return jsonify({"error": "Password must be at least 6 characters."}), 400

        try:
            delivery_fee = float(payload.get("delivery_fee", 250) or 0)
            if delivery_fee < 0:
                return jsonify({"error": "Delivery fee cannot be negative."}), 400
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid delivery fee."}), 400

        conn = get_db()
        if conn.execute("SELECT 1 FROM shops WHERE LOWER(email) = ?", (email,)).fetchone():
            return jsonify({"error": "Email already registered."}), 409

        slug = slugify_shop_name(shop_name, conn)
        now = datetime.now().isoformat(timespec="seconds")
        with conn:
            shop_id = conn.insert_returning_id(
                """
                INSERT INTO shops (
                    shop_name, slug, owner_name, email, phone, whatsapp_number,
                    municipality, address, description, delivery_fee, password_hash,
                    status, is_main, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    shop_name,
                    slug,
                    owner_name,
                    email,
                    phone,
                    whatsapp_number,
                    municipality,
                    address,
                    description,
                    delivery_fee,
                    generate_password_hash(password),
                    status,
                    now,
                ),
            )
        created = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        return jsonify({"shop": _serialize_shop(created, include_private=True)}), 201

    @app.patch("/api/admin/shops/<int:shop_id>")
    @admin_required
    def admin_update_shop(shop_id: int):
        payload = request.get_json(silent=True) or {}
        conn = get_db()
        existing = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Partner shop not found."}), 404

        new_password = (payload.get("password") or "").strip()
        if "password" in payload and len(new_password) < 6:
            return jsonify({"error": "New shop password must be at least 6 characters."}), 400

        new_status = (payload.get("status") or existing["status"]).strip().lower()
        if new_status not in VALID_SHOP_STATUSES:
            return jsonify({"error": "Invalid shop status."}), 400

        with conn:
            conn.execute(
                "UPDATE shops SET status = ?, is_main = 0 WHERE id = ?",
                (new_status, shop_id),
            )
            if new_password:
                conn.execute(
                    "UPDATE shops SET password_hash = ? WHERE id = ?",
                    (generate_password_hash(new_password), shop_id),
                )
        updated = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if new_status != existing["status"] and new_status in ("approved", "suspended"):
            secret_settings = get_settings(conn, include_secrets=True)
            _dispatch_alert(notify_partner_status_change, secret_settings, dict(updated))
        return jsonify({"shop": _serialize_shop(updated, include_private=True)})

    @app.delete("/api/admin/shops/<int:shop_id>")
    @admin_required
    def admin_delete_shop(shop_id: int):
        conn = get_db()
        existing = conn.execute("SELECT * FROM shops WHERE id = ?", (shop_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Partner shop not found."}), 404

        old_logo = (existing["logo_url"] if "logo_url" in existing.keys() else "") or ""
        old_cover = (existing["cover_url"] if "cover_url" in existing.keys() else "") or ""
        bike_cnt = conn.execute("SELECT COUNT(*) FROM bikes WHERE shop_id = ?", (shop_id,)).fetchone()[0]
        booking_cnt = conn.execute("SELECT COUNT(*) FROM bookings WHERE shop_id = ?", (shop_id,)).fetchone()[0]
        with conn:
            conn.execute(
                "DELETE FROM reviews WHERE shop_id = ? OR bike_id IN (SELECT id FROM bikes WHERE shop_id = ?)",
                (shop_id, shop_id),
            )
            conn.execute(
                "DELETE FROM bike_blocks WHERE shop_id = ? OR bike_id IN (SELECT id FROM bikes WHERE shop_id = ?)",
                (shop_id, shop_id),
            )
            conn.execute(
                "DELETE FROM bookings WHERE shop_id = ? OR bike_id IN (SELECT id FROM bikes WHERE shop_id = ?)",
                (shop_id, shop_id),
            )
            conn.execute("DELETE FROM bikes WHERE shop_id = ?", (shop_id,))
            conn.execute("DELETE FROM shops WHERE id = ?", (shop_id,))
        if old_logo:
            delete_unused_uploaded_media(conn, old_logo)
        if old_cover:
            delete_unused_uploaded_media(conn, old_cover)
        return jsonify(
            {
                "deleted": True,
                "id": shop_id,
                "deleted_bikes": int(bike_cnt),
                "deleted_bookings": int(booking_cnt),
            }
        )

    @app.get("/api/admin/bookings")
    @admin_required
    def admin_list_bookings():
        conn = get_db()
        status_filter = (request.args.get("status") or "").strip().lower()
        shop_id = request.args.get("shop_id", type=int)
        q = (request.args.get("q") or "").strip().lower()

        sql = """
            SELECT b.*, k.name AS bike_name, k.image_url AS bike_image,
                   k.category AS bike_category, k.transmission AS bike_transmission,
                   k.plate_number AS plate_number,
                   s.shop_name AS shop_name, s.municipality AS shop_municipality,
                   s.address AS shop_address, s.phone AS shop_phone,
                   s.whatsapp_number AS shop_whatsapp
            FROM bookings b
            JOIN bikes k ON k.id = b.bike_id
            JOIN shops s ON s.id = b.shop_id
            WHERE 1=1
        """
        params: list = []
        if status_filter and status_filter != "all":
            sql += " AND b.status = ?"
            params.append(status_filter)
        if shop_id:
            sql += " AND b.shop_id = ?"
            params.append(shop_id)
        if q:
            sql += """
                AND (
                    LOWER(b.booking_code) LIKE ?
                    OR LOWER(b.customer_name) LIKE ?
                    OR LOWER(b.customer_phone) LIKE ?
                    OR LOWER(k.name) LIKE ?
                    OR LOWER(s.shop_name) LIKE ?
                )
            """
            like = f"%{q}%"
            params.extend([like, like, like, like, like])

        sql += " ORDER BY CASE b.status WHEN 'pending' THEN 0 WHEN 'active' THEN 1 WHEN 'confirmed' THEN 2 WHEN 'completed' THEN 3 ELSE 4 END, b.pickup_date ASC, b.id DESC"
        rows = conn.execute(sql, params).fetchall()
        return jsonify({"bookings": [_serialize_booking(r) for r in rows]})

    @app.patch("/api/admin/bookings/<int:booking_id>")
    @admin_required
    def admin_update_booking(booking_id: int):
        payload = request.get_json(silent=True) or {}
        conn = get_db()
        existing = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Booking not found."}), 404

        new_status = (payload.get("status") or existing["status"]).strip().lower()
        if new_status not in VALID_BOOKING_STATUSES:
            return jsonify({"error": "Invalid booking status."}), 400

        existing_pay_status = str(existing["payment_status"] or "unpaid").strip().lower()
        new_payment_status = (
            str(payload["payment_status"]).strip().lower()
            if "payment_status" in payload and payload["payment_status"] is not None
            else existing_pay_status
        )
        if new_payment_status not in VALID_PAYMENT_STATUSES:
            return jsonify({"error": "Invalid payment status."}), 400

        total_amount = float(existing["total_amount"] or 0)
        reservation_fee = float(existing["reservation_fee"] or 0)
        if "payment_status" in payload and new_payment_status in ("submitted", "verified") and reservation_fee <= 0:
            return jsonify({"error": "No online reservation payment was submitted for this booking."}), 400

        if new_payment_status in ("rejected", "refunded", "unpaid"):
            new_balance_due = round(total_amount, 2)
        else:
            new_balance_due = round(max(0.0, total_amount - reservation_fee), 2)

        admin_notes = (
            payload["admin_notes"].strip()
            if "admin_notes" in payload and payload["admin_notes"] is not None
            else existing["admin_notes"]
        )

        if new_status in BLOCKING_STATUSES and existing["status"] not in BLOCKING_STATUSES:
            bike = conn.execute("SELECT * FROM bikes WHERE id = ?", (existing["bike_id"],)).fetchone()
            if not bike:
                return jsonify({"error": "Associated motorbike not found."}), 404
            booked = count_overlapping_bookings(
                conn,
                existing["bike_id"],
                existing["pickup_date"],
                existing["return_date"],
                exclude_booking_id=booking_id,
            )
            if booked >= int(bike["units_count"] or 1):
                return (
                    jsonify(
                        {
                            "error": (
                                f"Cannot re-activate booking: all units of {bike['name']} "
                                f"are already booked between {existing['pickup_date']} and {existing['return_date']}."
                            )
                        }
                    ),
                    409,
                )

        new_balance_paid, balance_error = _resolve_balance_paid(payload, existing)
        if balance_error:
            return jsonify({"error": balance_error}), 400

        now = datetime.now().isoformat(timespec="seconds")
        with conn:
            conn.execute(
                """
                UPDATE bookings
                SET status = ?, payment_status = ?, balance_due = ?, balance_paid = ?,
                    admin_notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    new_payment_status,
                    new_balance_due,
                    1 if new_balance_paid else 0,
                    admin_notes,
                    now,
                    booking_id,
                ),
            )
        updated = _fetch_booking_by_id(conn, booking_id)
        return jsonify({"booking": _serialize_booking(updated)})

    @app.get("/api/admin/bikes")
    @admin_required
    def admin_list_bikes():
        conn = get_db()
        shop_id = request.args.get("shop_id", type=int)
        today_str = date.today().isoformat()
        sql = """
            SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality,
                   s.status AS shop_status
            FROM bikes b
            JOIN shops s ON s.id = b.shop_id
            WHERE 1=1
        """
        params: list = []
        if shop_id:
            sql += " AND b.shop_id = ?"
            params.append(shop_id)
        sql += " ORDER BY b.id DESC"
        rows = conn.execute(sql, params).fetchall()
        schedules = build_bike_schedules(
            conn,
            rows,
            ref_pickup_date=today_str,
            ref_return_date=today_str,
            include_calendar=False,
            include_admin_details=True,
        )
        items = []
        for row in rows:
            sched = schedules.get(int(row["id"]))
            booked = int((sched or {}).get("ref_booked_units", 0))
            items.append(_serialize_bike(row, booked_units=booked, schedule=sched))
        return jsonify({"bikes": items})

    @app.post("/api/admin/bikes")
    @admin_required
    def admin_create_bike():
        conn = get_db()
        try:
            fields = _extract_bike_payload()
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        raw_shop_id = fields.get("shop_id")
        if not raw_shop_id:
            first_row = conn.execute(
                "SELECT id FROM shops ORDER BY id ASC LIMIT 1"
            ).fetchone()
            raw_shop_id = int(first_row["id"]) if first_row else 1
        try:
            shop_id = int(raw_shop_id)
        except (TypeError, ValueError):
            return jsonify({"error": "Invalid shop_id."}), 400

        if not conn.execute("SELECT 1 FROM shops WHERE id = ?", (shop_id,)).fetchone():
            return jsonify({"error": "Selected rental shop does not exist."}), 404

        slug = slugify_name(fields["name"], conn)
        now = datetime.now().isoformat(timespec="seconds")
        with conn:
            bike_id = conn.insert_returning_id(
                """
                INSERT INTO bikes (
                    shop_id, name, slug, category, engine_cc, transmission, fuel_type,
                    daily_rate, weekly_rate, deposit, units_count, plate_number,
                    inclusions, description, image_url, status, featured, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    shop_id,
                    fields["name"],
                    slug,
                    fields["category"],
                    fields["engine_cc"],
                    fields["transmission"],
                    fields["fuel_type"],
                    fields["daily_rate"],
                    fields["weekly_rate"],
                    fields["deposit"],
                    fields["units_count"],
                    fields["plate_number"],
                    fields["inclusions"],
                    fields["description"],
                    fields["image_url"],
                    fields["status"],
                    fields["featured"],
                    now,
                ),
            )

        row = conn.execute(
            "SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality, s.status AS shop_status "
            "FROM bikes b JOIN shops s ON s.id = b.shop_id WHERE b.id = ?",
            (bike_id,),
        ).fetchone()
        return jsonify({"bike": _serialize_bike(row)}), 201

    @app.put("/api/admin/bikes/<int:bike_id>")
    @admin_required
    def admin_update_bike(bike_id: int):
        conn = get_db()
        existing = conn.execute("SELECT * FROM bikes WHERE id = ?", (bike_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Motorbike not found."}), 404

        try:
            fields = _extract_bike_payload(existing=existing)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        shop_id = existing["shop_id"]
        if fields.get("shop_id"):
            try:
                shop_id = int(fields["shop_id"])
            except (TypeError, ValueError):
                return jsonify({"error": "Invalid shop_id."}), 400
            if not conn.execute("SELECT 1 FROM shops WHERE id = ?", (shop_id,)).fetchone():
                return jsonify({"error": "Selected rental shop does not exist."}), 404

        slug = slugify_name(fields["name"], conn, exclude_id=bike_id)
        with conn:
            conn.execute(
                """
                UPDATE bikes SET
                    shop_id = ?, name = ?, slug = ?, category = ?, engine_cc = ?, transmission = ?,
                    fuel_type = ?, daily_rate = ?, weekly_rate = ?, deposit = ?,
                    units_count = ?, plate_number = ?, inclusions = ?, description = ?,
                    image_url = ?, status = ?, featured = ?
                WHERE id = ?
                """,
                (
                    shop_id,
                    fields["name"],
                    slug,
                    fields["category"],
                    fields["engine_cc"],
                    fields["transmission"],
                    fields["fuel_type"],
                    fields["daily_rate"],
                    fields["weekly_rate"],
                    fields["deposit"],
                    fields["units_count"],
                    fields["plate_number"],
                    fields["inclusions"],
                    fields["description"],
                    fields["image_url"],
                    fields["status"],
                    fields["featured"],
                    bike_id,
                ),
            )
        if fields["image_url"] != existing["image_url"]:
            delete_unused_uploaded_media(conn, existing["image_url"])
        row = conn.execute(
            "SELECT b.*, s.shop_name AS shop_name, s.municipality AS shop_municipality, s.status AS shop_status "
            "FROM bikes b JOIN shops s ON s.id = b.shop_id WHERE b.id = ?",
            (bike_id,),
        ).fetchone()
        return jsonify({"bike": _serialize_bike(row)})

    @app.delete("/api/admin/bikes/<int:bike_id>")
    @admin_required
    def admin_delete_bike(bike_id: int):
        conn = get_db()
        existing = conn.execute("SELECT * FROM bikes WHERE id = ?", (bike_id,)).fetchone()
        if not existing:
            return jsonify({"error": "Motorbike not found."}), 404

        booking_count = conn.execute(
            "SELECT COUNT(*) FROM bookings WHERE bike_id = ?", (bike_id,)
        ).fetchone()[0]
        if booking_count > 0:
            return (
                jsonify(
                    {
                        "error": (
                            f"Cannot delete {existing['name']} because it has {booking_count} booking record(s). "
                            "Set its status to 'Hidden' or 'Maintenance' instead."
                        )
                    }
                ),
                409,
            )

        with conn:
            conn.execute("DELETE FROM bike_blocks WHERE bike_id = ?", (bike_id,))
            conn.execute("DELETE FROM bikes WHERE id = ?", (bike_id,))
        delete_unused_uploaded_media(conn, existing["image_url"])
        return jsonify({"deleted": True, "id": bike_id})

    @app.patch("/api/admin/bikes/<int:bike_id>/status")
    @admin_required
    def admin_patch_bike_status(bike_id: int):
        conn = get_db()
        existing = _fetch_bike_with_shop(conn, bike_id)
        if not existing:
            return jsonify({"error": "Motorbike not found."}), 404
        res, err, code = _apply_bike_availability_patch(conn, existing, request.get_json(silent=True) or {})
        if err:
            return jsonify({"error": err}), code
        return jsonify(res), code

    @app.get("/api/admin/bikes/<int:bike_id>/blocks")
    @admin_required
    def admin_get_bike_blocks(bike_id: int):
        conn = get_db()
        existing = _fetch_bike_with_shop(conn, bike_id)
        if not existing:
            return jsonify({"error": "Motorbike not found."}), 404
        return jsonify({"bike": _serialize_bike_with_schedule(conn, existing, include_calendar=True)})

    @app.post("/api/admin/bikes/<int:bike_id>/blocks")
    @admin_required
    def admin_add_bike_block(bike_id: int):
        conn = get_db()
        existing = _fetch_bike_with_shop(conn, bike_id)
        if not existing:
            return jsonify({"error": "Motorbike not found."}), 404
        res, err, code = _create_bike_block_entry(conn, existing, request.get_json(silent=True) or {})
        if err:
            return jsonify({"error": err}), code
        return jsonify(res), code

    @app.delete("/api/admin/bikes/<int:bike_id>/blocks/<int:block_id>")
    @admin_required
    def admin_remove_bike_block(bike_id: int, block_id: int):
        conn = get_db()
        existing = _fetch_bike_with_shop(conn, bike_id)
        if not existing:
            return jsonify({"error": "Motorbike not found."}), 404
        res, err, code = _delete_bike_block_entry(conn, existing, block_id)
        if err:
            return jsonify({"error": err}), code
        return jsonify(res), code

    @app.get("/api/admin/settings")
    @admin_required
    def admin_get_settings():
        conn = get_db()
        return jsonify({"settings": get_admin_settings_view(conn)})

    @app.put("/api/admin/settings")
    @admin_required
    def admin_update_settings():
        payload = request.get_json(silent=True) or {}
        conn = get_db()
        editable_keys = (
            "shop_name",
            "tagline",
            "location",
            "address",
            "phone",
            "email",
            "messenger_url",
            "whatsapp_number",
            "currency",
            "reservation_mode",
            "reservation_percent",
            "gcash_account_name",
            "gcash_number",
            "maya_number",
            "payment_instructions",
            "delivery_fee",
            "extra_helmet_fee",
            "top_box_fee",
            "opening_hours",
            "terms_note",
            "admin_telegram_chat_id",
            "admin_notify_email",
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_from_email",
            "paymongo_public_key",
        )
        numeric_keys = {
            "delivery_fee",
            "extra_helmet_fee",
            "top_box_fee",
            "reservation_percent",
        }

        updates: dict[str, str] = {}
        for key in editable_keys:
            if key in payload:
                val = str(payload[key]).strip()
                if key in numeric_keys:
                    try:
                        num = float(val or 0)
                        if num < 0:
                            return jsonify({"error": f"{key} cannot be negative."}), 400
                        if key == "reservation_percent" and num > 100:
                            return jsonify({"error": "Reservation percent cannot exceed 100%."}), 400
                        val = str(int(num) if num.is_integer() else round(num, 2))
                    except ValueError:
                        return jsonify({"error": f"{key} must be a valid number."}), 400
                if key == "shop_name" and not val:
                    return jsonify({"error": "Platform name cannot be empty."}), 400
                if key == "currency" and not val:
                    return jsonify({"error": "Currency symbol cannot be empty."}), 400
                updates[key] = val

        if "reservation_mode" in updates:
            mode_val = updates["reservation_mode"].lower()
            if mode_val not in VALID_RESERVATION_MODES:
                return (
                    jsonify({"error": "Invalid reservation mode. Choose off, optional, or required."}),
                    400,
                )
            updates["reservation_mode"] = mode_val

        new_password = (payload.get("new_password") or "").strip()
        if new_password:
            current_password = payload.get("current_password") or ""
            if not verify_admin_password(conn, current_password):
                return jsonify({"error": "Current admin password is incorrect."}), 400
            if len(new_password) < 6:
                return jsonify({"error": "New password must be at least 6 characters."}), 400
            updates["admin_password_hash"] = generate_password_hash(new_password)

        if "smtp_port" in updates:
            port_raw = (updates["smtp_port"] or "").strip() or "587"
            try:
                port_num = int(port_raw)
                if port_num < 1 or port_num > 65535:
                    raise ValueError("out of range")
                updates["smtp_port"] = str(port_num)
            except ValueError:
                return jsonify({"error": "SMTP Port must be a number between 1 and 65535."}), 400

        for bool_key in ("notify_partner_email", "notify_customer_email"):
            if bool_key in payload:
                updates[bool_key] = "1" if _as_bool(payload.get(bool_key)) else "0"

        if payload.get("clear_telegram_bot_token"):
            updates["telegram_bot_token"] = ""
        elif isinstance(payload.get("telegram_bot_token"), str) and payload["telegram_bot_token"].strip():
            updates["telegram_bot_token"] = payload["telegram_bot_token"].strip()

        if payload.get("clear_smtp_password"):
            updates["smtp_password"] = ""
        elif isinstance(payload.get("smtp_password"), str) and payload["smtp_password"].strip():
            updates["smtp_password"] = payload["smtp_password"].strip()

        if payload.get("clear_paymongo_secret_key"):
            updates["paymongo_secret_key"] = ""
        elif isinstance(payload.get("paymongo_secret_key"), str) and payload["paymongo_secret_key"].strip():
            updates["paymongo_secret_key"] = payload["paymongo_secret_key"].strip()

        if payload.get("clear_paymongo_webhook_secret"):
            updates["paymongo_webhook_secret"] = ""
        elif isinstance(payload.get("paymongo_webhook_secret"), str) and payload["paymongo_webhook_secret"].strip():
            updates["paymongo_webhook_secret"] = payload["paymongo_webhook_secret"].strip()

        old_qr_url = ""
        if _as_bool(payload.get("clear_gcash_qr")):
            qr_row = conn.execute("SELECT value FROM settings WHERE key = 'gcash_qr_url'").fetchone()
            old_qr_url = qr_row["value"] if qr_row else ""
            updates["gcash_qr_url"] = ""

        with conn:
            for key, val in updates.items():
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, val),
                )

        if old_qr_url:
            delete_unused_uploaded_media(conn, old_qr_url)

        return jsonify({"settings": get_admin_settings_view(conn)})

    @app.post("/api/admin/settings/qr")
    @admin_required
    def admin_upload_qr():
        qr_file = request.files.get("qr_image") or request.files.get("image")
        try:
            validated_qr = _validate_image_upload(qr_file, prefix="qr")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        if validated_qr is None:
            return (
                jsonify({"error": "Please select a QR code image (PNG, JPG, JPEG, or WEBP)."}),
                400,
            )

        conn = get_db()
        old_row = conn.execute("SELECT value FROM settings WHERE key = 'gcash_qr_url'").fetchone()
        old_qr_url = old_row["value"] if old_row else ""
        with conn:
            new_qr_url = _save_validated_image(conn, validated_qr, use_tx=False)
            conn.execute(
                "INSERT INTO settings (key, value) VALUES ('gcash_qr_url', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (new_qr_url,),
            )
        if old_qr_url and old_qr_url != new_qr_url:
            delete_unused_uploaded_media(conn, old_qr_url)
        return jsonify({"gcash_qr_url": new_qr_url, "settings": get_admin_settings_view(conn)})

    @app.post("/api/admin/settings/test-alert")
    @admin_required
    def admin_test_alert():
        payload = request.get_json(silent=True) or {}
        conn = get_db()
        cfg = dict(get_settings(conn, include_secrets=True))
        for key in (
            "telegram_bot_token",
            "smtp_host",
            "smtp_port",
            "smtp_username",
            "smtp_password",
            "smtp_from_email",
        ):
            override = payload.get(key)
            if isinstance(override, str) and override.strip():
                cfg[key] = override.strip()

        chat_id = (
            (payload.get("admin_telegram_chat_id") if "admin_telegram_chat_id" in payload else cfg.get("admin_telegram_chat_id"))
            or ""
        ).strip()
        email_to = (
            (payload.get("admin_notify_email") if "admin_notify_email" in payload else cfg.get("admin_notify_email"))
            or ""
        ).strip()

        has_smtp = bool((cfg.get("smtp_host") or "").strip())
        results = send_test_alert(
            cfg,
            telegram_chat_id=chat_id if (chat_id or not has_smtp) else None,
            email_to=email_to if has_smtp else None,
            label="Main Admin",
        )
        ok_any = any(item.get("ok") for item in results.values())
        return jsonify({"ok": ok_any, "results": results}), (200 if ok_any else 400)

    register_call_routes(app, get_db)

    return app


app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
