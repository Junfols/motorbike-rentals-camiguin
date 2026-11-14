import io
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta

from app import create_app


class MotorbikeRentalPWATests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test.db")
        self.upload_dir = os.path.join(self.temp_dir.name, "uploads")
        os.makedirs(self.upload_dir, exist_ok=True)
        self.app = create_app(
            {
                "TESTING": True,
                "DB_PATH": self.db_path,
                "UPLOAD_FOLDER": self.upload_dir,
                "SKIP_ICONS": True,
            }
        )
        self.client = self.app.test_client()

    def tearDown(self):
        self.temp_dir.cleanup()

    def _future_str(self, days_ahead: int) -> str:
        return (date.today() + timedelta(days=days_ahead)).isoformat()

    def test_pages_and_pwa_endpoints(self):
        for route in ("/", "/bookings", "/partner", "/admin", "/offline"):
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200, f"Route {route} failed")
            if route != "/admin":
                self.assertNotIn('href="/admin"', resp.get_data(as_text=True))

        shops_resp = self.client.get("/api/shops")
        self.assertEqual(shops_resp.status_code, 200)
        shops = shops_resp.get_json()["shops"]
        self.assertGreaterEqual(len(shops), 3)

        manifest_resp = self.client.get("/manifest.webmanifest")
        self.assertEqual(manifest_resp.status_code, 200)
        self.assertIn("application/manifest+json", manifest_resp.content_type)
        manifest = manifest_resp.get_json()
        self.assertEqual(manifest["display"], "standalone")
        self.assertTrue(any(icon["sizes"] == "192x192" for icon in manifest["icons"]))
        self.assertTrue(any(icon["sizes"] == "512x512" for icon in manifest["icons"]))

        sw_resp = self.client.get("/sw.js")
        self.assertEqual(sw_resp.status_code, 200)
        self.assertEqual(sw_resp.headers.get("Service-Worker-Allowed"), "/")
        admin_manifest_resp = self.client.get("/admin.webmanifest")
        self.assertEqual(admin_manifest_resp.status_code, 200)
        admin_manifest = admin_manifest_resp.get_json()
        self.assertEqual(admin_manifest["id"], "/admin")
        self.assertEqual(admin_manifest["start_url"], "/admin?source=pwa")
        self.assertEqual(admin_manifest["short_name"], "Admin")
        self.assertEqual(admin_manifest["display"], "standalone")
        self.assertEqual(manifest["id"], "/")
        self.assertIn('href="/admin.webmanifest"', self.client.get("/admin").get_data(as_text=True))
        self.assertIn('href="/manifest.webmanifest"', self.client.get("/").get_data(as_text=True))

    def test_fleet_filtering_and_quote_weekly_discount(self):
        resp = self.client.get("/api/bikes?category=Big%20Bike")
        self.assertEqual(resp.status_code, 200)
        bikes = resp.get_json()["bikes"]
        self.assertEqual(len(bikes), 1)
        dominar = bikes[0]
        self.assertEqual(dominar["name"], "Kawasaki Dominar 400")

        # 8-day rental should apply 1 weekly rate (9600) + 1 daily rate (1600) = 11200, saving 1600
        p = self._future_str(2)
        r = self._future_str(10)
        quote_resp = self.client.get(
            f"/api/quote?bike_id={dominar['id']}&pickup_date={p}&return_date={r}"
            "&pickup_method=delivery&extra_helmet=1&top_box=1"
        )
        self.assertEqual(quote_resp.status_code, 200)
        q = quote_resp.get_json()["quote"]
        self.assertEqual(q["rental_days"], 8)
        self.assertEqual(q["base_subtotal"], 11200.0)
        self.assertEqual(q["discount_saved"], 1600.0)
        self.assertEqual(q["addons_total"], 1200.0)  # (50 + 100) * 8
        self.assertEqual(q["delivery_total"], 150.0)   # Benoni Port Moto Express delivery rate
        self.assertEqual(q["total_amount"], 12550.0)
        self.assertEqual(q["commission_rate"], 10.0)
        self.assertEqual(q["platform_fee"], 1255.0)
        self.assertEqual(q["shop_payout"], 11295.0)
        self.assertTrue(q["is_available"])

    def test_booking_conflict_and_lookup_and_cancel(self):
        # Kawasaki Dominar 400 has units_count = 1
        dominar = self.client.get("/api/bikes?category=Big%20Bike").get_json()["bikes"][0]
        p1 = self._future_str(3)
        r1 = self._future_str(5)

        payload = {
            "bike_id": dominar["id"],
            "customer_name": "Juan Dela Cruz",
            "customer_phone": "+63 917 111 2233",
            "customer_email": "juan@example.com",
            "license_number": "G01-22-998877",
            "pickup_date": p1,
            "return_date": r1,
            "pickup_time": "09:00",
            "pickup_method": "shop",
        }
        create_resp = self.client.post("/api/bookings", json=payload)
        self.assertEqual(create_resp.status_code, 201)
        booking = create_resp.get_json()["booking"]
        self.assertTrue(booking["booking_code"].startswith("MR-"))
        self.assertEqual(booking["status"], "pending")

        # Overlapping booking on the single unit must fail with 409 Conflict
        overlap_payload = dict(payload)
        overlap_payload["pickup_date"] = self._future_str(4)
        overlap_payload["return_date"] = self._future_str(6)
        overlap_resp = self.client.post("/api/bookings", json=overlap_payload)
        self.assertEqual(overlap_resp.status_code, 409)

        # Same-day handoff overlap (pickup == previous return) also blocked safely
        handoff_payload = dict(payload)
        handoff_payload["pickup_date"] = r1
        handoff_payload["return_date"] = self._future_str(7)
        handoff_resp = self.client.post("/api/bookings", json=handoff_payload)
        self.assertEqual(handoff_resp.status_code, 409)

        # Lookup requires matching phone digits
        bad_lookup = self.client.get(
            f"/api/bookings/lookup?code={booking['booking_code']}&phone=9999"
        )
        self.assertEqual(bad_lookup.status_code, 403)

        ok_lookup = self.client.get(
            f"/api/bookings/lookup?code={booking['booking_code']}&phone=2233"
        )
        self.assertEqual(ok_lookup.status_code, 200)
        self.assertEqual(ok_lookup.get_json()["booking"]["customer_name"], "Juan Dela Cruz")

        # Also matches local 09xx format against +63 9xx format
        ph_lookup = self.client.get(
            f"/api/bookings/lookup?code={booking['booking_code']}&phone=09171112233"
        )
        self.assertEqual(ph_lookup.status_code, 200)

        # Customer cancels pending booking -> frees dates for new booking
        cancel_resp = self.client.post(
            "/api/bookings/cancel",
            json={"booking_code": booking["booking_code"], "customer_phone": "2233"},
        )
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(cancel_resp.get_json()["booking"]["status"], "cancelled")

        retry_resp = self.client.post("/api/bookings", json=overlap_payload)
        self.assertEqual(retry_resp.status_code, 201)

    def test_admin_auth_workflow_fleet_crud_and_settings(self):
        # Unauthenticated admin API rejected
        self.assertEqual(self.client.get("/api/admin/dashboard").status_code, 401)

        # Wrong password rejected
        bad_login = self.client.post("/api/admin/login", json={"password": "wrong"})
        self.assertEqual(bad_login.status_code, 401)

        # Correct default password
        ok_login = self.client.post("/api/admin/login", json={"password": "admin1234"})
        self.assertEqual(ok_login.status_code, 200)

        # Create booking & move through Pending -> Confirmed -> Active -> Completed
        click = self.client.get("/api/bikes?q=Click").get_json()["bikes"][0]
        p = self._future_str(1)
        r = self._future_str(3)
        b_resp = self.client.post(
            "/api/bookings",
            json={
                "bike_id": click["id"],
                "customer_name": "Maria Santos",
                "customer_phone": "09181234567",
                "license_number": "C02-19-123456",
                "pickup_date": p,
                "return_date": r,
            },
        )
        self.assertEqual(b_resp.status_code, 201)
        booking_id = b_resp.get_json()["booking"]["id"]

        for status in ("confirmed", "active", "completed"):
            patch = self.client.patch(
                f"/api/admin/bookings/{booking_id}",
                json={"status": status, "admin_notes": f"Moved to {status}"},
            )
            self.assertEqual(patch.status_code, 200)
            self.assertEqual(patch.get_json()["booking"]["status"], status)

        dash = self.client.get("/api/admin/dashboard").get_json()
        self.assertEqual(dash["kpis"]["completed_count"], 1)
        self.assertEqual(dash["kpis"]["completed_revenue"], 900.0)

        # Add a motorbike with uploaded image via multipart form
        fake_png = (io.BytesIO(b"\x89PNG\r\n\x1a\nfakeimage"), "vespa.png")
        add_bike = self.client.post(
            "/api/admin/bikes",
            data={
                "name": "Vespa Primavera 150",
                "category": "Scooter",
                "engine_cc": "150",
                "transmission": "Automatic",
                "daily_rate": "1200",
                "weekly_rate": "7200",
                "deposit": "3000",
                "units_count": "1",
                "status": "available",
                "image": fake_png,
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(add_bike.status_code, 201)
        new_bike = add_bike.get_json()["bike"]
        self.assertTrue(new_bike["image_url"].startswith("/uploads/"))

        uploaded_img_resp = self.client.get(new_bike["image_url"])
        self.assertEqual(uploaded_img_resp.status_code, 200)
        uploaded_img_resp.close()

        # Update bike
        upd_bike = self.client.put(
            f"/api/admin/bikes/{new_bike['id']}",
            json={"name": "Vespa Primavera 150 S", "daily_rate": 1350},
        )
        self.assertEqual(upd_bike.status_code, 200)
        self.assertEqual(upd_bike.get_json()["bike"]["daily_rate"], 1350.0)

        # Delete bike with no bookings succeeds
        del_bike = self.client.delete(f"/api/admin/bikes/{new_bike['id']}")
        self.assertEqual(del_bike.status_code, 200)

        # Cannot delete bike that has existing bookings
        del_click = self.client.delete(f"/api/admin/bikes/{click['id']}")
        self.assertEqual(del_click.status_code, 409)

        # Update shop settings & manifest reflects new shop name
        upd_settings = self.client.put(
            "/api/admin/settings",
            json={"shop_name": "Cebu Island Rides", "delivery_fee": "300"},
        )
        self.assertEqual(upd_settings.status_code, 200)
        manifest = self.client.get("/manifest.webmanifest").get_json()
        self.assertIn("Cebu Island Rides", manifest["name"])

    def test_centralized_partner_registration_approval_isolation_and_commission(self):
        # Unauthenticated partner API rejected
        self.assertEqual(self.client.get("/api/partner/dashboard").status_code, 401)

        # New rental shop registers as a partner (starts as 'pending')
        reg = self.client.post(
            "/api/partner/register",
            json={
                "shop_name": "Guinsiliban Ride Hub",
                "owner_name": "Elena Abad",
                "email": "elena@guinsilibanrides.ph",
                "phone": "09175558899",
                "municipality": "Guinsiliban",
                "address": "National Highway, Guinsiliban",
                "delivery_fee": 100,
                "password": "mysecret99",
            },
        )
        self.assertEqual(reg.status_code, 201)
        partner_shop = reg.get_json()["shop"]
        self.assertEqual(partner_shop["status"], "pending")
        partner_id = partner_shop["id"]

        # Pending partner adds a motorbike to their shop
        add_partner_bike = self.client.post(
            "/api/partner/bikes",
            json={
                "name": "Yamaha PG-1 115",
                "category": "Adventure",
                "engine_cc": 115,
                "transmission": "Manual",
                "daily_rate": 500,
                "weekly_rate": 3000,
                "deposit": 1500,
                "units_count": 2,
                "status": "available",
            },
        )
        self.assertEqual(add_partner_bike.status_code, 201)
        pg1_id = add_partner_bike.get_json()["bike"]["id"]

        # While pending, bike must NOT appear on public storefront and cannot be booked
        pub_hidden = self.client.get("/api/bikes?q=PG-1").get_json()["bikes"]
        self.assertEqual(len(pub_hidden), 0)

        p_date = self._future_str(5)
        r_date = self._future_str(7)
        blocked_book = self.client.post(
            "/api/bookings",
            json={
                "bike_id": pg1_id,
                "customer_name": "Mark Tan",
                "customer_phone": "09171110000",
                "license_number": "K04-20-112233",
                "pickup_date": p_date,
                "return_date": r_date,
            },
        )
        self.assertEqual(blocked_book.status_code, 409)

        # Isolation check: partner cannot edit/delete bike belonging to another shop (id=1)
        self.assertEqual(
            self.client.put("/api/partner/bikes/1", json={"name": "Hijacked"}).status_code,
            404,
        )
        self.assertEqual(self.client.delete("/api/partner/bikes/1").status_code, 404)

        # Main Admin updates platform commission to 15% and approves Guinsiliban Ride Hub
        self.assertEqual(
            self.client.post("/api/admin/login", json={"password": "admin1234"}).status_code,
            200,
        )
        upd_comm = self.client.put("/api/admin/settings", json={"commission_rate": "15"})
        self.assertEqual(upd_comm.status_code, 200)
        approve = self.client.patch(f"/api/admin/shops/{partner_id}", json={"status": "approved"})
        self.assertEqual(approve.status_code, 200)
        self.assertEqual(approve.get_json()["shop"]["status"], "approved")

        # Approved partner shop & bike are now visible publicly and bookable
        pub_visible = self.client.get("/api/bikes?municipality=Guinsiliban").get_json()["bikes"]
        self.assertEqual(len(pub_visible), 1)
        self.assertEqual(pub_visible[0]["shop_id"], partner_id)

        ok_book = self.client.post(
            "/api/bookings",
            json={
                "bike_id": pg1_id,
                "customer_name": "Mark Tan",
                "customer_phone": "09171110000",
                "license_number": "K04-20-112233",
                "pickup_date": p_date,
                "return_date": r_date,
                "pickup_method": "delivery",
                "delivery_address": "Mantigue Jump-off Resort",
            },
        )
        self.assertEqual(ok_book.status_code, 201)
        booked = ok_book.get_json()["booking"]
        # 2 days * 500 = 1000 + 100 shop delivery = 1100 total; 15% fee = 165; payout = 935
        self.assertEqual(booked["total_amount"], 1100.0)
        self.assertEqual(booked["commission_rate"], 15.0)
        self.assertEqual(booked["platform_fee"], 165.0)
        self.assertEqual(booked["shop_payout"], 935.0)

        # Partner logs in cleanly, confirms booking, and checks KPIs + Admin dashboard totals
        self.client.post("/api/partner/logout")
        relogin = self.client.post(
            "/api/partner/login",
            json={"email": "elena@guinsilibanrides.ph", "password": "mysecret99"},
        )
        self.assertEqual(relogin.status_code, 200)
        confirm = self.client.patch(
            f"/api/partner/bookings/{booked['id']}",
            json={"status": "confirmed", "admin_notes": "Ready for delivery"},
        )
        self.assertEqual(confirm.status_code, 200)
        p_dash = self.client.get("/api/partner/dashboard").get_json()
        self.assertEqual(p_dash["kpis"]["gross_revenue"], 1100.0)
        self.assertEqual(p_dash["kpis"]["platform_fee_total"], 165.0)
        self.assertEqual(p_dash["kpis"]["net_payout"], 935.0)

        a_dash = self.client.get("/api/admin/dashboard").get_json()
        self.assertEqual(a_dash["kpis"]["platform_fee_total"], 165.0)
        self.assertEqual(a_dash["kpis"]["partner_payout_total"], 935.0)

        # Suspending partner hides fleet and blocks partner mutations & new bookings
        susp = self.client.patch(f"/api/admin/shops/{partner_id}", json={"status": "suspended"})
        self.assertEqual(susp.status_code, 200)
        self.assertEqual(len(self.client.get("/api/bikes?municipality=Guinsiliban").get_json()["bikes"]), 0)
        self.assertEqual(
            self.client.post(
                "/api/partner/bikes",
                json={"name": "Blocked Bike", "category": "Scooter", "daily_rate": 400},
            ).status_code,
            403,
        )

    def test_legacy_single_shop_db_migration(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy_db = os.path.join(tmp, "legacy.db")
            legacy_uploads = os.path.join(tmp, "uploads")
            os.makedirs(legacy_uploads, exist_ok=True)
            conn = sqlite3.connect(legacy_db)
            conn.executescript(
                """
                CREATE TABLE bikes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    slug TEXT UNIQUE NOT NULL,
                    category TEXT NOT NULL,
                    engine_cc INTEGER NOT NULL DEFAULT 125,
                    transmission TEXT NOT NULL DEFAULT 'Automatic',
                    fuel_type TEXT NOT NULL DEFAULT 'Gasoline',
                    daily_rate REAL NOT NULL,
                    weekly_rate REAL NOT NULL DEFAULT 0,
                    deposit REAL NOT NULL DEFAULT 0,
                    units_count INTEGER NOT NULL DEFAULT 1,
                    plate_number TEXT DEFAULT '',
                    inclusions TEXT DEFAULT '',
                    description TEXT DEFAULT '',
                    image_url TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'available',
                    featured INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    booking_code TEXT UNIQUE NOT NULL,
                    bike_id INTEGER NOT NULL,
                    customer_name TEXT NOT NULL,
                    customer_phone TEXT NOT NULL,
                    customer_email TEXT DEFAULT '',
                    license_number TEXT NOT NULL,
                    pickup_date TEXT NOT NULL,
                    return_date TEXT NOT NULL,
                    pickup_time TEXT NOT NULL DEFAULT '09:00',
                    pickup_method TEXT NOT NULL DEFAULT 'shop',
                    delivery_address TEXT DEFAULT '',
                    extra_helmet INTEGER NOT NULL DEFAULT 0,
                    top_box INTEGER NOT NULL DEFAULT 0,
                    rental_days INTEGER NOT NULL DEFAULT 1,
                    daily_rate REAL NOT NULL,
                    base_subtotal REAL NOT NULL,
                    addons_total REAL NOT NULL DEFAULT 0,
                    delivery_total REAL NOT NULL DEFAULT 0,
                    total_amount REAL NOT NULL,
                    deposit_amount REAL NOT NULL DEFAULT 0,
                    notes TEXT DEFAULT '',
                    admin_notes TEXT DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT INTO bikes (name, slug, category, daily_rate, created_at)
                VALUES ('Legacy Beat 110', 'legacy-beat-110', 'Scooter', 400, '2026-01-01T00:00:00');
                INSERT INTO bookings (
                    booking_code, bike_id, customer_name, customer_phone, license_number,
                    pickup_date, return_date, daily_rate, base_subtotal, total_amount,
                    status, created_at, updated_at
                ) VALUES (
                    'MR-2601-0001', 1, 'Legacy Rider', '09170000001', 'L01',
                    '2026-12-01', '2026-12-02', 400, 400, 400,
                    'confirmed', '2026-01-01T00:00:00', '2026-01-01T00:00:00'
                );
                """
            )
            conn.commit()
            conn.close()

            migrated_app = create_app(
                {
                    "TESTING": True,
                    "DB_PATH": legacy_db,
                    "UPLOAD_FOLDER": legacy_uploads,
                    "SKIP_ICONS": True,
                }
            )
            client = migrated_app.test_client()
            bikes = client.get("/api/bikes?q=Legacy").get_json()["bikes"]
            self.assertEqual(len(bikes), 1)
            self.assertEqual(bikes[0]["shop_id"], 1)
            lookup = client.get("/api/bookings/lookup?code=MR-2601-0001&phone=0001").get_json()
            self.assertEqual(lookup["booking"]["shop_payout"], 400.0)

    def test_health_and_db_media_persistence_and_cleanup(self):
        health = self.client.get("/api/health").get_json()
        self.assertEqual(health["status"], "ok")
        self.assertEqual(health["backend"], "sqlite")

        self.assertEqual(
            self.client.post("/api/admin/login", json={"password": "admin1234"}).status_code,
            200,
        )
        photo_bytes = b"\x89PNG\r\n\x1a\nrender-ephemeral-disk-proof"
        add_resp = self.client.post(
            "/api/admin/bikes",
            data={
                "shop_id": "1",
                "name": "Suzuki Burgman Street 125",
                "category": "Scooter",
                "engine_cc": "125",
                "transmission": "Automatic",
                "daily_rate": "500",
                "units_count": "1",
                "image": (io.BytesIO(photo_bytes), "burgman.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(add_resp.status_code, 201)
        bike = add_resp.get_json()["bike"]
        img_url = bike["image_url"]
        self.assertTrue(img_url.startswith("/uploads/"))

        # Must be served from database even though nothing was written to UPLOAD_FOLDER
        self.assertEqual(os.listdir(self.upload_dir), [])
        media_resp = self.client.get(img_url)
        self.assertEqual(media_resp.status_code, 200)
        self.assertEqual(media_resp.data, photo_bytes)
        media_resp.close()

        # Deleting the bike should also clean up its unreferenced uploaded_media row
        self.assertEqual(self.client.delete(f"/api/admin/bikes/{bike['id']}").status_code, 200)
        gone_resp = self.client.get(img_url)
        self.assertEqual(gone_resp.status_code, 404)
        gone_resp.close()

    def test_postgres_adapter_translation_and_simulated_flow(self):
        import re
        import sys
        import types
        from unittest.mock import patch

        from db import CompatRow, get_database_url, translate_sql_to_postgres

        self.assertEqual(
            get_database_url("postgres://u:p@host.neon.tech/neondb?sslmode=require"),
            "postgresql://u:p@host.neon.tech/neondb?sslmode=require",
        )
        translated = translate_sql_to_postgres(
            "SELECT * FROM bikes WHERE name = ? AND note = 'How much? 50% off'"
        )
        self.assertEqual(
            translated,
            "SELECT * FROM bikes WHERE name = %s AND note = 'How much? 50% off'",
        )

        row = CompatRow(["id", "shop_name"], [7, "Camiguin Hub"])
        self.assertEqual(row[0], 7)
        self.assertEqual(row["shop_name"], "Camiguin Hub")
        self.assertEqual(row.keys(), ["id", "shop_name"])

        # Simulate psycopg v3 connection backed by an isolated SQLite DB to exercise all PG code paths
        pg_sim_db = os.path.join(self.temp_dir.name, "pg_sim.db")

        def _pg_sql_to_sqlite(sql: str) -> str:
            s = sql
            s = s.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            s = s.replace("DOUBLE PRECISION", "REAL")
            s = s.replace("BYTEA", "BLOB")
            s = s.replace("FOR UPDATE", "")
            s = re.sub(r"\s+RETURNING\s+id\b", "", s, flags=re.IGNORECASE)
            # Replace %s placeholders outside single quotes back to ?
            out = []
            i = 0
            in_sq = False
            while i < len(s):
                if s[i] == "'":
                    in_sq = not in_sq
                    out.append(s[i])
                elif not in_sq and s[i : i + 2] == "%s":
                    out.append("?")
                    i += 2
                    continue
                elif not in_sq and s[i : i + 2] == "%%":
                    out.append("%")
                    i += 2
                    continue
                else:
                    out.append(s[i])
                i += 1
            return "".join(out)

        class _ColDesc:
            def __init__(self, name: str):
                self.name = name

        class _FakePgCursor:
            def __init__(self, sqlite_cur):
                self._c = sqlite_cur
                self.description = (
                    [_ColDesc(d[0]) for d in sqlite_cur.description]
                    if sqlite_cur.description
                    else None
                )

            def fetchone(self):
                return self._c.fetchone()

            def fetchall(self):
                return self._c.fetchall()

            def executemany(self, sql, seq):
                sq_sql = _pg_sql_to_sqlite(sql)
                self._c.executemany(sq_sql, seq)
                return self

        class _FakePgTx:
            def __init__(self, raw):
                self._raw = raw

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                if exc_type:
                    self._raw.rollback()
                else:
                    self._raw.commit()
                return False

        class _FakePgConn:
            def __init__(self, path):
                self._raw = sqlite3.connect(path, timeout=15, check_same_thread=False)

            def execute(self, sql, params=None):
                norm = sql.strip()
                if norm.startswith("SELECT pg_advisory_"):
                    return _FakePgCursor(self._raw.execute("SELECT 1"))
                if "information_schema.columns" in norm and params:
                    tbl = params[0]
                    cols = [(r[1],) for r in self._raw.execute(f"PRAGMA table_info({tbl})").fetchall()]
                    cur = self._raw.execute("SELECT 1")
                    return type("ColsCur", (), {
                        "description": [_ColDesc("column_name")],
                        "fetchone": lambda self_: cols[0] if cols else None,
                        "fetchall": lambda self_: cols,
                    })()
                has_returning = bool(re.search(r"\bRETURNING\s+id\b", norm, re.IGNORECASE))
                sq_sql = _pg_sql_to_sqlite(sql)
                cur = self._raw.execute(sq_sql, tuple(params) if params is not None else ())
                if has_returning:
                    inserted_id = cur.lastrowid
                    return type("RetCur", (), {
                        "description": [_ColDesc("id")],
                        "fetchone": lambda self_: (inserted_id,),
                        "fetchall": lambda self_: [(inserted_id,)],
                    })()
                return _FakePgCursor(cur)

            def cursor(self):
                return _FakePgCursor(self._raw.cursor())

            def transaction(self):
                return _FakePgTx(self._raw)

            def commit(self):
                self._raw.commit()

            def rollback(self):
                self._raw.rollback()

            def close(self):
                self._raw.close()

        fake_psycopg = types.ModuleType("psycopg")
        fake_psycopg.connect = lambda url, connect_timeout=15: _FakePgConn(pg_sim_db)

        with patch.dict(sys.modules, {"psycopg": fake_psycopg}):
            pg_app = create_app(
                {
                    "TESTING": True,
                    "DATABASE_URL": "postgresql://demo:pass@ep-test.neon.tech/neondb?sslmode=require",
                    "UPLOAD_FOLDER": self.upload_dir,
                    "SKIP_ICONS": True,
                }
            )
            client = pg_app.test_client()
            health = client.get("/api/health").get_json()
            self.assertEqual(health["backend"], "postgresql")

            shops = client.get("/api/shops").get_json()["shops"]
            self.assertEqual(len(shops), 3)

            # Partner registration + booking + image upload through PG path
            reg = client.post(
                "/api/partner/register",
                json={
                    "shop_name": "Catarman Reef Rides",
                    "owner_name": "Rico Sia",
                    "email": "rico@catarman.ph",
                    "phone": "09179998888",
                    "municipality": "Catarman",
                    "password": "password123",
                },
            )
            self.assertEqual(reg.status_code, 201)
            shop_id = reg.get_json()["shop"]["id"]
            self.assertGreater(shop_id, 3)

            client.post("/api/admin/login", json={"password": "admin1234"})
            self.assertEqual(
                client.patch(f"/api/admin/shops/{shop_id}", json={"status": "approved"}).status_code,
                200,
            )
            add_bike = client.post(
                "/api/partner/bikes",
                data={
                    "name": "Honda Beat PG",
                    "category": "Scooter",
                    "engine_cc": "110",
                    "transmission": "Automatic",
                    "daily_rate": "400",
                    "image": (io.BytesIO(b"\x89PNG\r\n\x1a\npg"), "pgbeat.png"),
                },
                content_type="multipart/form-data",
            )
            self.assertEqual(add_bike.status_code, 201)
            bike = add_bike.get_json()["bike"]

            pg_img = client.get(bike["image_url"])
            self.assertEqual(pg_img.status_code, 200)
            pg_img.close()

            book = client.post(
                "/api/bookings",
                json={
                    "bike_id": bike["id"],
                    "customer_name": "Ana Cruz",
                    "customer_phone": "09182223333",
                    "license_number": "G01-22-001122",
                    "pickup_date": self._future_str(2),
                    "return_date": self._future_str(4),
                },
            )
            self.assertEqual(book.status_code, 201)
            self.assertEqual(book.get_json()["booking"]["total_amount"], 800.0)

    def test_alert_settings_masking_and_secret_isolation(self):
        from db import SECRET_SETTING_KEYS

        # Unauthenticated requests cannot read or test admin alert secrets
        self.assertEqual(self.client.get("/api/admin/settings").status_code, 401)
        self.assertEqual(self.client.post("/api/admin/settings/test-alert", json={}).status_code, 401)

        self.client.post("/api/admin/login", json={"password": "admin1234"})
        put_resp = self.client.put(
            "/api/admin/settings",
            json={
                "telegram_bot_token": "123456:TEST_BOT_TOKEN",
                "admin_telegram_chat_id": "987654321",
                "admin_notify_email": "owner@camiguin.ph",
                "smtp_host": "smtp.gmail.com",
                "smtp_port": "465",
                "smtp_username": "owner@gmail.com",
                "smtp_password": "app-secret-password",
                "smtp_from_email": "noreply@camiguin.ph",
                "notify_partner_email": True,
                "notify_customer_email": True,
            },
        )
        self.assertEqual(put_resp.status_code, 200)
        admin_cfg = put_resp.get_json()["settings"]
        self.assertTrue(admin_cfg["has_telegram_bot_token"])
        self.assertTrue(admin_cfg["has_smtp_password"])
        self.assertEqual(admin_cfg["admin_telegram_chat_id"], "987654321")
        self.assertEqual(admin_cfg["smtp_port"], "465")
        self.assertEqual(admin_cfg["notify_customer_email"], "1")
        self.assertNotIn("telegram_bot_token", admin_cfg)
        self.assertNotIn("smtp_password", admin_cfg)

        # Updating non-secret field with blank token must keep saved token intact
        keep_resp = self.client.put(
            "/api/admin/settings",
            json={"shop_name": "Motorbike Rentals Camiguin", "telegram_bot_token": ""},
        )
        self.assertEqual(keep_resp.status_code, 200)
        self.assertTrue(keep_resp.get_json()["settings"]["has_telegram_bot_token"])

        # Public endpoints must never leak secret settings or tokens
        pub_settings = self.client.get("/api/settings").get_json()["settings"]
        for key in SECRET_SETTING_KEYS:
            self.assertNotIn(key, pub_settings)
        home_html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("TEST_BOT_TOKEN", home_html)
        self.assertNotIn("app-secret-password", home_html)

        # Public shop list must not expose partner telegram_chat_id
        for shop in self.client.get("/api/shops").get_json()["shops"]:
            self.assertNotIn("telegram_chat_id", shop)

        # Invalid SMTP port is rejected
        bad_port = self.client.put("/api/admin/settings", json={"smtp_port": "99999"})
        self.assertEqual(bad_port.status_code, 400)

        # Explicit clear flag wipes saved token
        cleared = self.client.put(
            "/api/admin/settings",
            json={"clear_telegram_bot_token": True, "clear_smtp_password": True},
        )
        self.assertEqual(cleared.status_code, 200)
        cleared_cfg = cleared.get_json()["settings"]
        self.assertFalse(cleared_cfg["has_telegram_bot_token"])
        self.assertFalse(cleared_cfg["has_smtp_password"])

    def test_alert_dispatch_on_partner_and_booking_events(self):
        dispatched = []

        def _capture_dispatcher(fn, *args):
            dispatched.append((fn.__name__, args))

        alert_db = os.path.join(self.temp_dir.name, "alerts.db")
        alert_app = create_app(
            {
                "TESTING": True,
                "DB_PATH": alert_db,
                "UPLOAD_FOLDER": self.upload_dir,
                "SKIP_ICONS": True,
                "NOTIFICATION_DISPATCHER": _capture_dispatcher,
            }
        )
        client = alert_app.test_client()

        client.post("/api/admin/login", json={"password": "admin1234"})
        client.put(
            "/api/admin/settings",
            json={
                "telegram_bot_token": "999:FAKE_TOKEN",
                "admin_telegram_chat_id": "111222333",
            },
        )

        # 1. Partner registration dispatches new partner alert and stores telegram_chat_id
        reg = client.post(
            "/api/partner/register",
            json={
                "shop_name": "Mantigue Scooters",
                "owner_name": "Carlo Reyes",
                "email": "carlo@mantigue.ph",
                "phone": "09175551234",
                "telegram_chat_id": "99887766",
                "municipality": "Mahinog",
                "password": "password123",
            },
        )
        self.assertEqual(reg.status_code, 201)
        reg_data = reg.get_json()
        self.assertTrue(reg_data["platform_telegram_enabled"])
        self.assertEqual(reg_data["shop"]["telegram_chat_id"], "99887766")
        self.assertEqual(dispatched[-1][0], "notify_new_partner_registration")
        self.assertEqual(dispatched[-1][1][1]["shop_name"], "Mantigue Scooters")
        shop_id = reg_data["shop"]["id"]

        # 2. Admin approves partner -> dispatches partner status change alert
        upd = client.patch(f"/api/admin/shops/{shop_id}", json={"status": "approved"})
        self.assertEqual(upd.status_code, 200)
        self.assertEqual(dispatched[-1][0], "notify_partner_status_change")
        self.assertEqual(dispatched[-1][1][1]["status"], "approved")

        # 3. Partner updates telegram_chat_id and adds a bike
        prof = client.put("/api/partner/profile", json={"telegram_chat_id": "55443322"})
        self.assertEqual(prof.status_code, 200)
        self.assertEqual(prof.get_json()["shop"]["telegram_chat_id"], "55443322")

        add_bike = client.post(
            "/api/partner/bikes",
            data={
                "name": "Yamaha Mio Gear",
                "category": "Scooter",
                "engine_cc": "125",
                "transmission": "Automatic",
                "daily_rate": "450",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(add_bike.status_code, 201)
        bike_id = add_bike.get_json()["bike"]["id"]

        # 4. New customer booking dispatches notify_new_booking
        book_resp = client.post(
            "/api/bookings",
            json={
                "bike_id": bike_id,
                "customer_name": "Liza Sober",
                "customer_phone": "09181112222",
                "customer_email": "liza@example.com",
                "license_number": "G01-24-556677",
                "pickup_date": self._future_str(3),
                "return_date": self._future_str(5),
            },
        )
        self.assertEqual(book_resp.status_code, 201)
        booking_code = book_resp.get_json()["booking"]["booking_code"]
        self.assertEqual(dispatched[-1][0], "notify_new_booking")
        self.assertEqual(dispatched[-1][1][1]["telegram_chat_id"], "55443322")
        self.assertEqual(dispatched[-1][1][2]["booking_code"], booking_code)

        # 5. Customer pending cancellation dispatches notify_booking_cancelled_by_customer
        cancel_resp = client.post(
            "/api/bookings/cancel",
            json={"booking_code": booking_code, "customer_phone": "09181112222"},
        )
        self.assertEqual(cancel_resp.status_code, 200)
        self.assertEqual(dispatched[-1][0], "notify_booking_cancelled_by_customer")
        self.assertEqual(dispatched[-1][1][2]["booking_code"], booking_code)

    def test_notifications_delivery_and_test_alert_endpoints(self):
        import json as _json
        from unittest.mock import MagicMock, patch
        import notifications

        class _FakeHTTPResp:
            def __init__(self, payload: dict):
                self._raw = _json.dumps(payload).encode("utf-8")

            def read(self):
                return self._raw

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        telegram_calls = []

        def _fake_urlopen(req, timeout=8):
            telegram_calls.append(
                {
                    "url": req.full_url,
                    "body": _json.loads(req.data.decode("utf-8")),
                }
            )
            return _FakeHTTPResp({"ok": True, "result": {"message_id": 1}})

        smtp_server = MagicMock()
        smtp_ctx = MagicMock()
        smtp_ctx.__enter__.return_value = smtp_server

        settings = {
            "shop_name": "Motorbike Rentals Camiguin",
            "currency": "₱",
            "telegram_bot_token": "bot123:XYZ",
            "admin_telegram_chat_id": "10001",
            "admin_notify_email": "admin@camiguin.ph",
            "smtp_host": "smtp.example.com",
            "smtp_port": "587",
            "smtp_username": "mailer@example.com",
            "smtp_password": "secret",
            "smtp_from_email": "noreply@camiguin.ph",
            "notify_partner_email": "1",
            "notify_customer_email": "1",
        }
        shop = {
            "shop_name": "Island Rides",
            "municipality": "Mambajao",
            "address": "National Hwy",
            "email": "partner@islandrides.ph",
            "telegram_chat_id": "20002",
        }
        booking = {
            "booking_code": "MRC-TEST01",
            "bike_name": "Honda ADV 160",
            "pickup_date": self._future_str(1),
            "return_date": self._future_str(3),
            "rental_days": 2,
            "pickup_time": "09:00",
            "pickup_method": "shop",
            "customer_name": "Marco Polo",
            "customer_phone": "+639171234567",
            "customer_email": "marco@example.com",
            "total_amount": 1800,
        }

        with (
            patch("urllib.request.urlopen", side_effect=_fake_urlopen),
            patch("smtplib.SMTP", return_value=smtp_ctx) as mock_smtp,
        ):
            res = notifications.notify_new_booking(settings, shop, booking)

        self.assertTrue(res["admin_telegram"]["ok"])
        self.assertTrue(res["partner_telegram"]["ok"])
        self.assertTrue(res["admin_email"]["ok"])
        self.assertTrue(res["partner_email"]["ok"])
        self.assertTrue(res["customer_email"]["ok"])
        self.assertEqual([c["body"]["chat_id"] for c in telegram_calls], ["10001", "20002"])
        mock_smtp.assert_called()
        self.assertEqual(smtp_server.send_message.call_count, 3)

        # Endpoint tests: /api/admin/settings/test-alert and /api/partner/profile/test-alert
        self.client.post("/api/admin/login", json={"password": "admin1234"})
        no_cfg = self.client.post("/api/admin/settings/test-alert", json={})
        self.assertEqual(no_cfg.status_code, 400)
        self.assertFalse(no_cfg.get_json()["ok"])

        self.client.put(
            "/api/admin/settings",
            json={"telegram_bot_token": "bot123:XYZ", "admin_telegram_chat_id": "10001"},
        )
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            admin_test = self.client.post("/api/admin/settings/test-alert", json={})
        self.assertEqual(admin_test.status_code, 200)
        self.assertTrue(admin_test.get_json()["results"]["telegram"]["ok"])

        self.client.post(
            "/api/partner/register",
            json={
                "shop_name": "Sunken Cemetery Bikes",
                "owner_name": "Maya Lim",
                "email": "maya@sunken.ph",
                "phone": "09176667777",
                "telegram_chat_id": "30003",
                "password": "password123",
            },
        )
        with patch("urllib.request.urlopen", side_effect=_fake_urlopen):
            partner_test = self.client.post("/api/partner/profile/test-alert", json={})
        self.assertEqual(partner_test.status_code, 200)
        self.assertTrue(partner_test.get_json()["results"]["telegram"]["ok"])

    def test_legacy_db_migrates_telegram_chat_id(self):
        legacy_db = os.path.join(self.temp_dir.name, "legacy.db")
        raw_conn = sqlite3.connect(legacy_db)
        raw_conn.execute(
            """
            CREATE TABLE shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                owner_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL,
                whatsapp_number TEXT NOT NULL DEFAULT '',
                municipality TEXT NOT NULL DEFAULT 'Mambajao',
                address TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                delivery_fee REAL NOT NULL DEFAULT 200,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                is_main INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            )
            """
        )
        raw_conn.commit()
        raw_conn.close()

        migrated_app = create_app(
            {
                "TESTING": True,
                "DB_PATH": legacy_db,
                "UPLOAD_FOLDER": self.upload_dir,
                "SKIP_ICONS": True,
            }
        )
        self.assertEqual(migrated_app.test_client().get("/api/health").status_code, 200)

        check_conn = sqlite3.connect(legacy_db)
        cols = [r[1] for r in check_conn.execute("PRAGMA table_info(shops)").fetchall()]
        check_conn.close()
        self.assertIn("telegram_chat_id", cols)


    def test_reservation_payment_settings_qr_and_modes(self):
        from db import SECRET_SETTING_KEYS, get_connection

        # Unauthenticated QR upload must be rejected
        no_auth = self.client.post(
            "/api/admin/settings/qr",
            data={"qr_image": (io.BytesIO(b"\x89PNG\r\n\x1a\nFAKE"), "qr.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(no_auth.status_code, 401)

        bikes = self.client.get("/api/bikes").get_json()["bikes"]
        bike = bikes[0]
        p1, r1 = self._future_str(20), self._future_str(21)

        # Before GCash/Maya details exist, quote reports reservation_configured=False and reservation_fee=0
        q_before = self.client.get(
            f"/api/quote?bike_id={bike['id']}&pickup_date={p1}&return_date={r1}"
        ).get_json()["quote"]
        self.assertFalse(q_before["reservation_configured"])
        self.assertEqual(q_before["reservation_fee"], 0.0)
        self.assertEqual(q_before["balance_due"], q_before["total_amount"])

        self.client.post("/api/admin/login", json={"password": "admin1234"})

        # Reject invalid mode / percent
        bad_mode = self.client.put("/api/admin/settings", json={"reservation_mode": "invalid"})
        self.assertEqual(bad_mode.status_code, 400)
        bad_pct = self.client.put("/api/admin/settings", json={"reservation_percent": "120"})
        self.assertEqual(bad_pct.status_code, 400)

        # Upload first QR image -> saved in DB and served via /uploads/
        qr_bytes_1 = b"\x89PNG\r\n\x1a\nFIRST_QR_IMAGE_BYTES"
        up1 = self.client.post(
            "/api/admin/settings/qr",
            data={"qr_image": (io.BytesIO(qr_bytes_1), "gcash-qr.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(up1.status_code, 200)
        qr_url_1 = up1.get_json()["gcash_qr_url"]
        self.assertTrue(qr_url_1.startswith("/uploads/qr_"))
        self.assertEqual(self.client.get(qr_url_1).data, qr_bytes_1)

        # Configure payment details & 15% optional fee
        save_cfg = self.client.put(
            "/api/admin/settings",
            json={
                "reservation_mode": "optional",
                "reservation_percent": "15",
                "gcash_account_name": "Camiguin Main Admin",
                "gcash_number": "09171234567",
                "maya_number": "09187654321",
                "payment_instructions": "Send 15% downpayment and upload receipt.",
            },
        )
        self.assertEqual(save_cfg.status_code, 200)

        # Public settings include GCash/Maya display fields and omit secrets
        pub_settings = self.client.get("/api/settings").get_json()["settings"]
        self.assertEqual(pub_settings["gcash_qr_url"], qr_url_1)
        self.assertEqual(pub_settings["gcash_number"], "09171234567")
        self.assertEqual(pub_settings["maya_number"], "09187654321")
        for key in SECRET_SETTING_KEYS:
            self.assertNotIn(key, pub_settings)

        # Quote now calculates 15% reservation_fee & balance_due
        q_after = self.client.get(
            f"/api/quote?bike_id={bike['id']}&pickup_date={p1}&return_date={r1}"
        ).get_json()["quote"]
        self.assertTrue(q_after["reservation_configured"])
        self.assertEqual(q_after["reservation_mode"], "optional")
        self.assertEqual(q_after["reservation_percent"], 15.0)
        self.assertEqual(q_after["reservation_fee"], round(q_after["total_amount"] * 0.15, 2))
        self.assertEqual(
            q_after["balance_due"],
            round(q_after["total_amount"] - q_after["reservation_fee"], 2),
        )

        # Replacing QR removes old unused QR from uploaded_media
        qr_bytes_2 = b"\x89PNG\r\n\x1a\nSECOND_QR_IMAGE_BYTES"
        up2 = self.client.post(
            "/api/admin/settings/qr",
            data={"qr_image": (io.BytesIO(qr_bytes_2), "gcash-qr-v2.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(up2.status_code, 200)
        qr_url_2 = up2.get_json()["gcash_qr_url"]
        self.assertNotEqual(qr_url_1, qr_url_2)
        self.assertEqual(self.client.get(qr_url_2).data, qr_bytes_2)
        self.assertEqual(self.client.get(qr_url_1).status_code, 404)

        # Enforce required mode rules & atomic rollback of proof image on 409 conflict
        self.client.put("/api/admin/settings", json={"reservation_mode": "required"})
        no_shop_pay = self.client.post(
            "/api/bookings",
            json={
                "bike_id": bike["id"],
                "customer_name": "Elena Santos",
                "customer_phone": "09175551234",
                "license_number": "D01-99-123456",
                "pickup_date": p1,
                "return_date": r1,
                "payment_channel": "pay_at_shop",
            },
        )
        self.assertEqual(no_shop_pay.status_code, 400)

        short_ref = self.client.post(
            "/api/bookings",
            json={
                "bike_id": bike["id"],
                "customer_name": "Elena Santos",
                "customer_phone": "09175551234",
                "license_number": "D01-99-123456",
                "pickup_date": p1,
                "return_date": r1,
                "payment_channel": "gcash",
                "payment_reference": "123",
            },
        )
        self.assertEqual(short_ref.status_code, 400)

        bad_ext = self.client.post(
            "/api/bookings",
            data={
                "bike_id": str(bike["id"]),
                "customer_name": "Elena Santos",
                "customer_phone": "09175551234",
                "license_number": "D01-99-123456",
                "pickup_date": p1,
                "return_date": r1,
                "payment_channel": "gcash",
                "payment_reference": "1234567890123",
                "payment_proof": (io.BytesIO(b"not-an-image"), "receipt.txt"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(bad_ext.status_code, 400)

        # Fill all bike units on p1..r1 so the next proof-bearing booking hits 409 conflict
        for idx in range(int(bike["units_count"])):
            ok_fill = self.client.post(
                "/api/bookings",
                json={
                    "bike_id": bike["id"],
                    "customer_name": f"Rider {idx}",
                    "customer_phone": f"0917555000{idx}",
                    "license_number": f"L00-{idx}",
                    "pickup_date": p1,
                    "return_date": r1,
                    "payment_channel": "maya",
                    "payment_reference": f"MAYA998877{idx}",
                },
            )
            self.assertEqual(ok_fill.status_code, 201)

        conflict_resp = self.client.post(
            "/api/bookings",
            data={
                "bike_id": str(bike["id"]),
                "customer_name": "Late Rider",
                "customer_phone": "09178889999",
                "license_number": "L99-999",
                "pickup_date": p1,
                "return_date": r1,
                "payment_channel": "gcash",
                "payment_reference": "1234567890999",
                "payment_proof": (io.BytesIO(b"\x89PNG\r\n\x1a\nORPHAN_TEST"), "orphan.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(conflict_resp.status_code, 409)

        check_conn = get_connection(self.db_path)
        try:
            proof_rows = check_conn.execute(
                "SELECT filename FROM uploaded_media WHERE filename LIKE 'proof_%'"
            ).fetchall()
        finally:
            check_conn.close()
        self.assertEqual(len(proof_rows), 0)

        # Clear QR leaves gcash_qr_url blank and deletes qr_url_2
        clear_resp = self.client.put("/api/admin/settings", json={"clear_gcash_qr": True})
        self.assertEqual(clear_resp.status_code, 200)
        self.assertEqual(clear_resp.get_json()["settings"]["gcash_qr_url"], "")
        self.assertEqual(self.client.get(qr_url_2).status_code, 404)

    def test_reservation_payment_multipart_proof_verification_and_kpis(self):
        self.client.post("/api/admin/login", json={"password": "admin1234"})
        self.client.put(
            "/api/admin/settings",
            json={
                "reservation_mode": "optional",
                "reservation_percent": "10",
                "gcash_number": "09170001111",
            },
        )

        bikes = self.client.get("/api/bikes").get_json()["bikes"]
        bike = bikes[0]

        # 1. Pay at shop under optional mode
        p1, r1 = self._future_str(25), self._future_str(26)
        shop_booking_resp = self.client.post(
            "/api/bookings",
            json={
                "bike_id": bike["id"],
                "customer_name": "Walkin Rider",
                "customer_phone": "09171110001",
                "license_number": "LIC-111",
                "pickup_date": p1,
                "return_date": r1,
                "payment_channel": "pay_at_shop",
            },
        )
        self.assertEqual(shop_booking_resp.status_code, 201)
        b_shop = shop_booking_resp.get_json()["booking"]
        self.assertEqual(b_shop["payment_status"], "unpaid")
        self.assertEqual(b_shop["reservation_fee"], 0.0)
        self.assertEqual(b_shop["balance_due"], b_shop["total_amount"])

        # Cannot verify payment on unpaid booking with 0 reservation_fee
        bad_verify = self.client.patch(
            f"/api/admin/bookings/{b_shop['id']}",
            json={"payment_status": "verified"},
        )
        self.assertEqual(bad_verify.status_code, 400)

        # 2. Online GCash with receipt screenshot via multipart/form-data
        p2, r2 = self._future_str(30), self._future_str(32)
        receipt_bytes = b"\x89PNG\r\n\x1a\nGCASH_RECEIPT_PROOF"
        online_resp = self.client.post(
            "/api/bookings",
            data={
                "bike_id": str(bike["id"]),
                "customer_name": "Carlo Reyes",
                "customer_phone": "09172223333",
                "license_number": "LIC-222",
                "pickup_date": p2,
                "return_date": r2,
                "extra_helmet": "false",
                "top_box": "true",
                "payment_channel": "gcash",
                "payment_reference": "9001234567890",
                "payment_proof": (io.BytesIO(receipt_bytes), "gcash-receipt.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(online_resp.status_code, 201)
        b_online = online_resp.get_json()["booking"]
        self.assertEqual(b_online["payment_channel"], "gcash")
        self.assertEqual(b_online["payment_reference"], "9001234567890")
        self.assertEqual(b_online["payment_status"], "submitted")
        self.assertEqual(b_online["reservation_fee"], round(b_online["total_amount"] * 0.10, 2))
        self.assertEqual(
            b_online["balance_due"],
            round(b_online["total_amount"] - b_online["reservation_fee"], 2),
        )
        self.assertTrue(b_online["payment_proof_url"].startswith("/uploads/proof_"))
        self.assertEqual(self.client.get(b_online["payment_proof_url"]).data, receipt_bytes)

        # Admin KPIs show pending verification before approval
        dash1 = self.client.get("/api/admin/dashboard").get_json()["kpis"]
        self.assertEqual(dash1["pending_payment_verifications"], 1)
        self.assertEqual(dash1["pending_verification_total"], b_online["reservation_fee"])
        self.assertEqual(dash1["collected_reservation_total"], 0.0)

        # Customer lookup shows payment status, receipt URL, and balance due
        lookup = self.client.get(
            f"/api/bookings/lookup?code={b_online['booking_code']}&phone=3333"
        ).get_json()["booking"]
        self.assertEqual(lookup["payment_status"], "submitted")
        self.assertEqual(lookup["balance_due"], b_online["balance_due"])
        self.assertEqual(lookup["payment_proof_url"], b_online["payment_proof_url"])

        # Admin Verifies & Confirms booking
        verified = self.client.patch(
            f"/api/admin/bookings/{b_online['id']}",
            json={"payment_status": "verified", "status": "confirmed"},
        ).get_json()["booking"]
        self.assertEqual(verified["status"], "confirmed")
        self.assertEqual(verified["payment_status"], "verified")
        self.assertEqual(verified["balance_due"], b_online["balance_due"])

        import notifications

        alert_subject, alert_body = notifications.format_new_booking_message(
            {"currency": "₱", "shop_name": "Motorbike Rentals Camiguin"},
            {"shop_name": b_online.get("shop_name", "Shop")},
            b_online,
        )
        self.assertIn(b_online["booking_code"], alert_subject)
        self.assertIn("9001234567890", alert_body)
        self.assertIn("Balance Due at Pickup", alert_body)

        home_html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="payment-qr-section"', home_html)
        admin_html = self.client.get("/admin").get_data(as_text=True)
        self.assertIn('id="set-reservation-mode"', admin_html)
        self.assertIn('id="set-qr-image-file"', admin_html)

        dash2 = self.client.get("/api/admin/dashboard").get_json()["kpis"]
        self.assertEqual(dash2["pending_payment_verifications"], 0)
        self.assertEqual(dash2["collected_reservation_total"], b_online["reservation_fee"])

        # If payment rejected later, balance_due resets to full total_amount so shop collects all
        rejected = self.client.patch(
            f"/api/admin/bookings/{b_online['id']}",
            json={"payment_status": "rejected"},
        ).get_json()["booking"]
        self.assertEqual(rejected["payment_status"], "rejected")
        self.assertEqual(rejected["balance_due"], b_online["total_amount"])

        # Re-verifying restores net balance_due cleanly
        reverified = self.client.patch(
            f"/api/admin/bookings/{b_online['id']}",
            json={"payment_status": "verified"},
        ).get_json()["booking"]
        self.assertEqual(reverified["payment_status"], "verified")
        self.assertEqual(reverified["balance_due"], b_online["balance_due"])

    def test_legacy_db_migrates_payment_columns_and_preserves_balance_due(self):
        legacy_db = os.path.join(self.temp_dir.name, "legacy_bookings.db")
        raw_conn = sqlite3.connect(legacy_db)
        raw_conn.executescript(
            """
            CREATE TABLE shops (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                owner_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT NOT NULL,
                whatsapp_number TEXT NOT NULL DEFAULT '',
                telegram_chat_id TEXT NOT NULL DEFAULT '',
                municipality TEXT NOT NULL DEFAULT 'Mambajao',
                address TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                delivery_fee REAL NOT NULL DEFAULT 200,
                password_hash TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                is_main INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE bikes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                shop_id INTEGER NOT NULL DEFAULT 1,
                name TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                category TEXT NOT NULL,
                engine_cc INTEGER NOT NULL,
                transmission TEXT NOT NULL,
                fuel_type TEXT NOT NULL DEFAULT 'Gasoline',
                plate_number TEXT NOT NULL DEFAULT '',
                daily_rate REAL NOT NULL,
                weekly_rate REAL NOT NULL DEFAULT 0,
                deposit REAL NOT NULL DEFAULT 2000,
                units_count INTEGER NOT NULL DEFAULT 1,
                image_url TEXT NOT NULL DEFAULT '',
                inclusions TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                featured INTEGER NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'available',
                created_at TEXT NOT NULL
            );
            CREATE TABLE bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                booking_code TEXT NOT NULL UNIQUE,
                bike_id INTEGER NOT NULL,
                shop_id INTEGER NOT NULL DEFAULT 1,
                customer_name TEXT NOT NULL,
                customer_phone TEXT NOT NULL,
                customer_email TEXT NOT NULL DEFAULT '',
                license_number TEXT NOT NULL,
                pickup_date TEXT NOT NULL,
                return_date TEXT NOT NULL,
                pickup_time TEXT NOT NULL DEFAULT '09:00',
                pickup_method TEXT NOT NULL DEFAULT 'shop',
                delivery_address TEXT NOT NULL DEFAULT '',
                extra_helmet INTEGER NOT NULL DEFAULT 0,
                top_box INTEGER NOT NULL DEFAULT 0,
                rental_days INTEGER NOT NULL,
                base_subtotal REAL NOT NULL,
                addons_total REAL NOT NULL DEFAULT 0,
                delivery_total REAL NOT NULL DEFAULT 0,
                total_amount REAL NOT NULL,
                commission_rate REAL NOT NULL DEFAULT 10,
                platform_fee REAL NOT NULL DEFAULT 0,
                shop_payout REAL NOT NULL DEFAULT 0,
                deposit_amount REAL NOT NULL,
                notes TEXT NOT NULL DEFAULT '',
                admin_notes TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        raw_conn.execute(
            """
            INSERT INTO shops (id, shop_name, slug, owner_name, email, phone, password_hash, status, is_main, created_at)
            VALUES (1, 'Legacy Shop', 'legacy-shop', 'Owner', 'owner@legacy.ph', '09171234567', 'hash', 'approved', 1, '2026-01-01T00:00:00')
            """
        )
        raw_conn.execute(
            """
            INSERT INTO bikes (id, shop_id, name, slug, category, engine_cc, transmission, daily_rate, status, created_at)
            VALUES (1, 1, 'Legacy Beat 110', 'legacy-beat-110', 'Scooter', 110, 'Automatic', 500, 'available', '2026-01-01T00:00:00')
            """
        )
        raw_conn.execute(
            """
            INSERT INTO bookings (
                id, booking_code, bike_id, shop_id, customer_name, customer_phone, license_number,
                pickup_date, return_date, rental_days, base_subtotal, total_amount, deposit_amount,
                status, created_at, updated_at
            ) VALUES (1, 'MR-2026-0001', 1, 1, 'Old Rider', '09179998888', 'LIC-OLD',
                      '2026-12-01', '2026-12-04', 3, 1500, 1500, 2000, 'confirmed',
                      '2026-01-01T00:00:00', '2026-01-01T00:00:00')
            """
        )
        raw_conn.commit()
        raw_conn.close()

        migrated_app = create_app(
            {
                "TESTING": True,
                "DB_PATH": legacy_db,
                "UPLOAD_FOLDER": self.upload_dir,
                "SKIP_ICONS": True,
            }
        )
        client = migrated_app.test_client()
        self.assertEqual(client.get("/api/health").status_code, 200)

        check_conn = sqlite3.connect(legacy_db)
        cols = [r[1] for r in check_conn.execute("PRAGMA table_info(bookings)").fetchall()]
        row = check_conn.execute(
            "SELECT reservation_fee, balance_due, payment_channel, payment_status FROM bookings WHERE id = 1"
        ).fetchone()
        check_conn.close()

        for col in (
            "reservation_fee",
            "balance_due",
            "payment_channel",
            "payment_reference",
            "payment_proof_url",
            "payment_status",
        ):
            self.assertIn(col, cols)
        self.assertEqual(float(row[0]), 0.0)
        self.assertEqual(float(row[1]), 1500.0)
        self.assertEqual(row[2], "pay_at_shop")
        self.assertEqual(row[3], "unpaid")

    def test_qr_upload_accepts_jfif_and_highres_images_and_network_first_scripts(self):
        sw_text = self.client.get("/sw.js").get_data(as_text=True)
        self.assertIn("motoride-pwa-v6", sw_text)
        self.assertIn('/static/js/', sw_text)

        login_resp = self.client.post("/api/admin/login", json={"password": "admin1234"})
        self.assertEqual(login_resp.status_code, 200)
        admin_html = self.client.get("/admin").get_data(as_text=True)
        self.assertIn('/static/js/admin.js?v=6', admin_html)
        self.assertIn('.jfif', admin_html)

        # Windows/Edge/Messenger saves often use .jfif -> served cleanly as image/jpeg
        jfif_bytes = b"\xff\xd8\xff\xe0JFIF_QR_DATA"
        up_jfif = self.client.post(
            "/api/admin/settings/qr",
            data={"qr_image": (io.BytesIO(jfif_bytes), "gcash-qr.jfif")},
            content_type="multipart/form-data",
        )
        self.assertEqual(up_jfif.status_code, 200)
        jfif_url = up_jfif.get_json()["gcash_qr_url"]
        self.assertTrue(jfif_url.endswith(".jfif"))
        served = self.client.get(jfif_url)
        self.assertEqual(served.status_code, 200)
        self.assertEqual(served.mimetype, "image/jpeg")
        self.assertEqual(served.data, jfif_bytes)

        # Phone screenshots / photos above 4 MB (up to 8 MB) must upload cleanly
        large_ok = b"\x89PNG\r\n\x1a\n" + (b"0" * (5 * 1024 * 1024))
        up_large = self.client.post(
            "/api/admin/settings/qr",
            data={"qr_image": (io.BytesIO(large_ok), "highres-qr.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(up_large.status_code, 200)

        # Above 8 MB limit fails cleanly with 400 JSON error
        too_big = b"\x89PNG\r
\x1a\n" + (b"0" * (8 * 1024 * 1024 + 100))
        up_too_big = self.client.post(
            "/api/admin/settings/qr",
            data={"qr_image": (io.BytesIO(too_big), "huge-qr.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(up_too_big.status_code, 400)
        self.assertIn("8 MB", up_too_big.get_json()["error"])

if __name__ == "__main__":
    unittest.main()
