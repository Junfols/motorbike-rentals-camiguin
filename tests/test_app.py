import base64
import io
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from unittest.mock import patch

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
        for route in ("/", "/customer", "/bookings", "/shop", "/rider", "/partner", "/admin", "/offline"):
            resp = self.client.get(route)
            self.assertEqual(resp.status_code, 200, f"Route {route} failed")
            html = resp.get_data(as_text=True)
            self.assertIn('href="/shop"', html)
            if route != "/admin":
                self.assertNotIn('href="/admin"', html)
                self.assertIn("data-admin-tap-trigger", html)
            else:
                self.assertIn('href="/admin"', html)

        with self.client.get("/static/js/pwa.js") as pwa_resp:
            pwa_js = pwa_resp.get_data(as_text=True)
        self.assertIn("ADMIN_TAP_TARGET = 10", pwa_js)
        self.assertIn('"/admin"', pwa_js)

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
        self.assertIn('"/rider"', sw_resp.get_data(as_text=True))

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

        # 8-day rental uses standard daily rate (8 * 1600 = 12800) with weekly rate savings removed
        p = self._future_str(2)
        r = self._future_str(10)
        quote_resp = self.client.get(
            f"/api/quote?bike_id={dominar['id']}&pickup_date={p}&return_date={r}"
            "&pickup_method=delivery&extra_helmet=1&top_box=1"
        )
        self.assertEqual(quote_resp.status_code, 200)
        q = quote_resp.get_json()["quote"]
        self.assertEqual(q["rental_days"], 8)
        self.assertEqual(q["base_subtotal"], 12800.0)
        self.assertEqual(q["discount_saved"], 0.0)
        self.assertEqual(q["addons_total"], 1200.0)  # (50 + 100) * 8
        self.assertEqual(q["delivery_total"], 150.0)   # Benoni Port Moto Express delivery rate
        self.assertEqual(q["total_amount"], 14150.0)
        self.assertEqual(q["commission_rate"], 0.0)
        self.assertEqual(q["platform_fee"], 0.0)
        self.assertEqual(q["shop_payout"], 14150.0)
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

        # Main Admin tries to set a commission (ignored: platform fee removed) and approves Guinsiliban Ride Hub
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
        # 2 days * 500 = 1000 + 100 shop delivery = 1100 total; no platform fee; payout = 1100
        self.assertEqual(booked["total_amount"], 1100.0)
        self.assertEqual(booked["commission_rate"], 0.0)
        self.assertEqual(booked["platform_fee"], 0.0)
        self.assertEqual(booked["shop_payout"], 1100.0)

        # Partner logs in cleanly, confirms booking, and checks KPIs + Admin dashboard totals
        self.client.post("/api/partner/logout")
        relogin = self.client.post(
            "/api/partner/login",
            json={"email": "elena@guinsilibanrides.ph", "password": "mysecret99"},
        )
        self.assertEqual(relogin.status_code, 200)

        # Admin can reset a partner shop password via PATCH /api/admin/shops/<id>
        short_pw = self.client.patch(f"/api/admin/shops/{partner_id}", json={"password": "123"})
        self.assertEqual(short_pw.status_code, 400)
        reset_pw = self.client.patch(f"/api/admin/shops/{partner_id}", json={"password": "partner1234"})
        self.assertEqual(reset_pw.status_code, 200)
        self.client.post("/api/partner/logout")
        old_login = self.client.post(
            "/api/partner/login",
            json={"email": "elena@guinsilibanrides.ph", "password": "mysecret99"},
        )
        self.assertEqual(old_login.status_code, 401)
        new_login = self.client.post(
            "/api/partner/login",
            json={"email": "elena@guinsilibanrides.ph", "password": "partner1234"},
        )
        self.assertEqual(new_login.status_code, 200)
        confirm = self.client.patch(
            f"/api/partner/bookings/{booked['id']}",
            json={"status": "confirmed", "admin_notes": "Ready for delivery"},
        )
        self.assertEqual(confirm.status_code, 200)
        self.assertFalse(confirm.get_json()["booking"]["balance_paid"])

        # Shop can mark the remaining balance as collected (e.g., customer pays everything on return)
        paid_resp = self.client.patch(
            f"/api/partner/bookings/{booked['id']}",
            json={"balance_paid": True},
        )
        self.assertEqual(paid_resp.status_code, 200)
        self.assertTrue(paid_resp.get_json()["booking"]["balance_paid"])
        self.assertEqual(paid_resp.get_json()["booking"]["status"], "confirmed")
        # Status changes keep the balance_paid flag
        active_resp = self.client.patch(
            f"/api/partner/bookings/{booked['id']}",
            json={"status": "active"},
        )
        self.assertTrue(active_resp.get_json()["booking"]["balance_paid"])
        unpaid_resp = self.client.patch(
            f"/api/partner/bookings/{booked['id']}",
            json={"balance_paid": False},
        )
        self.assertFalse(unpaid_resp.get_json()["booking"]["balance_paid"])
        bad_paid = self.client.patch(
            f"/api/partner/bookings/{booked['id']}",
            json={"status": "cancelled", "balance_paid": True},
        )
        self.assertEqual(bad_paid.status_code, 400)
        restore_resp = self.client.patch(
            f"/api/partner/bookings/{booked['id']}",
            json={"status": "confirmed"},
        )
        self.assertEqual(restore_resp.status_code, 200)
        p_dash = self.client.get("/api/partner/dashboard").get_json()
        self.assertEqual(p_dash["kpis"]["gross_revenue"], 1100.0)
        self.assertEqual(p_dash["kpis"]["platform_fee_total"], 0.0)
        self.assertEqual(p_dash["kpis"]["net_payout"], 1100.0)

        a_dash = self.client.get("/api/admin/dashboard").get_json()
        self.assertEqual(a_dash["kpis"]["platform_fee_total"], 0.0)
        self.assertEqual(a_dash["kpis"]["partner_payout_total"], 1100.0)

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
            def __init__(self, wrapper):
                self._wrapper = wrapper
                self._is_outer = False

            def __enter__(self):
                if not self._wrapper.autocommit and self._wrapper._in_implicit_tx:
                    # Simulate psycopg 3 SAVEPOINT behavior when connection already entered an implicit tx
                    self._is_outer = False
                elif self._wrapper._in_explicit_tx:
                    self._is_outer = False
                else:
                    self._is_outer = True
                    self._wrapper._in_explicit_tx = True
                return self

            def __exit__(self, exc_type, exc, tb):
                if self._is_outer:
                    self._wrapper._in_explicit_tx = False
                    if exc_type:
                        self._wrapper._raw.rollback()
                    else:
                        self._wrapper._raw.commit()
                return False

        class _FakePgConn:
            def __init__(self, path, autocommit=False):
                self.autocommit = bool(autocommit)
                self._in_implicit_tx = False
                self._in_explicit_tx = False
                self._raw = sqlite3.connect(path, timeout=15, check_same_thread=False)

            def _after_exec(self):
                if self.autocommit and not self._in_explicit_tx:
                    self._raw.commit()
                elif not self.autocommit and not self._in_explicit_tx:
                    self._in_implicit_tx = True

            def execute(self, sql, params=None):
                norm = sql.strip()
                if norm.startswith("SELECT pg_advisory_"):
                    res = _FakePgCursor(self._raw.execute("SELECT 1"))
                    self._after_exec()
                    return res
                if "information_schema.columns" in norm and params:
                    tbl = params[0]
                    cols = [(r[1],) for r in self._raw.execute(f"PRAGMA table_info({tbl})").fetchall()]
                    self._raw.execute("SELECT 1")
                    self._after_exec()
                    return type("ColsCur", (), {
                        "description": [_ColDesc("column_name")],
                        "fetchone": lambda self_: cols[0] if cols else None,
                        "fetchall": lambda self_: cols,
                    })()
                has_returning = bool(re.search(r"\bRETURNING\s+id\b", norm, re.IGNORECASE))
                sq_sql = _pg_sql_to_sqlite(sql)
                cur = self._raw.execute(sq_sql, tuple(params) if params is not None else ())
                self._after_exec()
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
                return _FakePgTx(self)

            def commit(self):
                self._in_implicit_tx = False
                self._raw.commit()

            def rollback(self):
                self._in_implicit_tx = False
                self._raw.rollback()

            def close(self):
                self._raw.rollback()
                self._raw.close()

        fake_psycopg = types.ModuleType("psycopg")
        fake_psycopg.connect = lambda url, connect_timeout=15, autocommit=False: _FakePgConn(
            pg_sim_db, autocommit=autocommit
        )

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
            created_booking = book.get_json()["booking"]
            self.assertEqual(created_booking["total_amount"], 800.0)

            # Verify shop approval persisted on fresh GET /api/shops across PG connections
            approved_shops = client.get("/api/shops").get_json()["shops"]
            self.assertEqual(len(approved_shops), 4)
            self.assertTrue(any(s["id"] == shop_id and s["status"] == "approved" for s in approved_shops))

            # Verify overlapping booking rollback works cleanly on PG with autocommit + manual tx
            overlap_pg = client.post(
                "/api/bookings",
                json={
                    "bike_id": bike["id"],
                    "customer_name": "Lito Cruz",
                    "customer_phone": "09182224444",
                    "license_number": "G01-22-001133",
                    "pickup_date": self._future_str(2),
                    "return_date": self._future_str(3),
                },
            )
            self.assertEqual(overlap_pg.status_code, 409)

            # Admin approves booking & saves alert setting; fresh requests must see committed values
            confirm_resp = client.patch(
                f"/api/admin/bookings/{created_booking['id']}",
                json={"status": "confirmed"},
            )
            self.assertEqual(confirm_resp.status_code, 200)
            self.assertEqual(confirm_resp.get_json()["booking"]["status"], "confirmed")

            lookup_after = client.get(
                f"/api/bookings/lookup?code={created_booking['booking_code']}&phone=3333"
            )
            self.assertEqual(lookup_after.status_code, 200)
            self.assertEqual(lookup_after.get_json()["booking"]["status"], "confirmed")

            save_cfg = client.put(
                "/api/admin/settings",
                json={"admin_telegram_chat_id": "555666"},
            )
            self.assertEqual(save_cfg.status_code, 200)
            read_cfg = client.get("/api/admin/settings")
            self.assertEqual(read_cfg.status_code, 200)
            self.assertEqual(read_cfg.get_json()["settings"]["admin_telegram_chat_id"], "555666")

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

        # Quote now calculates 15% reservation_fee & balance_due for 1-2 days, and flat ₱500 for 3+ days
        q_after = self.client.get(
            f"/api/quote?bike_id={bike['id']}&pickup_date={p1}&return_date={r1}"
        ).get_json()["quote"]
        self.assertTrue(q_after["reservation_configured"])
        self.assertEqual(q_after["reservation_mode"], "optional")
        self.assertEqual(q_after["reservation_percent"], 15.0)
        self.assertEqual(q_after["down_payment_rule"], "percent")
        self.assertEqual(q_after["reservation_fee"], round(q_after["total_amount"] * 0.15, 2))
        self.assertEqual(q_after["down_payment"], q_after["reservation_fee"])
        self.assertEqual(
            q_after["balance_due"],
            round(q_after["total_amount"] - q_after["reservation_fee"], 2),
        )

        p3, r3 = self._future_str(40), self._future_str(43)
        q_3days = self.client.get(
            f"/api/quote?bike_id={bike['id']}&pickup_date={p3}&return_date={r3}"
        ).get_json()["quote"]
        self.assertEqual(q_3days["rental_days"], 3)
        self.assertEqual(q_3days["down_payment_rule"], "flat_500")
        self.assertEqual(q_3days["reservation_fee"], 500.0)
        self.assertEqual(q_3days["down_payment"], 500.0)
        self.assertEqual(
            q_3days["balance_due"],
            round(q_3days["total_amount"] - 500.0, 2),
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

        # Admin can mark the shop balance as collected / uncollected; defaults to unpaid
        self.assertFalse(b_shop["balance_paid"])
        admin_paid = self.client.patch(
            f"/api/admin/bookings/{b_shop['id']}",
            json={"balance_paid": True},
        )
        self.assertEqual(admin_paid.status_code, 200)
        self.assertTrue(admin_paid.get_json()["booking"]["balance_paid"])
        admin_unpaid = self.client.patch(
            f"/api/admin/bookings/{b_shop['id']}",
            json={"balance_paid": False},
        )
        self.assertFalse(admin_unpaid.get_json()["booking"]["balance_paid"])

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
        with self.client.get("/sw.js") as sw_resp:
            sw_text = sw_resp.get_data(as_text=True)
        self.assertIn("motoride-pwa-v18", sw_text)
        self.assertIn('/static/js/', sw_text)

        login_resp = self.client.post("/api/admin/login", json={"password": "admin1234"})
        self.assertEqual(login_resp.status_code, 200)
        admin_html = self.client.get("/admin").get_data(as_text=True)
        self.assertIn('/static/js/admin.js?v=18', admin_html)
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
        too_big = b"\x89PNG\r\n\x1a\n" + (b"0" * (8 * 1024 * 1024 + 100))
        up_too_big = self.client.post(
            "/api/admin/settings/qr",
            data={"qr_image": (io.BytesIO(too_big), "huge-qr.png")},
            content_type="multipart/form-data",
        )
        self.assertEqual(up_too_big.status_code, 400)
        self.assertIn("8 MB", up_too_big.get_json()["error"])

    def test_return_date_defaults_to_select_date_prompt_without_prefill(self):
        index_html = self.client.get("/").get_data(as_text=True)
        self.assertIn('/static/css/style.css?v=18', index_html)
        self.assertIn('/static/js/storefront.js?v=18', index_html)
        self.assertIn('class="bike-card"', index_html)
        self.assertNotIn('<div class="loading-state">Loading motorbikes...</div>', index_html)
        self.assertIn('id="modal-availability-calendar"', index_html)
        self.assertIn('id="modal-next-available-btn"', index_html)
        self.assertEqual(index_html.count('<span class="date-placeholder" aria-hidden="true">Select date</span>'), 2)
        self.assertIn('id="search-return-date"', index_html)
        self.assertIn('id="booking-return-date"', index_html)

        with self.client.get("/static/js/storefront.js") as sf_resp:
            storefront_js = sf_resp.get_data(as_text=True)
        self.assertIn('state.returnDate = "";', storefront_js)
        self.assertIn("bindDatePickerPlaceholder(searchReturnInput);", storefront_js)
        self.assertIn("bindDatePickerPlaceholder(bookingReturn);", storefront_js)
        self.assertIn("Select a return date above to check availability & total price.", storefront_js)
        self.assertIn("renderAvailabilityCalendarHtml", storefront_js)
        self.assertNotIn("today.getDate() + 2", storefront_js)

        with self.client.get("/static/css/style.css") as css_resp:
            style_css = css_resp.get_data(as_text=True)
        self.assertIn(".date-input-wrap.is-empty .date-placeholder", style_css)
        self.assertIn(".quote-availability.muted", style_css)
        self.assertIn(".avail-cal-grid", style_css)

    def test_availability_calendar_booked_dates_and_sweep_line_concurrency(self):
        self.assertEqual(
            self.client.post("/api/admin/login", json={"password": "admin1234"}).status_code,
            200,
        )
        # Create a 2-unit bike so we can verify limited vs booked & non-overlapping concurrency
        create_bike = self.client.post(
            "/api/admin/bikes",
            json={
                "shop_id": 1,
                "name": "Honda PCX 160 Multi",
                "category": "Scooter",
                "engine_cc": 160,
                "transmission": "Automatic",
                "daily_rate": 700,
                "weekly_rate": 4200,
                "deposit": 1500,
                "units_count": 2,
                "status": "available",
            },
        )
        self.assertEqual(create_bike.status_code, 201)
        bike_id = create_bike.get_json()["bike"]["id"]

        d2 = self._future_str(2)
        d3 = self._future_str(3)
        d4 = self._future_str(4)
        d5 = self._future_str(5)
        d6 = self._future_str(6)

        # Two DISJOINT 1-unit bookings across [d2, d6] have peak concurrency 1 (< 2 units)
        for p_dt, r_dt, cname in ((d2, d3, "Rider One"), (d5, d6, "Rider Two")):
            res = self.client.post(
                "/api/bookings",
                json={
                    "bike_id": bike_id,
                    "customer_name": cname,
                    "customer_phone": "09171112200",
                    "license_number": "L01-11-111111",
                    "pickup_date": p_dt,
                    "return_date": r_dt,
                },
            )
            self.assertEqual(res.status_code, 201)

        # Another unit is STILL open across the full [d2, d6] window because peak is 1 of 2
        res_full = self.client.post(
            "/api/bookings",
            json={
                "bike_id": bike_id,
                "customer_name": "Rider Three",
                "customer_phone": "09171112201",
                "license_number": "L01-11-222222",
                "pickup_date": d2,
                "return_date": d6,
            },
        )
        self.assertEqual(res_full.status_code, 201)

        # Now d2..d3 and d5..d6 have 2/2 units booked, while d4 has only 1/2 unit booked (limited/open)
        blocked_d2_d3 = self.client.post(
            "/api/bookings",
            json={
                "bike_id": bike_id,
                "customer_name": "Rider Four",
                "customer_phone": "09171112202",
                "license_number": "L01-11-333333",
                "pickup_date": d2,
                "return_date": d3,
            },
        )
        self.assertEqual(blocked_d2_d3.status_code, 409)

        # Searching without explicit return_date succeeds (uses pickup_date)
        list_no_ret = self.client.get(f"/api/bikes?pickup_date={d2}")
        self.assertEqual(list_no_ret.status_code, 200)
        target_no_ret = next(b for b in list_no_ret.get_json()["bikes"] if b["id"] == bike_id)
        self.assertFalse(target_no_ret["is_available"])
        self.assertEqual(target_no_ret["next_available_date"], d4)
        self.assertIsNone(target_no_ret["next_available_return_date"])

        # Searching d2..d3 jumps to next 2-day window starting after booked spans (d7..d8)
        list_with_ret = self.client.get(f"/api/bikes?pickup_date={d2}&return_date={d3}")
        self.assertEqual(list_with_ret.status_code, 200)
        target_with_ret = next(b for b in list_with_ret.get_json()["bikes"] if b["id"] == bike_id)
        self.assertFalse(target_with_ret["is_available"])
        self.assertEqual(
            target_with_ret["booked_ranges"],
            [
                {"pickup_date": d2, "return_date": d3},
                {"pickup_date": d5, "return_date": d6},
            ],
        )
        self.assertEqual(target_with_ret["next_available_date"], self._future_str(7))
        self.assertEqual(target_with_ret["next_available_return_date"], self._future_str(8))

        # Bike detail endpoint returns 35-day availability_calendar with open/limited/booked states
        detail = self.client.get(f"/api/bikes/{bike_id}?pickup_date={d2}&return_date={d3}").get_json()["bike"]
        cal = detail["availability_calendar"]
        self.assertEqual(len(cal), 35)
        cal_by_date = {c["date"]: c for c in cal}
        self.assertEqual(cal_by_date[d2]["status"], "booked")
        self.assertEqual(cal_by_date[d2]["available_units"], 0)
        self.assertEqual(cal_by_date[d4]["status"], "limited")
        self.assertEqual(cal_by_date[d4]["available_units"], 1)
        self.assertEqual(cal_by_date[self._future_str(7)]["status"], "available")
        self.assertEqual(cal_by_date[self._future_str(7)]["available_units"], 2)

    def test_partner_and_admin_quick_status_and_manual_date_blocks(self):
        # Register & approve a new partner shop with a 2-unit bike
        reg = self.client.post(
            "/api/partner/register",
            json={
                "shop_name": "Mambajao Moto Hub",
                "owner_name": "Carlos Reyes",
                "email": "carlos@mambajaomoto.ph",
                "phone": "09178889900",
                "municipality": "Mambajao",
                "address": "Rizal St, Mambajao",
                "delivery_fee": 150,
                "password": "partnerpass123",
            },
        )
        self.assertEqual(reg.status_code, 201)
        shop_id = reg.get_json()["shop"]["id"]
        bike_resp = self.client.post(
            "/api/partner/bikes",
            json={
                "name": "Yamaha Mio Aerox",
                "category": "Scooter",
                "engine_cc": 155,
                "transmission": "Automatic",
                "daily_rate": 600,
                "weekly_rate": 3600,
                "deposit": 1500,
                "units_count": 2,
                "status": "available",
            },
        )
        self.assertEqual(bike_resp.status_code, 201)
        bike_id = bike_resp.get_json()["bike"]["id"]

        # Admin approves shop
        self.assertEqual(
            self.client.post("/api/admin/login", json={"password": "admin1234"}).status_code,
            200,
        )
        self.assertEqual(
            self.client.patch(f"/api/admin/shops/{shop_id}", json={"status": "approved"}).status_code,
            200,
        )

        # Partner logs back in
        self.assertEqual(
            self.client.post(
                "/api/partner/login",
                json={"email": "carlos@mambajaomoto.ph", "password": "partnerpass123"},
            ).status_code,
            200,
        )

        d1 = self._future_str(1)
        d2 = self._future_str(2)
        d4 = self._future_str(4)
        d5 = self._future_str(5)

        # 1) Partner toggles bike status quickly -> maintenance -> back to available
        st_maint = self.client.patch(f"/api/partner/bikes/{bike_id}/status", json={"status": "maintenance"})
        self.assertEqual(st_maint.status_code, 200)
        self.assertEqual(st_maint.get_json()["bike"]["status"], "maintenance")
        quote_maint = self.client.get(f"/api/quote?bike_id={bike_id}&pickup_date={d1}&return_date={d2}").get_json()["quote"]
        self.assertFalse(quote_maint["is_available"])

        st_open = self.client.patch(f"/api/partner/bikes/{bike_id}/status", json={"status": "available"})
        self.assertEqual(st_open.status_code, 200)
        self.assertEqual(st_open.get_json()["bike"]["status"], "available")

        # 2) Partner blocks all 2 units for a walk-in customer on [d1, d2]
        blk_resp = self.client.post(
            f"/api/partner/bikes/{bike_id}/blocks",
            json={
                "start_date": d1,
                "end_date": d2,
                "units_blocked": 2,
                "reason": "Walk-in Tourist",
            },
        )
        self.assertEqual(blk_resp.status_code, 201)
        blk_data = blk_resp.get_json()["bike"]
        blk_id = blk_data["blocks"][0]["id"]
        self.assertEqual(blk_data["booked_ranges"], [{"pickup_date": d1, "return_date": d2}])

        # Attempting to double-block the same dates must fail with 409
        dup_blk = self.client.post(
            f"/api/partner/bikes/{bike_id}/blocks",
            json={"start_date": d1, "end_date": d2, "units_blocked": 1, "reason": "Overflow"},
        )
        self.assertEqual(dup_blk.status_code, 409)

        # Online customer trying to book [d1, d2] is blocked (409), and KPI revenue remains 0
        online_blocked = self.client.post(
            "/api/bookings",
            json={
                "bike_id": bike_id,
                "customer_name": "Web Tourist",
                "customer_phone": "09172223344",
                "license_number": "A01-22-334455",
                "pickup_date": d1,
                "return_date": d2,
            },
        )
        self.assertEqual(online_blocked.status_code, 409)
        dash = self.client.get("/api/partner/dashboard").get_json()
        self.assertEqual(dash["kpis"]["pending_count"], 0)
        self.assertEqual(dash["kpis"]["gross_revenue"], 0.0)

        # Schedule endpoint lists block + 35-day calendar
        sched = self.client.get(f"/api/partner/bikes/{bike_id}/blocks").get_json()["bike"]
        self.assertEqual(len(sched["blocks"]), 1)
        self.assertEqual(len(sched["availability_calendar"]), 35)

        # 3) Partner unblocks walk-in dates -> dates become bookable again
        unblk = self.client.delete(f"/api/partner/bikes/{bike_id}/blocks/{blk_id}")
        self.assertEqual(unblk.status_code, 200)
        self.assertEqual(unblk.get_json()["bike"]["blocks"], [])
        online_ok = self.client.post(
            "/api/bookings",
            json={
                "bike_id": bike_id,
                "customer_name": "Web Tourist",
                "customer_phone": "09172223344",
                "license_number": "A01-22-334455",
                "pickup_date": d1,
                "return_date": d2,
            },
        )
        self.assertEqual(online_ok.status_code, 201)

        # 4) Admin blocks [d4, d5], verifies templates expose controls, then deletes bike & cleans blocks
        admin_blk = self.client.post(
            f"/api/admin/bikes/{bike_id}/blocks",
            json={"start_date": d4, "end_date": d5, "units_blocked": 1, "reason": "Admin Hold"},
        )
        self.assertEqual(admin_blk.status_code, 201)

        partner_html = self.client.get("/partner").get_data(as_text=True)
        self.assertIn('id="bike-schedule-modal"', partner_html)
        self.assertIn('/static/js/partner.js?v=18', partner_html)
        admin_html = self.client.get("/admin").get_data(as_text=True)
        self.assertIn('id="bike-schedule-modal"', admin_html)

        # Bike with booking history cannot be deleted (existing safeguard)
        blocked_delete = self.client.delete(f"/api/admin/bikes/{bike_id}")
        self.assertEqual(blocked_delete.status_code, 409)

        # A bike without bookings but with a manual block can be deleted; blocks are cleaned up
        spare = self.client.post(
            "/api/admin/bikes",
            json={
                "shop_id": shop_id,
                "name": "Spare Scooter",
                "category": "Scooter",
                "engine_cc": 110,
                "transmission": "Automatic",
                "daily_rate": 400,
                "deposit": 1500,
                "units_count": 1,
                "status": "available",
            },
        )
        self.assertEqual(spare.status_code, 201)
        spare_id = spare.get_json()["bike"]["id"]
        spare_blk = self.client.post(
            f"/api/admin/bikes/{spare_id}/blocks",
            json={"start_date": d4, "end_date": d5, "units_blocked": 1},
        )
        self.assertEqual(spare_blk.status_code, 201)
        del_bike = self.client.delete(f"/api/admin/bikes/{spare_id}")
        self.assertEqual(del_bike.status_code, 200)
        self.assertEqual(self.client.get(f"/api/admin/bikes/{spare_id}/blocks").status_code, 404)

    def test_set_rafols_as_main_hub_via_migration_and_admin_patch(self):
        self.assertEqual(
            self.client.post("/api/admin/login", json={"password": "admin1234"}).status_code,
            200,
        )
        # Create RAFOLS MOTORBIKE RENTAL shop
        create_rafols = self.client.post(
            "/api/admin/shops",
            json={
                "shop_name": "RAFOLS MOTORBIKE RENTAL",
                "owner_name": "Jun Rafols",
                "email": "rafols@camiguin.ph",
                "phone": "09564596949",
                "municipality": "Mambajao",
                "address": "Mambajao, Camiguin",
                "delivery_fee": 200,
                "status": "approved",
            },
        )
        self.assertEqual(create_rafols.status_code, 201)
        rafols_id = create_rafols.get_json()["shop"]["id"]
        self.assertFalse(create_rafols.get_json()["shop"]["is_main"])

        # Running init_db clears legacy is_main flags so all shops are equal and resets Rafols password once
        from db import init_db
        init_db(self.db_path)

        shops = self.client.get("/api/admin/shops?status=all").get_json()["shops"]
        by_id = {s["id"]: s for s in shops}
        self.assertFalse(by_id[rafols_id]["is_main"])
        self.assertFalse(by_id[1]["is_main"])

        # Any shop (including id=1 and RAFOLS) can now be suspended, re-approved, or deleted
        susp_old = self.client.patch("/api/admin/shops/1", json={"status": "suspended"})
        self.assertEqual(susp_old.status_code, 200)
        self.assertEqual(susp_old.get_json()["shop"]["status"], "suspended")

        susp_rafols = self.client.patch(f"/api/admin/shops/{rafols_id}", json={"status": "suspended"})
        self.assertEqual(susp_rafols.status_code, 200)
        self.assertEqual(susp_rafols.get_json()["shop"]["status"], "suspended")

        approve_rafols = self.client.patch(f"/api/admin/shops/{rafols_id}", json={"status": "approved"})
        self.assertEqual(approve_rafols.status_code, 200)
        self.assertEqual(approve_rafols.get_json()["shop"]["status"], "approved")

        # Admin can delete any partner shop even if it has bikes and bookings/blocks
        self.client.post(
            "/api/admin/bikes/1/blocks",
            json={"start_date": "2026-07-01", "end_date": "2026-07-03", "reason": "Walk-in test"},
        )
        del_shop = self.client.delete("/api/admin/shops/1")
        self.assertEqual(del_shop.status_code, 200)
        del_payload = del_shop.get_json()
        self.assertTrue(del_payload["deleted"])
        self.assertGreaterEqual(del_payload["deleted_bikes"], 2)
        remaining_shop_ids = [s["id"] for s in self.client.get("/api/admin/shops").get_json()["shops"]]
        self.assertNotIn(1, remaining_shop_ids)
        remaining_bike_shop_ids = {b["shop_id"] for b in self.client.get("/api/admin/bikes").get_json()["bikes"]}
        self.assertNotIn(1, remaining_bike_shop_ids)
        pub_settings = self.client.get("/api/settings").get_json()["settings"]
        self.assertEqual(pub_settings["reservation_mode"], "required")

        # Production init_db (seed_demo=False) purges remaining demo starter shops and keeps real shops
        init_db(self.db_path, seed_demo=False)
        prod_shops = self.client.get("/api/admin/shops?status=all").get_json()["shops"]
        self.assertEqual([s["id"] for s in prod_shops], [rafols_id])

        # Deleting the last shop and re-running init_db leaves partner shops completely empty (no re-seeding)
        self.assertEqual(self.client.delete(f"/api/admin/shops/{rafols_id}").status_code, 200)
        init_db(self.db_path, seed_demo=True)
        init_db(self.db_path, seed_demo=False)
        self.assertEqual(self.client.get("/api/admin/shops?status=all").get_json()["shops"], [])
        self.assertEqual(self.client.get("/api/shops").get_json()["shops"], [])
        self.assertEqual(self.client.get("/api/bikes").get_json()["bikes"], [])

    def test_partner_profile_picture_cover_photo_and_facebook_share_link(self):
        # Register & approve a partner shop, then add a bike
        reg = self.client.post(
            "/api/partner/register",
            json={
                "shop_name": "White Island Moto Rentals",
                "owner_name": "Marco Dizon",
                "email": "marco@whiteislandmoto.ph",
                "phone": "09178889900",
                "municipality": "Mambajao",
                "address": "Yumbing Port Road, Mambajao",
                "description": "Best scooters right across White Island ferry terminal.",
                "delivery_fee": 150,
                "password": "partner1234",
            },
        )
        self.assertEqual(reg.status_code, 201)
        shop_initial = reg.get_json()["shop"]
        self.assertEqual(shop_initial["logo_url"], "")
        self.assertEqual(shop_initial["cover_url"], "")
        self.assertEqual(shop_initial["share_url"], f"/shop/{shop_initial['slug']}")

        self.client.post("/api/admin/login", json={"password": "admin1234"})
        self.client.patch(f"/api/admin/shops/{shop_initial['id']}", json={"status": "approved"})
        self.client.post(
            "/api/partner/bikes",
            json={
                "name": "Honda ADV 160 White Island",
                "category": "Adventure",
                "engine_cc": 160,
                "transmission": "Automatic",
                "daily_rate": 650,
                "deposit": 1500,
                "units_count": 2,
                "status": "available",
            },
        )

        # Upload profile picture and cover photo via /api/partner/profile/media
        fake_logo = io.BytesIO(b"\x89PNG\r\n\x1a\nlogo-image-bytes")
        fake_cover = io.BytesIO(b"\x89PNG\r\n\x1a\ncover-image-bytes")
        media_resp = self.client.post(
            "/api/partner/profile/media",
            data={
                "logo_image": (fake_logo, "partner_logo.png"),
                "cover_image": (fake_cover, "partner_cover.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(media_resp.status_code, 200)
        shop_after = media_resp.get_json()["shop"]
        self.assertTrue(shop_after["logo_url"].startswith("/uploads/shop_logo_"))
        self.assertTrue(shop_after["cover_url"].startswith("/uploads/shop_cover_"))

        # Uploaded logo & cover are served from DB-backed /uploads/<filename>
        logo_get = self.client.get(shop_after["logo_url"])
        self.assertEqual(logo_get.status_code, 200)
        self.assertEqual(logo_get.data, b"\x89PNG\r\n\x1a\nlogo-image-bytes")
        cover_get = self.client.get(shop_after["cover_url"])
        self.assertEqual(cover_get.status_code, 200)
        self.assertEqual(cover_get.data, b"\x89PNG\r\n\x1a\ncover-image-bytes")

        # Public shareable link /shop/<slug> renders Open Graph tags with the shop's cover photo & name
        slug = shop_after["slug"]
        shop_page = self.client.get(f"/shop/{slug}")
        self.assertEqual(shop_page.status_code, 200)
        html = shop_page.get_data(as_text=True)
        self.assertIn(f'<meta property="og:title" content="{shop_after["shop_name"]}', html)
        self.assertIn(shop_after["cover_url"], html)
        self.assertIn(f'/shop/{slug}', html)
        self.assertIn("window.INITIAL_FEATURED_SHOP", html)

        # Public API /api/shops/<slug> and /api/bikes include shop_logo_url and shop_cover_url
        pub_shop_api = self.client.get(f"/api/shops/{slug}")
        self.assertEqual(pub_shop_api.status_code, 200)
        self.assertEqual(pub_shop_api.get_json()["shop"]["logo_url"], shop_after["logo_url"])
        self.assertEqual(pub_shop_api.get_json()["shop"]["cover_url"], shop_after["cover_url"])

        bikes_api = self.client.get(f"/api/bikes?shop_id={shop_after['id']}").get_json()["bikes"]
        self.assertTrue(len(bikes_api) >= 1)
        self.assertEqual(bikes_api[0]["shop_logo_url"], shop_after["logo_url"])
        self.assertEqual(bikes_api[0]["shop_cover_url"], shop_after["cover_url"])

        # Clear logo & cover and verify old uploaded_media rows are cleaned up
        old_logo_url = shop_after["logo_url"]
        old_cover_url = shop_after["cover_url"]
        clear_resp = self.client.post(
            "/api/partner/profile/media",
            data={"clear_logo": "1", "clear_cover": "1"},
        )
        self.assertEqual(clear_resp.status_code, 200)
        cleared_shop = clear_resp.get_json()["shop"]
        self.assertEqual(cleared_shop["logo_url"], "")
        self.assertEqual(cleared_shop["cover_url"], "")
        self.assertEqual(self.client.get(old_logo_url).status_code, 404)
        self.assertEqual(self.client.get(old_cover_url).status_code, 404)

        # Verify default contract terms and custom shop contract terms
        self.assertIn("2,000.00 minimum fee for any crash", cleared_shop["contract_terms"])
        custom_terms = "MINIMUM CHARGE:\n• ₱2,500.00 crash minimum\n• ₱1,200.00 helmet loss"
        update_contract = self.client.put(
            "/api/partner/profile",
            json={"contract_terms": custom_terms},
        )
        self.assertEqual(update_contract.status_code, 200)
        self.assertEqual(update_contract.get_json()["shop"]["contract_terms"], custom_terms)
        bikes_after_contract = self.client.get(f"/api/bikes?shop_id={shop_after['id']}").get_json()["bikes"]
        self.assertEqual(bikes_after_contract[0]["shop_contract_terms"], custom_terms)

    def test_paymongo_settings_and_booking_link_and_webhook_auto_confirm(self):
        # 1. Admin login and save PayMongo credentials
        login_resp = self.client.post("/api/admin/login", json={"password": "admin1234"})
        self.assertEqual(login_resp.status_code, 200)

        put_resp = self.client.put(
            "/api/admin/settings",
            json={
                "paymongo_secret_key": "sk_test_mocksecretkey123456",
                "paymongo_public_key": "pk_test_mockpublickey123456",
                "paymongo_webhook_secret": "whsk_mockwebhooksecret123",
            },
        )
        self.assertEqual(put_resp.status_code, 200)
        settings = put_resp.get_json()["settings"]
        self.assertTrue(settings["has_paymongo_secret_key"])
        self.assertTrue(settings["has_paymongo_webhook_secret"])
        self.assertEqual(settings["paymongo_public_key"], "pk_test_mockpublickey123456")

        # 2. Customer creates booking with payment_channel="paymongo"
        bike_row = self.client.get("/api/bikes").get_json()["bikes"][0]
        bike_id = bike_row["id"]
        p_date = self._future_str(5)
        r_date = self._future_str(7)

        mock_link = {
            "link_id": "link_test_abc123",
            "checkout_url": "https://pm.link/pay/testabc123",
            "status": "unpaid",
            "amount": 10000,
        }

        with patch("app.create_payment_link", return_value=(True, mock_link)):
            booking_resp = self.client.post(
                "/api/bookings",
                json={
                    "bike_id": bike_id,
                    "pickup_date": p_date,
                    "return_date": r_date,
                    "customer_name": "Maria Santos",
                    "customer_phone": "09179876543",
                    "license_number": "N01-99-888888",
                    "payment_channel": "paymongo",
                },
            )
        self.assertEqual(booking_resp.status_code, 201)
        booking_data = booking_resp.get_json()["booking"]
        self.assertEqual(booking_data["payment_channel"], "paymongo")
        self.assertEqual(booking_data["payment_status"], "unpaid")
        self.assertEqual(booking_data["payment_link_id"], "link_test_abc123")
        self.assertEqual(booking_data["payment_checkout_url"], "https://pm.link/pay/testabc123")
        self.assertEqual(booking_resp.get_json()["checkout_url"], "https://pm.link/pay/testabc123")

        booking_id = booking_data["id"]
        booking_code = booking_data["booking_code"]

        # 3. Simulate PayMongo Webhook call (link.payment.paid)
        raw_event = {
            "data": {
                "id": "evt_test_123",
                "type": "event",
                "attributes": {
                    "type": "link.payment.paid",
                    "data": {
                        "id": "link_test_abc123",
                        "type": "link",
                        "attributes": {
                            "amount": 10000,
                            "remarks": booking_code,
                            "payments": [
                                {
                                    "id": "pay_test_999888",
                                    "attributes": {
                                        "status": "paid",
                                        "amount": 10000,
                                        "fee": 250,
                                        "net_amount": 9750,
                                    },
                                }
                            ],
                        },
                    },
                },
            }
        }
        raw_payload = json.dumps(raw_event).encode("utf-8")

        with patch("app.verify_webhook_signature", return_value=True):
            wh_resp = self.client.post(
                "/api/webhooks/paymongo",
                data=raw_payload,
                headers={"Paymongo-Signature": "t=12345,te=sig,li=sig"},
                content_type="application/json",
            )
        self.assertEqual(wh_resp.status_code, 200)
        self.assertTrue(wh_resp.get_json().get("verified"))

        # Verify booking in database is confirmed and verified
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        saved = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
        self.assertEqual(saved["status"], "confirmed")
        self.assertEqual(saved["payment_status"], "verified")
        self.assertEqual(saved["payment_reference"], "pay_test_999888")
        conn.close()

        # 4. Test PayMongo Sync endpoint
        sync_resp = self.client.get(f"/api/bookings/{booking_id}/paymongo-sync")
        self.assertEqual(sync_resp.status_code, 200)
        self.assertEqual(sync_resp.get_json()["status"], "already_verified")

    def test_delivery_map_pinning_and_navigation_link(self):
        bike_row = self.client.get("/api/bikes").get_json()["bikes"][0]
        bike_id = bike_row["id"]
        p_date = self._future_str(3)
        r_date = self._future_str(5)

        booking_resp = self.client.post(
            "/api/bookings",
            json={
                "bike_id": bike_id,
                "pickup_date": p_date,
                "return_date": r_date,
                "customer_name": "Juan Tourist",
                "customer_phone": "09171234567",
                "license_number": "D01-22-334455",
                "pickup_method": "delivery",
                "delivery_address": "Paras Beach Resort, Yumbing, Camiguin",
                "delivery_lat": 9.2553,
                "delivery_lng": 124.6468,
            },
        )
        self.assertEqual(booking_resp.status_code, 201)
        booking = booking_resp.get_json()["booking"]
        self.assertEqual(booking["pickup_method"], "delivery")
        self.assertEqual(booking["delivery_address"], "Paras Beach Resort, Yumbing, Camiguin")
        self.assertEqual(booking["delivery_lat"], 9.2553)
        self.assertEqual(booking["delivery_lng"], 124.6468)
        self.assertIn("https://www.google.com/maps/dir/?api=1&destination=9.2553,124.6468", booking["google_maps_url"])

        # Check lookup booking includes delivery lat/lng & maps link
        lookup_resp = self.client.get(
            f"/api/bookings/lookup?code={booking['booking_code']}&phone=09171234567"
        )
        self.assertEqual(lookup_resp.status_code, 200)
        lookup_booking = lookup_resp.get_json()["booking"]
        self.assertEqual(lookup_booking["delivery_lat"], 9.2553)
        self.assertEqual(lookup_booking["delivery_lng"], 124.6468)
        self.assertEqual(lookup_booking["google_maps_url"], booking["google_maps_url"])

        # Check index html contains homepage tourist map section
        index_html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="tourist-map"', index_html)
        self.assertIn('id="homepage-map"', index_html)
        self.assertIn('Camiguin Tourist &amp; Delivery Map', index_html)
        self.assertIn('Island Map 🗺️', index_html)

    def test_digital_contract_route_guide_and_reviews(self):
        # 1. Test homepage features: Route Guide & Verified Reviews
        index_html = self.client.get("/").get_data(as_text=True)
        self.assertIn('id="island-guide"', index_html)
        self.assertIn('Where to Go in Camiguin &amp; Best Bike Match', index_html)
        self.assertIn('Circumferential Highway Scenic Tour', index_html)
        self.assertIn('Katibawasan &amp; Tuasan Mountain Ascent', index_html)
        self.assertIn('Cross-Island Trans-Mountain Highway', index_html)
        self.assertIn('Mantigue Island &amp; East Coast Trail', index_html)
        self.assertIn('id="reviews-section"', index_html)
        self.assertIn('Verified Tourist Reviews', index_html)
        self.assertIn('bike-rating-pill', index_html)
        self.assertIn('id="booking-customer-address"', index_html)
        self.assertNotIn('id="modal-deposit-rate"', index_html)

        # 2. Test booking with Digital Contract, License Upload, and E-Signature
        png_1x1 = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        sig_data_b64 = "data:image/png;base64," + base64.b64encode(png_1x1).decode("ascii")

        booking_payload = {
            "bike_id": 1,
            "customer_name": "Maria Tourist",
            "customer_phone": "09187654321",
            "customer_email": "maria@tourist.ph",
            "customer_address": "Cagayan de Oro City",
            "license_number": "D02-24-998877",
            "pickup_date": self._future_str(2),
            "return_date": self._future_str(4),
            "pickup_time": "09:00",
            "pickup_method": "shop",
            "payment_channel": "pay_at_shop",
            "contract_agreed": "1",
            "signature_data": sig_data_b64,
            "license_photo": (io.BytesIO(png_1x1), "license_photo.png"),
        }

        booking_resp = self.client.post(
            "/api/bookings",
            data=booking_payload,
            content_type="multipart/form-data",
        )
        self.assertEqual(booking_resp.status_code, 201)
        booking = booking_resp.get_json()["booking"]
        self.assertEqual(booking["customer_address"], "Cagayan de Oro City")
        self.assertTrue(booking["contract_agreed"])
        self.assertIsNotNone(booking["contract_signed_at"])
        self.assertIsNotNone(booking["license_photo_url"])
        self.assertIsNotNone(booking["signature_url"])

        # Check lookup includes contract details
        lookup_resp = self.client.get(
            f"/api/bookings/lookup?code={booking['booking_code']}&phone=09187654321"
        )
        self.assertEqual(lookup_resp.status_code, 200)
        lookup_booking = lookup_resp.get_json()["booking"]
        self.assertEqual(lookup_booking["customer_address"], "Cagayan de Oro City")
        self.assertTrue(lookup_booking["contract_agreed"])
        self.assertEqual(lookup_booking["license_photo_url"], booking["license_photo_url"])
        self.assertEqual(lookup_booking["signature_url"], booking["signature_url"])

        # 3. Test Reviews API
        rev_post = self.client.post(
            "/api/reviews",
            json={
                "bike_id": 1,
                "booking_code": booking["booking_code"],
                "customer_name": "Maria Tourist",
                "rating": 5,
                "comment": "Had an unforgettable time exploring Camiguin! The Click 125 was very economical and handled the island road beautifully.",
            },
        )
        self.assertEqual(rev_post.status_code, 201)
        rev_data = rev_post.get_json()
        self.assertTrue(rev_data["success"])
        self.assertEqual(rev_data["review"]["rating"], 5)

        # Test GET /api/reviews
        get_revs = self.client.get("/api/reviews")
        self.assertEqual(get_revs.status_code, 200)
        revs_list = get_revs.get_json()["reviews"]
        self.assertTrue(len(revs_list) >= 1)

        # Test GET /api/bikes/1 includes reviews and rating stats
        bike_resp = self.client.get("/api/bikes/1")
        self.assertEqual(bike_resp.status_code, 200)
        bike_data = bike_resp.get_json()["bike"]
        self.assertIn("rating_avg", bike_data)
        self.assertIn("rating_count", bike_data)
        self.assertIn("reviews", bike_data)
        self.assertTrue(len(bike_data["reviews"]) >= 1)

        # Test shop reviews and rating stats
        shop_resp = self.client.get("/api/shops")
        self.assertEqual(shop_resp.status_code, 200)
        shops = shop_resp.get_json()["shops"]
        self.assertTrue(len(shops) >= 1)
        self.assertIn("rating_avg", shops[0])
        self.assertIn("review_count", shops[0])

        shop_id = bike_data.get("shop_id") or shops[0]["id"]
        shop_revs_resp = self.client.get(f"/api/reviews/shop/{shop_id}")
        self.assertEqual(shop_revs_resp.status_code, 200)
        shop_rev_data = shop_revs_resp.get_json()
        self.assertIn("reviews", shop_rev_data)
        self.assertIn("stats", shop_rev_data)
        self.assertTrue(len(shop_rev_data["reviews"]) >= 1)

        # Test printable contract and receipt page
        code = booking["booking_code"]
        # Unauthorized without phone -> redirects to /customer?code=...
        anon_resp = self.client.get(f"/bookings/{code}/contract")
        self.assertEqual(anon_resp.status_code, 302)
        self.assertIn("/customer?code=", anon_resp.headers.get("Location", ""))

        # Authorized customer with phone
        cust_contract = self.client.get(f"/bookings/{code}/contract?phone=09187654321")
        self.assertEqual(cust_contract.status_code, 200)
        html = cust_contract.get_data(as_text=True)
        self.assertIn("OFFICIAL RENTAL CONTRACT", html)
        self.assertIn(code, html)
        self.assertIn("Maria Tourist", html)
        self.assertIn("window.print()", html)

        # Authorized admin
        self.assertEqual(
            self.client.post("/api/admin/login", json={"password": "admin1234"}).status_code,
            200,
        )
        admin_contract = self.client.get(f"/bookings/{code}/contract")
        self.assertEqual(admin_contract.status_code, 200)
        self.assertIn("OFFICIAL RENTAL CONTRACT", admin_contract.get_data(as_text=True))

    def test_in_app_voice_call_signaling(self):
        bike = self.client.get("/api/bikes").get_json()["bikes"][0]
        booking = self.client.post(
            "/api/bookings",
            json={
                "bike_id": bike["id"],
                "customer_name": "Maria Santos",
                "customer_phone": "+63 917 555 7788",
                "customer_email": "maria@example.com",
                "license_number": "G01-55-123456",
                "pickup_date": self._future_str(10),
                "return_date": self._future_str(11),
                "pickup_time": "09:00",
                "pickup_method": "shop",
            },
        ).get_json()["booking"]
        code = booking["booking_code"]
        phone = "09175557788"

        customer = self.app.test_client()
        admin = self.app.test_client()
        self.assertEqual(
            admin.post("/api/admin/login", json={"password": "admin1234"}).status_code, 200
        )

        self.assertEqual(customer.get("/api/calls/ice-config").status_code, 200)

        # Wrong phone / anonymous cannot start a call
        bad = customer.post(
            "/api/calls/start", json={"booking_code": code, "phone": "0000", "offer": "v=0 offer"}
        )
        self.assertEqual(bad.status_code, 403)

        started = customer.post(
            "/api/calls/start", json={"booking_code": code, "phone": phone, "offer": "v=0 offer"}
        )
        self.assertEqual(started.status_code, 201)
        call = started.get_json()["call"]
        self.assertEqual(call["status"], "ringing")
        call_id = call["id"]

        # Anonymous watcher without booking context is rejected; admin sees the call
        self.assertEqual(self.app.test_client().get("/api/calls/incoming").status_code, 401)
        incoming = admin.get("/api/calls/incoming").get_json()["call"]
        self.assertEqual(incoming["id"], call_id)
        self.assertEqual(incoming["offer_sdp"], "v=0 offer")

        # The caller does not receive their own call as incoming
        self.assertIsNone(
            customer.get(f"/api/calls/incoming?code={code}&phone={phone}").get_json()["call"]
        )

        # Customer cannot answer their own call; admin can
        self.assertEqual(
            customer.post(
                f"/api/calls/{call_id}/answer", json={"answer": "v=0 answer", "phone": phone}
            ).status_code,
            403,
        )
        answered = admin.post(f"/api/calls/{call_id}/answer", json={"answer": "v=0 answer"})
        self.assertEqual(answered.status_code, 200)
        self.assertEqual(answered.get_json()["call"]["status"], "active")

        # ICE candidates are exchanged in both directions
        cand_c = {"candidate": "candidate:1 1 udp 1 1.1.1.1 1000 typ host", "sdpMid": "0", "sdpMLineIndex": 0}
        cand_s = {"candidate": "candidate:2 1 udp 1 2.2.2.2 2000 typ host", "sdpMid": "0", "sdpMLineIndex": 0}
        self.assertEqual(
            customer.post(
                f"/api/calls/{call_id}/candidate", json={"candidate": cand_c, "phone": phone}
            ).status_code,
            200,
        )
        self.assertEqual(
            admin.post(f"/api/calls/{call_id}/candidate", json={"candidate": cand_s}).status_code, 200
        )
        caller_view = customer.get(f"/api/calls/{call_id}?phone={phone}").get_json()["call"]
        self.assertEqual(caller_view["answer_sdp"], "v=0 answer")
        self.assertEqual(len(caller_view["remote_candidates"]), 1)
        self.assertEqual(caller_view["remote_candidates"][0]["candidate"], cand_s["candidate"])
        callee_view = admin.get(f"/api/calls/{call_id}").get_json()["call"]
        self.assertEqual(len(callee_view["remote_candidates"]), 1)
        self.assertEqual(callee_view["remote_candidates"][0]["candidate"], cand_c["candidate"])

        # Wrong phone cannot read the call; ending works for either side
        self.assertEqual(customer.get(f"/api/calls/{call_id}?phone=0000").status_code, 403)
        ended = admin.post(f"/api/calls/{call_id}/end")
        self.assertEqual(ended.status_code, 200)
        self.assertEqual(ended.get_json()["call"]["status"], "ended")

        # Shop-initiated call to the customer, declined by the customer
        shop_call = admin.post(
            "/api/calls/start", json={"booking_code": code, "offer": "v=0 shop-offer"}
        )
        self.assertEqual(shop_call.status_code, 201)
        shop_call_id = shop_call.get_json()["call"]["id"]
        seen = customer.get(f"/api/calls/incoming?code={code}&phone={phone}").get_json()["call"]
        self.assertEqual(seen["id"], shop_call_id)
        declined = customer.post(f"/api/calls/{shop_call_id}/end", json={"phone": phone})
        self.assertEqual(declined.get_json()["call"]["status"], "declined")

        # Cancelled bookings cannot be called
        self.assertEqual(
            customer.post(
                "/api/bookings/cancel", json={"booking_code": code, "customer_phone": "7788"}
            ).status_code,
            200,
        )
        blocked = customer.post(
            "/api/calls/start", json={"booking_code": code, "phone": phone, "offer": "v=0 offer"}
        )
        self.assertEqual(blocked.status_code, 409)

        # Script is wired into every page
        html = self.client.get("/customer").get_data(as_text=True)
        self.assertIn("/static/js/calls.js", html)
        self.assertIn('data-nav="customer"', html)

    def test_web_push_notification_endpoints_and_triggers(self):
        # 1. Fetch VAPID public key
        key_resp = self.client.get("/api/push/vapid-public-key")
        self.assertEqual(key_resp.status_code, 200)
        pub_key = key_resp.get_json()["publicKey"]
        self.assertTrue(len(pub_key) >= 50)

        # 2. Test Subscribe validation
        bad_sub = self.client.post("/api/push/subscribe", json={})
        self.assertEqual(bad_sub.status_code, 400)

        sub_payload = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/test-sub-12345",
            "keys": {
                "p256dh": "BNcRdreALRFXTkOOUHK1EtK2wtaz5Ry4YfYCA_0QT9t044Yjs2oWGWKek8KaIR8HTDHUt8pvE0og-7Fm927pfGE",
                "auth": "tBHItJI5svbpez7KI4CCXg",
            },
            "phone": "0917 555 7788",
            "booking_code": "MR-2611-TEST",
        }

        # Customer subscribe
        cust_sub = self.client.post("/api/push/subscribe", json=sub_payload)
        self.assertEqual(cust_sub.status_code, 200)
        self.assertEqual(cust_sub.get_json()["role"], "customer")

        # Admin subscribe
        admin_client = self.app.test_client()
        self.assertEqual(
            admin_client.post("/api/admin/login", json={"password": "admin1234"}).status_code,
            200,
        )
        admin_sub_payload = dict(sub_payload)
        admin_sub_payload["endpoint"] = "https://updates.push.services.mozilla.com/wpush/v2/admin-test"
        admin_sub = admin_client.post("/api/push/subscribe", json=admin_sub_payload)
        self.assertEqual(admin_sub.status_code, 200)
        self.assertEqual(admin_sub.get_json()["role"], "admin")

        # 3. Test Push test endpoint (mocking pywebpush.webpush so no real network call happens)
        anon_test = self.client.post("/api/push/test")
        self.assertEqual(anon_test.status_code, 401)

        with patch("push_notifications.pywebpush.webpush", return_value=True):
            ok_test = admin_client.post("/api/push/test")
            self.assertEqual(ok_test.status_code, 200)
            self.assertTrue(ok_test.get_json()["ok"])

        # 4. Unsubscribe
        unsub = self.client.post("/api/push/unsubscribe", json={"endpoint": sub_payload["endpoint"]})
        self.assertEqual(unsub.status_code, 200)
        self.assertTrue(unsub.get_json()["ok"])

        # 5. Base template includes push.js script tag
        home_html = self.client.get("/").get_data(as_text=True)
        self.assertIn("/static/js/push.js", home_html)

    def test_pickup_methods_benoni_airport_and_around_mambajao(self):
        # 1. Homepage contains the new pickup method select options
        index_html = self.client.get("/").get_data(as_text=True)
        self.assertIn('value="benoni_port">Benoni Port (+₱200)</option>', index_html)
        self.assertIn('value="airport">Camiguin Airport (Free)</option>', index_html)
        self.assertIn('value="around_mambajao">Around Mambajao (Free)</option>', index_html)

        # 2. Get a bike (e.g. Honda Click 125i @ 450/day)
        click_bike = self.client.get("/api/bikes?category=Scooter").get_json()["bikes"][0]
        p = self._future_str(1)
        r = self._future_str(2) # 1 day rental = 450.0

        # Quote: benoni_port adds exactly 200 fee
        q_benoni = self.client.get(
            f"/api/quote?bike_id={click_bike['id']}&pickup_date={p}&return_date={r}&pickup_method=benoni_port"
        ).get_json()["quote"]
        self.assertEqual(q_benoni["delivery_total"], 200.0)
        self.assertEqual(q_benoni["total_amount"], 650.0)

        # Quote: airport is FREE (0 fee)
        q_airport = self.client.get(
            f"/api/quote?bike_id={click_bike['id']}&pickup_date={p}&return_date={r}&pickup_method=airport"
        ).get_json()["quote"]
        self.assertEqual(q_airport["delivery_total"], 0.0)
        self.assertEqual(q_airport["total_amount"], 450.0)

        # Quote: around_mambajao is FREE (0 fee)
        q_mambajao = self.client.get(
            f"/api/quote?bike_id={click_bike['id']}&pickup_date={p}&return_date={r}&pickup_method=around_mambajao"
        ).get_json()["quote"]
        self.assertEqual(q_mambajao["delivery_total"], 0.0)
        self.assertEqual(q_mambajao["total_amount"], 450.0)

        # 3. Create booking with Benoni Port
        p_b = self._future_str(12)
        r_b = self._future_str(14) # 2 days = 900 + 200 = 1100
        b_res = self.client.post(
            "/api/bookings",
            json={
                "bike_id": click_bike["id"],
                "pickup_date": p_b,
                "return_date": r_b,
                "pickup_time": "10:00",
                "customer_name": "Maria Ferry",
                "customer_phone": "09179988776",
                "license_number": "D02-11-223344",
                "pickup_method": "benoni_port",
            },
        )
        self.assertEqual(b_res.status_code, 201)
        b_data = b_res.get_json()["booking"]
        self.assertEqual(b_data["pickup_method"], "benoni_port")
        self.assertEqual(b_data["delivery_total"], 200.0)
        self.assertEqual(b_data["total_amount"], 1100.0)
        self.assertEqual(b_data["delivery_address"], "Benoni Port, Mahinog")
        self.assertEqual(b_data["delivery_lat"], 9.1306)
        self.assertEqual(b_data["delivery_lng"], 124.7937)

        # 4. Create booking with Airport
        p_a = self._future_str(15)
        r_a = self._future_str(16)
        a_res = self.client.post(
            "/api/bookings",
            json={
                "bike_id": click_bike["id"],
                "pickup_date": p_a,
                "return_date": r_a,
                "customer_name": "Pedro Flight",
                "customer_phone": "09187766554",
                "license_number": "D02-11-556677",
                "pickup_method": "airport",
            },
        )
        self.assertEqual(a_res.status_code, 201)
        a_data = a_res.get_json()["booking"]
        self.assertEqual(a_data["pickup_method"], "airport")
        self.assertEqual(a_data["delivery_total"], 0.0)
        self.assertEqual(a_data["total_amount"], 450.0)
        self.assertEqual(a_data["delivery_address"], "Camiguin Airport, Mambajao")
        self.assertEqual(a_data["delivery_lat"], 9.2530)
        self.assertEqual(a_data["delivery_lng"], 124.7061)

        # 5. Create booking with Around Mambajao requires address
        p_m = self._future_str(17)
        r_m = self._future_str(18)
        m_err = self.client.post(
            "/api/bookings",
            json={
                "bike_id": click_bike["id"],
                "pickup_date": p_m,
                "return_date": r_m,
                "customer_name": "Ana Resort",
                "customer_phone": "09191122334",
                "license_number": "D02-11-889900",
                "pickup_method": "around_mambajao",
            },
        )
        self.assertEqual(m_err.status_code, 400)
        self.assertIn("resort", m_err.get_json()["error"])

        m_ok = self.client.post(
            "/api/bookings",
            json={
                "bike_id": click_bike["id"],
                "pickup_date": p_m,
                "return_date": r_m,
                "customer_name": "Ana Resort",
                "customer_phone": "09191122334",
                "license_number": "D02-11-889900",
                "pickup_method": "around_mambajao",
                "delivery_address": "Paras Beach Resort, Yumbing",
            },
        )
        self.assertEqual(m_ok.status_code, 201)
        m_data = m_ok.get_json()["booking"]
        self.assertEqual(m_data["pickup_method"], "around_mambajao")
        self.assertEqual(m_data["delivery_total"], 0.0)
        self.assertEqual(m_data["total_amount"], 450.0)
        self.assertEqual(m_data["delivery_address"], "Paras Beach Resort, Yumbing")

    def test_default_bikes_use_svg_placeholder_and_photo_coming_soon(self):
        bikes_res = self.client.get("/api/bikes")
        self.assertEqual(bikes_res.status_code, 200)
        bikes = bikes_res.get_json()["bikes"]
        self.assertGreaterEqual(len(bikes), 6)
        for bike in bikes:
            self.assertEqual(bike["image_url"], "/static/icons/icon.svg")
            self.assertTrue(bike["is_placeholder_image"])
            self.assertNotIn("/static/images/", bike["image_url"])

        index_html = self.client.get("/").get_data(as_text=True)
        self.assertNotIn("/static/images/", index_html)
        self.assertIn("Photo Coming Soon", index_html)
        self.assertIn("bike-photo-placeholder", index_html)

    def test_partner_onboarding_mobile_camera_upload_and_payout_details(self):
        index_html = self.client.get("/").get_data(as_text=True)
        self.assertIn("landing-partner-onboard-form", index_html)
        self.assertIn("Ilista Imong Motor", index_html)

        partner_html = self.client.get("/partner").get_data(as_text=True)
        self.assertNotIn("/static/images/", partner_html)
        self.assertIn('id="reg-payout-method"', partner_html)
        self.assertIn('id="reg-payout-number"', partner_html)
        self.assertIn('id="reg-bike-photo"', partner_html)
        self.assertIn('capture="environment"', partner_html)

        # Register a new partner shop with direct mobile photo upload and GCash payout info
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        reg_res = self.client.post(
            "/api/partner/register",
            data={
                "shop_name": "Catarman Island Riders",
                "owner_name": "Ramon Reyes",
                "email": "ramon@catarmanriders.ph",
                "phone": "09171112233",
                "municipality": "Catarman",
                "address": "Bonbon Road near Sunken Cemetery",
                "delivery_fee": "250",
                "password": "password123",
                "payout_method": "Maya",
                "payout_number": "09189998877",
                "payout_account_name": "Ramon C. Reyes",
                "first_bike_name": "Yamaha NMAX 155",
                "first_bike_category": "Maxi Scooter",
                "first_bike_daily_rate": "750",
                "bike_photo": (io.BytesIO(png_bytes), "nmax155_phone.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(reg_res.status_code, 201)
        reg_json = reg_res.get_json()
        shop = reg_json["shop"]
        self.assertEqual(shop["payout_method"], "Maya")
        self.assertEqual(shop["payout_number"], "09189998877")
        self.assertEqual(shop["payout_account_name"], "Ramon C. Reyes")
        self.assertIsNotNone(reg_json.get("first_bike"))
        self.assertEqual(reg_json["first_bike"]["name"], "Yamaha NMAX 155")
        self.assertTrue(reg_json["first_bike"]["image_url"].startswith("/uploads/"))
        self.assertFalse(reg_json["first_bike"]["is_placeholder_image"])

        # Update payout details via partner profile
        upd_res = self.client.put(
            "/api/partner/profile",
            json={
                "shop_name": "Catarman Island Riders",
                "owner_name": "Ramon Reyes",
                "phone": "09171112233",
                "municipality": "Catarman",
                "delivery_fee": 250,
                "address": "Bonbon Road near Sunken Cemetery",
                "payout_method": "GCash & Maya",
                "payout_number": "09171112233",
                "payout_account_name": "Ramon Reyes Official",
            },
        )
        self.assertEqual(upd_res.status_code, 200)
        upd_shop = upd_res.get_json()["shop"]
        self.assertEqual(upd_shop["payout_method"], "GCash & Maya")
        self.assertEqual(upd_shop["payout_number"], "09171112233")
        self.assertEqual(upd_shop["payout_account_name"], "Ramon Reyes Official")

    def test_camiguin_preset_pickup_points_balbagon_and_hotel_delivery(self):
        index_html = self.client.get("/").get_data(as_text=True)
        self.assertIn("Benoni Port (Mahinog)", index_html)
        self.assertIn("Balbagon Port (Mambajao)", index_html)
        self.assertIn("Camiguin Airport (Mambajao)", index_html)
        self.assertIn("Hotel / Resort Delivery (Mambajao, Catarman, Sagay, Guinsiliban)", index_html)

        click_bike = self.client.get("/api/bikes?category=Scooter").get_json()["bikes"][0]
        p = self._future_str(20)
        r = self._future_str(21)

        q_balbagon = self.client.get(
            f"/api/quote?bike_id={click_bike['id']}&pickup_date={p}&return_date={r}&pickup_method=balbagon_port"
        ).get_json()["quote"]
        self.assertEqual(q_balbagon["delivery_total"], 0.0)
        self.assertEqual(q_balbagon["total_amount"], 450.0)

        b_res = self.client.post(
            "/api/bookings",
            json={
                "bike_id": click_bike["id"],
                "pickup_date": p,
                "return_date": r,
                "customer_name": "Bohol Ferry Tourist",
                "customer_phone": "09173334455",
                "license_number": "G01-24-112233",
                "pickup_method": "balbagon_port",
            },
        )
        self.assertEqual(b_res.status_code, 201)
        b_data = b_res.get_json()["booking"]
        self.assertEqual(b_data["pickup_method"], "balbagon_port")
        self.assertEqual(b_data["delivery_total"], 0.0)
        self.assertEqual(b_data["delivery_address"], "Balbagon Port (Mambajao)")
        self.assertEqual(b_data["delivery_lat"], 9.2561)
        self.assertEqual(b_data["delivery_lng"], 124.7175)

    def test_license_photo_requirement_and_prefilled_rental_contract(self):
        click_bike = self.client.get("/api/bikes?category=Scooter").get_json()["bikes"][0]
        p = self._future_str(22)
        r = self._future_str(24)

        # Storefront submission with require_license_photo=1 and no license_photo fails with 400
        missing_lic = self.client.post(
            "/api/bookings",
            data={
                "bike_id": str(click_bike["id"]),
                "pickup_date": p,
                "return_date": r,
                "pickup_time": "09:00",
                "pickup_method": "shop",
                "customer_name": "Carlos Rider",
                "customer_phone": "09174445566",
                "license_number": "N01-23-987654",
                "require_license_photo": "1",
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(missing_lic.status_code, 400)
        self.assertIn("Driver's License", missing_lic.get_json()["error"])

        # Uploading valid license photo + digital signature succeeds and populates printable contract
        png_bytes = (
            b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
            b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        sig_data_uri = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")
        ok_res = self.client.post(
            "/api/bookings",
            data={
                "bike_id": str(click_bike["id"]),
                "pickup_date": p,
                "return_date": r,
                "pickup_time": "09:00",
                "pickup_method": "balbagon_port",
                "customer_name": "Carlos Rider",
                "customer_phone": "09174445566",
                "customer_address": "Balyali Resort, Agoho, Mambajao",
                "license_number": "N01-23-987654",
                "require_license_photo": "1",
                "contract_agreed": "1",
                "signature_data": sig_data_uri,
                "license_photo": (io.BytesIO(png_bytes), "ph_drivers_license.png"),
            },
            content_type="multipart/form-data",
        )
        self.assertEqual(ok_res.status_code, 201)
        booking = ok_res.get_json()["booking"]
        self.assertTrue(booking["license_photo_url"].startswith("/uploads/"))
        self.assertTrue(booking["signature_url"].startswith("/uploads/"))

        contract_res = self.client.get(
            f"/bookings/{booking['booking_code']}/contract?phone=09174445566"
        )
        self.assertEqual(contract_res.status_code, 200)
        contract_html = contract_res.get_data(as_text=True)
        self.assertIn(booking["booking_code"], contract_html)
        self.assertIn("Carlos Rider", contract_html)
        self.assertIn("N01-23-987654", contract_html)
        self.assertIn(booking["license_photo_url"], contract_html)
        self.assertIn(booking["signature_url"], contract_html)
        self.assertIn("Helmet Use &amp; Safety Policy", contract_html)
        self.assertIn("Gas / Fuel Policy (Unleaded)", contract_html)
        self.assertIn("Damage &amp; Loss Liability", contract_html)


if __name__ == "__main__":
    unittest.main()
