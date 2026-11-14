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


if __name__ == "__main__":
    unittest.main()
