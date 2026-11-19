"""In-app voice call signaling (WebRTC) between customers and shops / admin.

Audio flows peer-to-peer in the browser. This module only relays the small
SDP offer/answer and ICE candidate messages through the database using plain
HTTP polling, so it works on hosts without WebSocket support.
"""

import json
import os
import re
from datetime import datetime, timedelta

from flask import jsonify, request, session

RING_TIMEOUT_SECONDS = 45
ACTIVE_MAX_HOURS = 3
MAX_SDP_CHARS = 30000
MAX_CANDIDATES = 80
LIVE_STATUSES = ("ringing", "active")


def _normalize_phone(phone: str) -> str:
    return re.sub(r"\D+", "", phone or "")


def _phones_match(stored: str, provided: str) -> bool:
    s = _normalize_phone(stored)
    p = _normalize_phone(provided)
    if not s or len(p) < 4:
        return False
    if s == p or s.endswith(p):
        return True
    return len(s) >= 10 and len(p) >= 10 and s[-10:] == p[-10:]


def _now() -> datetime:
    return datetime.now()


def _stamp(dt: datetime | None = None) -> str:
    return (dt or _now()).isoformat(timespec="seconds")


def _expire_stale(conn) -> None:
    ring_cutoff = _stamp(_now() - timedelta(seconds=RING_TIMEOUT_SECONDS))
    active_cutoff = _stamp(_now() - timedelta(hours=ACTIVE_MAX_HOURS))
    with conn:
        conn.execute(
            "UPDATE booking_calls SET status = 'missed', updated_at = ? "
            "WHERE status = 'ringing' AND created_at < ?",
            (_stamp(), ring_cutoff),
        )
        conn.execute(
            "UPDATE booking_calls SET status = 'ended', updated_at = ? "
            "WHERE status = 'active' AND updated_at < ?",
            (_stamp(), active_cutoff),
        )


def _find_booking(conn, booking_code: str):
    code = (booking_code or "").strip().upper()
    if not code:
        return None
    return conn.execute(
        """
        SELECT b.id, b.booking_code, b.shop_id, b.customer_name, b.customer_phone, b.status,
               s.shop_name AS shop_name
        FROM bookings b
        JOIN shops s ON s.id = b.shop_id
        WHERE UPPER(b.booking_code) = ?
        """,
        (code,),
    ).fetchone()


def _actor_for_booking(booking, phone: str):
    """Return 'shop' for admin / owning partner shop, 'customer' for the renter, else None."""
    if booking is None:
        return None
    if session.get("is_admin"):
        return "shop"
    partner_id = session.get("partner_shop_id")
    if partner_id and int(partner_id) == int(booking["shop_id"]):
        return "shop"
    if phone and _phones_match(booking["customer_phone"], phone):
        return "customer"
    return None


def _load_candidates(raw) -> list:
    try:
        data = json.loads(raw or "[]")
        return data if isinstance(data, list) else []
    except (TypeError, ValueError):
        return []


def _call_view(row, my_role: str) -> dict:
    is_caller = my_role == row["caller_role"]
    view = {
        "id": row["id"],
        "booking_code": row["booking_code"],
        "status": row["status"],
        "caller_role": row["caller_role"],
        "caller_name": row["caller_name"],
        "callee_name": row["callee_name"],
        "my_party": "caller" if is_caller else "callee",
        "created_at": row["created_at"],
    }
    if is_caller:
        view["answer_sdp"] = row["answer_sdp"]
        view["remote_candidates"] = _load_candidates(row["callee_candidates"])
    else:
        view["offer_sdp"] = row["offer_sdp"]
        view["remote_candidates"] = _load_candidates(row["caller_candidates"])
    return view


def register_call_routes(app, get_db) -> None:
    def _auth_call(conn, call_id: int, phone: str):
        row = conn.execute("SELECT * FROM booking_calls WHERE id = ?", (call_id,)).fetchone()
        if not row:
            return None, None, (jsonify({"error": "Call not found."}), 404)
        booking = _find_booking(conn, row["booking_code"])
        role = _actor_for_booking(booking, phone)
        if role is None:
            return None, None, (jsonify({"error": "Not allowed to access this call."}), 403)
        return row, role, None

    @app.get("/api/calls/ice-config")
    def call_ice_config():
        servers = [{"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}]
        turn_urls = [u.strip() for u in os.environ.get("TURN_URLS", "").split(",") if u.strip()]
        if turn_urls:
            servers.append(
                {
                    "urls": turn_urls,
                    "username": os.environ.get("TURN_USERNAME", ""),
                    "credential": os.environ.get("TURN_CREDENTIAL", ""),
                }
            )
        return jsonify({"iceServers": servers})

    @app.post("/api/calls/start")
    def call_start():
        payload = request.get_json(silent=True) or {}
        offer = str(payload.get("offer") or "")
        if not offer or len(offer) > MAX_SDP_CHARS:
            return jsonify({"error": "Invalid call offer."}), 400

        conn = get_db()
        booking = _find_booking(conn, payload.get("booking_code"))
        if booking is None:
            return jsonify({"error": "Booking not found."}), 404
        role = _actor_for_booking(booking, str(payload.get("phone") or ""))
        if role is None:
            return jsonify({"error": "Not allowed to call for this booking."}), 403
        if booking["status"] == "cancelled":
            return jsonify({"error": "This booking was cancelled."}), 409

        if role == "customer":
            caller_name, callee_name = booking["customer_name"], booking["shop_name"]
        else:
            caller_name, callee_name = booking["shop_name"], booking["customer_name"]

        _expire_stale(conn)
        now = _stamp()
        with conn:
            conn.execute(
                "UPDATE booking_calls SET status = 'ended', updated_at = ? "
                "WHERE booking_id = ? AND status IN ('ringing', 'active')",
                (now, booking["id"]),
            )
            call_id = conn.insert_returning_id(
                """
                INSERT INTO booking_calls (
                    booking_id, booking_code, shop_id, caller_role, caller_name, callee_name,
                    status, offer_sdp, answer_sdp, caller_candidates, callee_candidates,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'ringing', ?, '', '[]', '[]', ?, ?)
                """,
                (
                    booking["id"],
                    booking["booking_code"],
                    booking["shop_id"],
                    role,
                    caller_name,
                    callee_name,
                    offer,
                    now,
                    now,
                ),
            )
        row = conn.execute("SELECT * FROM booking_calls WHERE id = ?", (call_id,)).fetchone()
        callee_role = "shop" if role == "customer" else "customer"
        try:
            from push_notifications import notify_incoming_call
            notify_incoming_call(conn, dict(row), dict(booking), callee_role)
        except Exception:
            pass
        return jsonify({"call": _call_view(row, role)}), 201

    @app.get("/api/calls/incoming")
    def call_incoming():
        conn = get_db()
        _expire_stale(conn)
        code = (request.args.get("code") or "").strip()
        phone = request.args.get("phone") or ""

        if code:
            booking = _find_booking(conn, code)
            role = _actor_for_booking(booking, phone)
            if role is None:
                return jsonify({"error": "Not allowed."}), 403
            opposite = "customer" if role == "shop" else "shop"
            row = conn.execute(
                "SELECT * FROM booking_calls WHERE booking_id = ? AND status = 'ringing' "
                "AND caller_role = ? ORDER BY id DESC LIMIT 1",
                (booking["id"], opposite),
            ).fetchone()
        else:
            if session.get("is_admin"):
                row = conn.execute(
                    "SELECT * FROM booking_calls WHERE status = 'ringing' AND caller_role = 'customer' "
                    "ORDER BY id DESC LIMIT 1"
                ).fetchone()
                role = "shop"
            elif session.get("partner_shop_id"):
                row = conn.execute(
                    "SELECT * FROM booking_calls WHERE status = 'ringing' AND caller_role = 'customer' "
                    "AND shop_id = ? ORDER BY id DESC LIMIT 1",
                    (int(session["partner_shop_id"]),),
                ).fetchone()
                role = "shop"
            else:
                return jsonify({"error": "Login required."}), 401

        return jsonify({"call": _call_view(row, role) if row else None})

    @app.get("/api/calls/<int:call_id>")
    def call_state(call_id: int):
        conn = get_db()
        _expire_stale(conn)
        row, role, err = _auth_call(conn, call_id, request.args.get("phone") or "")
        if err:
            return err
        return jsonify({"call": _call_view(row, role)})

    @app.post("/api/calls/<int:call_id>/answer")
    def call_answer(call_id: int):
        payload = request.get_json(silent=True) or {}
        answer = str(payload.get("answer") or "")
        if not answer or len(answer) > MAX_SDP_CHARS:
            return jsonify({"error": "Invalid call answer."}), 400
        conn = get_db()
        _expire_stale(conn)
        row, role, err = _auth_call(conn, call_id, str(payload.get("phone") or ""))
        if err:
            return err
        if role == row["caller_role"]:
            return jsonify({"error": "Only the person being called can answer."}), 403
        if row["status"] != "ringing":
            return jsonify({"error": "This call is no longer ringing."}), 409
        with conn:
            conn.execute(
                "UPDATE booking_calls SET answer_sdp = ?, status = 'active', updated_at = ? WHERE id = ?",
                (answer, _stamp(), call_id),
            )
        row = conn.execute("SELECT * FROM booking_calls WHERE id = ?", (call_id,)).fetchone()
        return jsonify({"call": _call_view(row, role)})

    @app.post("/api/calls/<int:call_id>/candidate")
    def call_candidate(call_id: int):
        payload = request.get_json(silent=True) or {}
        candidate = payload.get("candidate")
        if not isinstance(candidate, dict) or len(json.dumps(candidate)) > 4000:
            return jsonify({"error": "Invalid ICE candidate."}), 400
        conn = get_db()
        row, role, err = _auth_call(conn, call_id, str(payload.get("phone") or ""))
        if err:
            return err
        if row["status"] not in LIVE_STATUSES:
            return jsonify({"ok": False, "status": row["status"]})
        column = "caller_candidates" if role == row["caller_role"] else "callee_candidates"
        items = _load_candidates(row[column])
        if len(items) < MAX_CANDIDATES:
            items.append(candidate)
            with conn:
                conn.execute(
                    f"UPDATE booking_calls SET {column} = ?, updated_at = ? WHERE id = ?",
                    (json.dumps(items), _stamp(), call_id),
                )
        return jsonify({"ok": True})

    @app.post("/api/calls/<int:call_id>/end")
    def call_end(call_id: int):
        payload = request.get_json(silent=True) or {}
        conn = get_db()
        row, role, err = _auth_call(conn, call_id, str(payload.get("phone") or ""))
        if err:
            return err
        if row["status"] in LIVE_STATUSES:
            new_status = "declined" if (row["status"] == "ringing" and role != row["caller_role"]) else "ended"
            with conn:
                conn.execute(
                    "UPDATE booking_calls SET status = ?, updated_at = ? WHERE id = ?",
                    (new_status, _stamp(), call_id),
                )
        row = conn.execute("SELECT * FROM booking_calls WHERE id = ?", (call_id,)).fetchone()
        return jsonify({"call": _call_view(row, role)})
