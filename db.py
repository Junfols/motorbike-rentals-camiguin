import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(BASE_DIR, "motoride.db")

BLOCKING_STATUSES = ("pending", "confirmed", "active")
VALID_BOOKING_STATUSES = ("pending", "confirmed", "active", "completed", "cancelled")
VALID_BIKE_STATUSES = ("available", "maintenance", "hidden")
VALID_SHOP_STATUSES = ("pending", "approved", "suspended")
VALID_RESERVATION_MODES = ("off", "optional", "required")
VALID_PAYMENT_STATUSES = ("unpaid", "submitted", "verified", "rejected", "refunded")
VALID_CATEGORIES = ("Scooter", "Maxi Scooter", "Adventure", "Big Bike")
VALID_TRANSMISSIONS = ("Automatic", "Manual")
CAMIGUIN_MUNICIPALITIES = ("Mambajao", "Catarman", "Sagay", "Guinsiliban", "Mahinog")

MEDIA_MIME_TYPES = {
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "jfif": "image/jpeg",
    "webp": "image/webp",
}

SECRET_SETTING_KEYS = {
    "admin_password_hash",
    "secret_key",
    "telegram_bot_token",
    "smtp_password",
    "admin_telegram_chat_id",
    "admin_notify_email",
    "smtp_host",
    "smtp_port",
    "smtp_username",
    "smtp_from_email",
    "notify_partner_email",
    "notify_customer_email",
    "paymongo_secret_key",
    "paymongo_public_key",
    "paymongo_webhook_secret",
}

_ALERT_ENV_FALLBACKS = {
    "telegram_bot_token": "TELEGRAM_BOT_TOKEN",
    "admin_telegram_chat_id": "ADMIN_TELEGRAM_CHAT_ID",
    "admin_notify_email": "ADMIN_NOTIFY_EMAIL",
    "smtp_host": "SMTP_HOST",
    "smtp_port": "SMTP_PORT",
    "smtp_username": "SMTP_USERNAME",
    "smtp_password": "SMTP_PASSWORD",
    "smtp_from_email": "SMTP_FROM_EMAIL",
    "paymongo_secret_key": "PAYMONGO_SECRET_KEY",
    "paymongo_public_key": "PAYMONGO_PUBLIC_KEY",
    "paymongo_webhook_secret": "PAYMONGO_WEBHOOK_SECRET",
}

_PG_INIT_LOCK_KEY = 84729103


def get_database_url(explicit_url: str | None = None) -> str | None:
    """Resolve PostgreSQL connection URI from explicit value or environment."""
    raw = (
        explicit_url
        or os.environ.get("DATABASE_URL")
        or os.environ.get("MOTORIDE_DATABASE_URL")
        or ""
    ).strip()
    if raw.startswith("postgres://"):
        raw = "postgresql://" + raw[len("postgres://") :]
    return raw or None


def is_postgres_url(db_url: str | None) -> bool:
    """Return True if the connection target is PostgreSQL."""
    return bool(db_url and db_url.startswith(("postgresql://", "postgres://")))


def translate_sql_to_postgres(sql: str) -> str:
    """Translate SQLite '?' placeholders to PostgreSQL '%s' outside quoted strings."""
    out: list[str] = []
    i = 0
    n = len(sql)
    in_single = False
    in_double = False
    while i < n:
        ch = sql[i]
        if ch == "'" and not in_double:
            if in_single and i + 1 < n and sql[i + 1] == "'":
                out.append("''")
                i += 2
                continue
            in_single = not in_single
            out.append(ch)
        elif ch == '"' and not in_single:
            in_double = not in_double
            out.append(ch)
        elif not in_single and not in_double and ch == "?":
            out.append("%s")
        elif not in_single and not in_double and ch == "%":
            out.append("%%")
        else:
            out.append(ch)
        i += 1
    return "".join(out)


class CompatRow:
    """Row wrapper supporting both key access (row['col']) and index access (row[0])."""

    def __init__(self, columns: list[str], values: tuple | list):
        self._columns = list(columns)
        self._values = tuple(values)
        self._map = {col: val for col, val in zip(self._columns, self._values)}

    def __getitem__(self, key):
        if isinstance(key, int):
            return self._values[key]
        return self._map[key]

    def get(self, key: str, default=None):
        return self._map.get(key, default)

    def keys(self) -> list[str]:
        return list(self._columns)

    def __contains__(self, key: str) -> bool:
        return key in self._map

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


class CompatCursor:
    """Cursor wrapper normalizing fetch results between SQLite and psycopg."""

    def __init__(self, raw_cursor, is_postgres: bool):
        self._cur = raw_cursor
        self._is_postgres = is_postgres
        self._columns = (
            [col.name for col in raw_cursor.description]
            if is_postgres and raw_cursor.description
            else []
        )

    @property
    def lastrowid(self):
        return getattr(self._cur, "lastrowid", None)

    def fetchone(self):
        row = self._cur.fetchone()
        if row is None or not self._is_postgres:
            return row
        return CompatRow(self._columns, row)

    def fetchall(self):
        rows = self._cur.fetchall()
        if not self._is_postgres:
            return rows
        return [CompatRow(self._columns, r) for r in rows]


class DatabaseConnection:
    """Unified connection wrapper over SQLite and PostgreSQL (psycopg v3)."""

    def __init__(self, raw_conn, backend: str):
        self._raw = raw_conn
        self.backend = backend
        self._tx_stack: list = []
        self._manual_tx = None

    def execute(self, sql: str, params: tuple | list = ()) -> CompatCursor:
        if self.backend == "postgresql":
            pg_sql = translate_sql_to_postgres(sql)
            cur = self._raw.execute(pg_sql, params or None)
            return CompatCursor(cur, is_postgres=True)
        cur = self._raw.execute(sql, params)
        return CompatCursor(cur, is_postgres=False)

    def executemany(self, sql: str, seq_of_params) -> CompatCursor:
        if self.backend == "postgresql":
            pg_sql = translate_sql_to_postgres(sql)
            cur = self._raw.cursor()
            cur.executemany(pg_sql, seq_of_params)
            return CompatCursor(cur, is_postgres=True)
        cur = self._raw.executemany(sql, seq_of_params)
        return CompatCursor(cur, is_postgres=False)

    def insert_returning_id(self, sql: str, params: tuple | list = ()) -> int:
        """Execute an INSERT statement and return the newly inserted integer primary key."""
        if self.backend == "postgresql":
            pg_sql = translate_sql_to_postgres(sql.strip().rstrip(";")) + " RETURNING id"
            cur = self._raw.execute(pg_sql, params or None)
            row = cur.fetchone()
            return int(row[0])
        cur = self._raw.execute(sql, params)
        return int(cur.lastrowid)

    def begin_booking_lock(self, bike_id: int):
        """Acquire a write/row lock on a bike before availability counting and insert."""
        if self.backend == "postgresql":
            if self._manual_tx is not None:
                self.rollback()
            elif not getattr(self._raw, "autocommit", False):
                self._raw.rollback()
            tx = self._raw.transaction()
            tx.__enter__()
            self._manual_tx = tx
            return self.execute(
                "SELECT * FROM bikes WHERE id = ? FOR UPDATE", (bike_id,)
            ).fetchone()
        self._raw.execute("BEGIN IMMEDIATE")
        return self.execute("SELECT * FROM bikes WHERE id = ?", (bike_id,)).fetchone()

    def commit(self):
        if self.backend == "postgresql" and self._manual_tx is not None:
            tx = self._manual_tx
            self._manual_tx = None
            tx.__exit__(None, None, None)
            return
        self._raw.commit()

    def rollback(self):
        if self.backend == "postgresql" and self._manual_tx is not None:
            tx = self._manual_tx
            self._manual_tx = None
            tx.__exit__(RuntimeError, RuntimeError("rollback"), None)
            return
        self._raw.rollback()

    def close(self):
        try:
            if self.backend == "postgresql" and self._manual_tx is not None:
                self.rollback()
        finally:
            self._raw.close()

    def __enter__(self):
        if self.backend == "postgresql":
            tx = self._raw.transaction()
            tx.__enter__()
            self._tx_stack.append(tx)
            return self
        self._raw.__enter__()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.backend == "postgresql":
            tx = self._tx_stack.pop()
            return tx.__exit__(exc_type, exc_val, exc_tb)
        return self._raw.__exit__(exc_type, exc_val, exc_tb)


def get_connection(
    db_path: str | None = None,
    db_url: str | None = None,
) -> DatabaseConnection:
    """Create a database connection for PostgreSQL (if configured) or SQLite."""
    target_url = get_database_url(db_url)
    if db_path and not db_url and os.environ.get("DATABASE_URL") is None:
        target_url = None
    if db_path and db_url == "":
        target_url = None

    if is_postgres_url(target_url):
        import psycopg

        raw = psycopg.connect(target_url, connect_timeout=15, autocommit=True)
        return DatabaseConnection(raw, backend="postgresql")

    path = db_path or os.environ.get("MOTORIDE_DB_PATH") or DEFAULT_DB_PATH
    raw = sqlite3.connect(path, timeout=15, check_same_thread=False)
    raw.row_factory = sqlite3.Row
    raw.execute("PRAGMA foreign_keys = ON")
    return DatabaseConnection(raw, backend="sqlite")


def _table_columns(conn: DatabaseConnection, table_name: str) -> set[str]:
    if conn.backend == "postgresql":
        rows = conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = ?
            """,
            (table_name,),
        ).fetchall()
        return {row[0] for row in rows}
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def _create_sqlite_schema(conn: DatabaseConnection) -> None:
    conn._raw.executescript(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS shops (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            owner_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            whatsapp_number TEXT NOT NULL DEFAULT '',
            municipality TEXT NOT NULL DEFAULT 'Mambajao',
            address TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            delivery_fee REAL NOT NULL DEFAULT 250,
            telegram_chat_id TEXT NOT NULL DEFAULT '',
            logo_url TEXT NOT NULL DEFAULT '',
            cover_url TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            is_main INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bikes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            shop_id INTEGER NOT NULL DEFAULT 1 REFERENCES shops(id) ON DELETE RESTRICT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            engine_cc INTEGER NOT NULL,
            transmission TEXT NOT NULL,
            fuel_type TEXT NOT NULL DEFAULT 'Gasoline',
            daily_rate REAL NOT NULL,
            weekly_rate REAL NOT NULL DEFAULT 0,
            deposit REAL NOT NULL DEFAULT 1500,
            units_count INTEGER NOT NULL DEFAULT 1,
            plate_number TEXT NOT NULL DEFAULT '',
            inclusions TEXT NOT NULL DEFAULT '2 Helmets, Phone Mount, Rain Poncho',
            description TEXT NOT NULL DEFAULT '',
            image_url TEXT NOT NULL DEFAULT '/static/images/bike-click125.jpg',
            status TEXT NOT NULL DEFAULT 'available',
            featured INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_code TEXT UNIQUE NOT NULL,
            bike_id INTEGER NOT NULL REFERENCES bikes(id) ON DELETE RESTRICT,
            shop_id INTEGER NOT NULL DEFAULT 1 REFERENCES shops(id) ON DELETE RESTRICT,
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
            reservation_fee REAL NOT NULL DEFAULT 0,
            balance_due REAL NOT NULL DEFAULT 0,
            payment_channel TEXT NOT NULL DEFAULT 'pay_at_shop',
            payment_reference TEXT NOT NULL DEFAULT '',
            payment_proof_url TEXT NOT NULL DEFAULT '',
            payment_status TEXT NOT NULL DEFAULT 'unpaid',
            balance_paid INTEGER NOT NULL DEFAULT 0,
            payment_link_id TEXT NOT NULL DEFAULT '',
            payment_checkout_url TEXT NOT NULL DEFAULT '',
            deposit_amount REAL NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            admin_notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS bike_blocks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bike_id INTEGER NOT NULL REFERENCES bikes(id) ON DELETE CASCADE,
            shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            units_blocked INTEGER NOT NULL DEFAULT 1,
            reason TEXT NOT NULL DEFAULT 'Walk-in / Offline Booking',
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS uploaded_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT UNIQUE NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            data BLOB NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )


def _create_postgres_schema(conn: DatabaseConnection) -> None:
    statements = [
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS shops (
            id SERIAL PRIMARY KEY,
            shop_name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            owner_name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            phone TEXT NOT NULL,
            whatsapp_number TEXT NOT NULL DEFAULT '',
            municipality TEXT NOT NULL DEFAULT 'Mambajao',
            address TEXT NOT NULL DEFAULT '',
            description TEXT NOT NULL DEFAULT '',
            delivery_fee DOUBLE PRECISION NOT NULL DEFAULT 250,
            telegram_chat_id TEXT NOT NULL DEFAULT '',
            logo_url TEXT NOT NULL DEFAULT '',
            cover_url TEXT NOT NULL DEFAULT '',
            password_hash TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            is_main INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bikes (
            id SERIAL PRIMARY KEY,
            shop_id INTEGER NOT NULL DEFAULT 1 REFERENCES shops(id) ON DELETE RESTRICT,
            name TEXT NOT NULL,
            slug TEXT UNIQUE NOT NULL,
            category TEXT NOT NULL,
            engine_cc INTEGER NOT NULL,
            transmission TEXT NOT NULL,
            fuel_type TEXT NOT NULL DEFAULT 'Gasoline',
            daily_rate DOUBLE PRECISION NOT NULL,
            weekly_rate DOUBLE PRECISION NOT NULL DEFAULT 0,
            deposit DOUBLE PRECISION NOT NULL DEFAULT 1500,
            units_count INTEGER NOT NULL DEFAULT 1,
            plate_number TEXT NOT NULL DEFAULT '',
            inclusions TEXT NOT NULL DEFAULT '2 Helmets, Phone Mount, Rain Poncho',
            description TEXT NOT NULL DEFAULT '',
            image_url TEXT NOT NULL DEFAULT '/static/images/bike-click125.jpg',
            status TEXT NOT NULL DEFAULT 'available',
            featured INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            booking_code TEXT UNIQUE NOT NULL,
            bike_id INTEGER NOT NULL REFERENCES bikes(id) ON DELETE RESTRICT,
            shop_id INTEGER NOT NULL DEFAULT 1 REFERENCES shops(id) ON DELETE RESTRICT,
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
            base_subtotal DOUBLE PRECISION NOT NULL,
            addons_total DOUBLE PRECISION NOT NULL DEFAULT 0,
            delivery_total DOUBLE PRECISION NOT NULL DEFAULT 0,
            total_amount DOUBLE PRECISION NOT NULL,
            commission_rate DOUBLE PRECISION NOT NULL DEFAULT 10,
            platform_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
            shop_payout DOUBLE PRECISION NOT NULL DEFAULT 0,
            reservation_fee DOUBLE PRECISION NOT NULL DEFAULT 0,
            balance_due DOUBLE PRECISION NOT NULL DEFAULT 0,
            payment_channel TEXT NOT NULL DEFAULT 'pay_at_shop',
            payment_reference TEXT NOT NULL DEFAULT '',
            payment_proof_url TEXT NOT NULL DEFAULT '',
            payment_status TEXT NOT NULL DEFAULT 'unpaid',
            balance_paid INTEGER NOT NULL DEFAULT 0,
            payment_link_id TEXT NOT NULL DEFAULT '',
            payment_checkout_url TEXT NOT NULL DEFAULT '',
            deposit_amount DOUBLE PRECISION NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            admin_notes TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS bike_blocks (
            id SERIAL PRIMARY KEY,
            bike_id INTEGER NOT NULL REFERENCES bikes(id) ON DELETE CASCADE,
            shop_id INTEGER NOT NULL REFERENCES shops(id) ON DELETE CASCADE,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            units_blocked INTEGER NOT NULL DEFAULT 1,
            reason TEXT NOT NULL DEFAULT 'Walk-in / Offline Booking',
            created_at TEXT NOT NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS uploaded_media (
            id SERIAL PRIMARY KEY,
            filename TEXT UNIQUE NOT NULL,
            content_type TEXT NOT NULL DEFAULT 'application/octet-stream',
            data BYTEA NOT NULL,
            created_at TEXT NOT NULL
        )
        """,
    ]
    for stmt in statements:
        conn.execute(stmt)


def _create_indexes(conn: DatabaseConnection) -> None:
    indexes = [
        "CREATE INDEX IF NOT EXISTS idx_bikes_shop ON bikes (shop_id, status)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_bike_dates ON bookings (bike_id, pickup_date, return_date, status)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_shop_status ON bookings (shop_id, status, pickup_date)",
        "CREATE INDEX IF NOT EXISTS idx_bookings_code ON bookings (booking_code)",
        "CREATE INDEX IF NOT EXISTS idx_bike_blocks_bike_dates ON bike_blocks (bike_id, start_date, end_date)",
        "CREATE INDEX IF NOT EXISTS idx_media_filename ON uploaded_media (filename)",
    ]
    for idx in indexes:
        conn.execute(idx)


def init_db(db_path: str | None = None, db_url: str | None = None) -> None:
    """Create tables, migrate legacy single-shop schema if needed, and seed defaults."""
    conn = get_connection(db_path=db_path, db_url=db_url)
    try:
        with conn:
            if conn.backend == "postgresql":
                # Transaction-scoped lock stays safe on Neon PgBouncer transaction poolers
                conn.execute("SELECT pg_advisory_xact_lock(?)", (_PG_INIT_LOCK_KEY,))
                _create_postgres_schema(conn)
            else:
                _create_sqlite_schema(conn)

            initial_admin_pw = (os.environ.get("ADMIN_PASSWORD") or "admin1234").strip()
            initial_secret = (os.environ.get("SECRET_KEY") or "").strip() or secrets.token_hex(32)
            default_settings = {
                "shop_name": "Motorbike Rentals Camiguin",
                "tagline": "Centralized island motorbike rental marketplace — verified local shops across Camiguin.",
                "location": "Camiguin Island, Philippines",
                "address": "Mambajao, Camiguin Island",
                "phone": "+63 917 555 0148",
                "email": "hello@motorbikerentalscamiguin.ph",
                "messenger_url": "https://m.me/motorbikerentalscamiguin",
                "whatsapp_number": "639175550148",
                "currency": "₱",
                "commission_rate": "10",
                "delivery_fee": "250",
                "extra_helmet_fee": "50",
                "top_box_fee": "100",
                "opening_hours": "Daily, 7:00 AM – 8:00 PM",
                "terms_note": "Valid Driver's License required upon pickup. A refundable security deposit may be collected by the partner shop.",
                "telegram_bot_token": os.environ.get("TELEGRAM_BOT_TOKEN", ""),
                "admin_telegram_chat_id": os.environ.get("ADMIN_TELEGRAM_CHAT_ID", ""),
                "admin_notify_email": os.environ.get("ADMIN_NOTIFY_EMAIL", ""),
                "smtp_host": os.environ.get("SMTP_HOST", ""),
                "smtp_port": os.environ.get("SMTP_PORT", "587"),
                "smtp_username": os.environ.get("SMTP_USERNAME", ""),
                "smtp_password": os.environ.get("SMTP_PASSWORD", ""),
                "smtp_from_email": os.environ.get("SMTP_FROM_EMAIL", ""),
                "notify_partner_email": "1",
                "notify_customer_email": "1",
                "reservation_mode": "required",
                "reservation_percent": "10",
                "gcash_account_name": "",
                "gcash_number": "",
                "gcash_qr_url": "",
                "maya_number": "",
                "payment_instructions": "Scan the GCash QR or send the reservation fee, then enter your 13-digit Reference No. before submitting. Pay the remaining balance at the shop on pickup.",
                "admin_password_hash": generate_password_hash(initial_admin_pw),
                "secret_key": initial_secret,
            }
            for key, val in default_settings.items():
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT (key) DO NOTHING",
                    (key, val),
                )

            now = datetime.now().isoformat(timespec="seconds")
            existing_shops = conn.execute("SELECT COUNT(*) FROM shops").fetchone()[0]
            if existing_shops == 0:
                starter_shops = [
                    (
                        "Camiguin Central Hub",
                        "camiguin-central-hub",
                        "Platform Main Fleet",
                        "main@camiguinrentals.ph",
                        "+63 917 555 0148",
                        "639175550148",
                        "Mambajao",
                        "Rizal St., Poblacion, Mambajao",
                        "Main flagship rental desk located in central Mambajao near public market and town plaza.",
                        250,
                        generate_password_hash("partner1234"),
                        "approved",
                        1,
                        now,
                    ),
                    (
                        "Yumbing Island Scooters",
                        "yumbing-island-scooters",
                        "Marco Reyes",
                        "yumbing@camiguinrentals.ph",
                        "+63 917 555 0210",
                        "639175550210",
                        "Mambajao",
                        "Yumbing Road (near White Island Boat Terminal)",
                        "Convenient beachfront scooter rentals right beside White Island jump-off resorts.",
                        200,
                        generate_password_hash("partner1234"),
                        "approved",
                        0,
                        now,
                    ),
                    (
                        "Benoni Port Moto Express",
                        "benoni-port-moto-express",
                        "Liza Villanueva",
                        "benoni@camiguinrentals.ph",
                        "+63 918 555 0399",
                        "639185550399",
                        "Mahinog",
                        "Benoni Wharf Rd., Mahinog, Camiguin",
                        "Step off the ferry and ride right away — scooters and touring bikes at Benoni Port.",
                        150,
                        generate_password_hash("partner1234"),
                        "approved",
                        0,
                        now,
                    ),
                ]
                conn.executemany(
                    """
                    INSERT INTO shops (
                        shop_name, slug, owner_name, email, phone, whatsapp_number,
                        municipality, address, description, delivery_fee, password_hash,
                        status, is_main, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    starter_shops,
                )

            # Safe schema migrations if upgrading an existing single-shop DB
            shop_cols = _table_columns(conn, "shops")
            if "telegram_chat_id" not in shop_cols:
                conn.execute("ALTER TABLE shops ADD COLUMN telegram_chat_id TEXT NOT NULL DEFAULT ''")
            if "logo_url" not in shop_cols:
                conn.execute("ALTER TABLE shops ADD COLUMN logo_url TEXT NOT NULL DEFAULT ''")
            if "cover_url" not in shop_cols:
                conn.execute("ALTER TABLE shops ADD COLUMN cover_url TEXT NOT NULL DEFAULT ''")

            bike_cols = _table_columns(conn, "bikes")
            if "shop_id" not in bike_cols:
                conn.execute("ALTER TABLE bikes ADD COLUMN shop_id INTEGER NOT NULL DEFAULT 1")

            booking_cols = _table_columns(conn, "bookings")
            if "shop_id" not in booking_cols:
                conn.execute("ALTER TABLE bookings ADD COLUMN shop_id INTEGER NOT NULL DEFAULT 1")
            if "commission_rate" not in booking_cols:
                conn.execute("ALTER TABLE bookings ADD COLUMN commission_rate REAL NOT NULL DEFAULT 0")
            if "platform_fee" not in booking_cols:
                conn.execute("ALTER TABLE bookings ADD COLUMN platform_fee REAL NOT NULL DEFAULT 0")
            if "shop_payout" not in booking_cols:
                conn.execute("ALTER TABLE bookings ADD COLUMN shop_payout REAL NOT NULL DEFAULT 0")
                conn.execute(
                    "UPDATE bookings SET shop_payout = total_amount WHERE shop_payout = 0 AND total_amount > 0"
                )
            if "reservation_fee" not in booking_cols:
                conn.execute("ALTER TABLE bookings ADD COLUMN reservation_fee REAL NOT NULL DEFAULT 0")
            if "balance_due" not in booking_cols:
                conn.execute("ALTER TABLE bookings ADD COLUMN balance_due REAL NOT NULL DEFAULT 0")
                conn.execute(
                    """
                    UPDATE bookings
                    SET balance_due = CASE
                        WHEN total_amount > COALESCE(reservation_fee, 0) THEN total_amount - COALESCE(reservation_fee, 0)
                        ELSE 0
                    END
                    WHERE balance_due = 0 AND total_amount > 0
                    """
                )
            if "payment_channel" not in booking_cols:
                conn.execute(
                    "ALTER TABLE bookings ADD COLUMN payment_channel TEXT NOT NULL DEFAULT 'pay_at_shop'"
                )
            if "payment_reference" not in booking_cols:
                conn.execute(
                    "ALTER TABLE bookings ADD COLUMN payment_reference TEXT NOT NULL DEFAULT ''"
                )
            if "payment_proof_url" not in booking_cols:
                conn.execute(
                    "ALTER TABLE bookings ADD COLUMN payment_proof_url TEXT NOT NULL DEFAULT ''"
                )
            if "payment_status" not in booking_cols:
                conn.execute(
                    "ALTER TABLE bookings ADD COLUMN payment_status TEXT NOT NULL DEFAULT 'unpaid'"
                )
            if "balance_paid" not in booking_cols:
                conn.execute(
                    "ALTER TABLE bookings ADD COLUMN balance_paid INTEGER NOT NULL DEFAULT 0"
                )
            if "payment_link_id" not in booking_cols:
                conn.execute(
                    "ALTER TABLE bookings ADD COLUMN payment_link_id TEXT NOT NULL DEFAULT ''"
                )
            if "payment_checkout_url" not in booking_cols:
                conn.execute(
                    "ALTER TABLE bookings ADD COLUMN payment_checkout_url TEXT NOT NULL DEFAULT ''"
                )

            _create_indexes(conn)

            # Promote RAFOLS MOTORBIKE RENTAL to Main Hub once if present in existing DB
            rafols_row = conn.execute(
                "SELECT id, is_main FROM shops WHERE LOWER(shop_name) = 'rafols motorbike rental' ORDER BY id ASC LIMIT 1"
            ).fetchone()
            if rafols_row:
                migrated_flag = conn.execute(
                    "SELECT value FROM settings WHERE key = 'main_hub_rafols_migrated'"
                ).fetchone()
                if not migrated_flag:
                    conn.execute("UPDATE shops SET is_main = 0 WHERE is_main != 0")
                    conn.execute(
                        "UPDATE shops SET is_main = 1, status = 'approved' WHERE id = ?",
                        (int(rafols_row["id"]),),
                    )
                    conn.execute(
                        "INSERT INTO settings (key, value) VALUES ('main_hub_rafols_migrated', '1') ON CONFLICT (key) DO NOTHING"
                    )

            req_mode_flag = conn.execute(
                "SELECT value FROM settings WHERE key = 'reservation_mode_required_v1'"
            ).fetchone()
            if not req_mode_flag:
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('reservation_mode', 'required') "
                    "ON CONFLICT (key) DO UPDATE SET value = 'required'"
                )
                conn.execute(
                    "INSERT INTO settings (key, value) VALUES ('reservation_mode_required_v1', '1') "
                    "ON CONFLICT (key) DO NOTHING"
                )

            existing_bikes = conn.execute("SELECT COUNT(*) FROM bikes").fetchone()[0]
            if existing_bikes == 0:
                shop_id_by_slug = {
                    row["slug"]: int(row["id"])
                    for row in conn.execute("SELECT id, slug FROM shops").fetchall()
                }
                hub_id = shop_id_by_slug.get("camiguin-central-hub", 1)
                yumbing_id = shop_id_by_slug.get("yumbing-island-scooters", hub_id)
                benoni_id = shop_id_by_slug.get("benoni-port-moto-express", hub_id)

                starter_bikes = [
                    (
                        hub_id,
                        "Honda Click 125i",
                        "honda-click-125i",
                        "Scooter",
                        125,
                        "Automatic",
                        "Gasoline",
                        450,
                        2700,
                        1500,
                        3,
                        "GA-1251",
                        "2 Helmets, Phone Mount, Rain Poncho",
                        "Agile, fuel-efficient city scooter ideal for Camiguin circumference loop rides and waterfalls.",
                        "/static/images/bike-click125.jpg",
                        "available",
                        1,
                        now,
                    ),
                    (
                        yumbing_id,
                        "Yamaha NMAX 155",
                        "yamaha-nmax-155",
                        "Maxi Scooter",
                        155,
                        "Automatic",
                        "Gasoline",
                        650,
                        3900,
                        2000,
                        2,
                        "GA-1552",
                        "2 Helmets, Phone Mount, USB Charger",
                        "Comfortable maxi scooter with ABS brakes and spacious under-seat storage for two-up island touring.",
                        "/static/images/bike-nmax155.jpg",
                        "available",
                        1,
                        now,
                    ),
                    (
                        yumbing_id,
                        "Honda PCX 160",
                        "honda-pcx-160",
                        "Maxi Scooter",
                        160,
                        "Automatic",
                        "Gasoline",
                        700,
                        4200,
                        2500,
                        2,
                        "GA-1603",
                        "2 Helmets, Phone Mount, USB-C Port",
                        "Smooth, quiet 160cc touring scooter built for effortless coastal highway cruising.",
                        "/static/images/bike-pcx160.jpg",
                        "available",
                        0,
                        now,
                    ),
                    (
                        benoni_id,
                        "Yamaha Mio Aerox 155",
                        "yamaha-aerox-155",
                        "Scooter",
                        155,
                        "Automatic",
                        "Gasoline",
                        600,
                        3600,
                        2000,
                        2,
                        "GA-1554",
                        "2 Helmets, Phone Mount, Disc Lock",
                        "Sporty, responsive 155cc scooter ready for immediate pickup near Benoni Port.",
                        "/static/images/bike-aerox155.jpg",
                        "available",
                        0,
                        now,
                    ),
                    (
                        hub_id,
                        "Honda ADV 160",
                        "honda-adv-160",
                        "Adventure",
                        160,
                        "Automatic",
                        "Gasoline",
                        850,
                        5100,
                        3000,
                        2,
                        "GA-1605",
                        "2 Helmets, Phone Mount, Windscreen, USB Port",
                        "Adventure-ready scooter with tall ground clearance for mountain climbs up Hibok-Hibok roads.",
                        "/static/images/bike-adv160.jpg",
                        "available",
                        1,
                        now,
                    ),
                    (
                        benoni_id,
                        "Kawasaki Dominar 400",
                        "kawasaki-dominar-400",
                        "Big Bike",
                        373,
                        "Manual",
                        "Gasoline",
                        1600,
                        9600,
                        5000,
                        1,
                        "MC-4006",
                        "2 Full-Face Helmets, Phone Mount, Disc Lock",
                        "400cc sport-touring motorcycle with 6-speed gearbox and confident power for long highway runs.",
                        "/static/images/bike-dominar400.jpg",
                        "available",
                        1,
                        now,
                    ),
                ]
                conn.executemany(
                    """
                    INSERT INTO bikes (
                        shop_id, name, slug, category, engine_cc, transmission, fuel_type,
                        daily_rate, weekly_rate, deposit, units_count, plate_number,
                        inclusions, description, image_url, status, featured, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    starter_bikes,
                )
    finally:
        conn.close()


def get_settings(conn: DatabaseConnection, include_secrets: bool = False) -> dict[str, str]:
    """Fetch platform settings as a dictionary."""
    rows = conn.execute("SELECT key, value FROM settings").fetchall()
    result = {row["key"]: row["value"] for row in rows}
    if include_secrets:
        for setting_key, env_name in _ALERT_ENV_FALLBACKS.items():
            if not result.get(setting_key):
                env_val = (os.environ.get(env_name) or "").strip()
                if env_val:
                    result[setting_key] = env_val
    else:
        for secret_key in SECRET_SETTING_KEYS:
            result.pop(secret_key, None)
    return result


def get_admin_settings_view(conn: DatabaseConnection) -> dict:
    """Return all editable platform settings for Main Admin with tokens masked."""
    full = get_settings(conn, include_secrets=True)
    token = full.pop("telegram_bot_token", "")
    smtp_pw = full.pop("smtp_password", "")
    pm_secret = full.pop("paymongo_secret_key", "")
    pm_wh = full.pop("paymongo_webhook_secret", "")
    full.pop("admin_password_hash", None)
    full.pop("secret_key", None)
    full["has_telegram_bot_token"] = bool(token)
    full["has_smtp_password"] = bool(smtp_pw)
    full["has_paymongo_secret_key"] = bool(pm_secret)
    full["has_paymongo_webhook_secret"] = bool(pm_wh)
    return full


def verify_admin_password(conn: DatabaseConnection, password: str) -> bool:
    """Verify the admin login password against stored hash."""
    row = conn.execute(
        "SELECT value FROM settings WHERE key = 'admin_password_hash'"
    ).fetchone()
    if not row or not password:
        return False
    return check_password_hash(row["value"], password)


def verify_shop_password(shop_row, password: str) -> bool:
    """Verify partner rental shop owner password."""
    if not shop_row or not password:
        return False
    return check_password_hash(shop_row["password_hash"], password)


def parse_iso_date(value: str) -> date:
    """Parse YYYY-MM-DD date string strictly."""
    return date.fromisoformat(value.strip())


def calculate_rental_days(pickup_date: str, return_date: str) -> int:
    """Return inclusive/minimum 1 rental day for pickup -> return dates."""
    p_dt = parse_iso_date(pickup_date)
    r_dt = parse_iso_date(return_date)
    if r_dt < p_dt:
        raise ValueError("Return date cannot be earlier than pickup date.")
    delta = (r_dt - p_dt).days
    return max(1, delta)


def calculate_quote(
    bike,
    settings: dict[str, str],
    pickup_date: str,
    return_date: str,
    pickup_method: str = "shop",
    extra_helmet: bool = False,
    top_box: bool = False,
    shop=None,
) -> dict:
    """Compute itemized booking pricing and platform commission split."""
    rental_days = calculate_rental_days(pickup_date, return_date)
    daily_rate = float(bike["daily_rate"])
    weekly_rate = float(bike["weekly_rate"] or 0)
    deposit = float(bike["deposit"] or 0)

    standard_total = rental_days * daily_rate
    base_subtotal = standard_total
    discount_saved = 0.0

    helmet_fee = float(settings.get("extra_helmet_fee", "50") or 0)
    top_box_fee = float(settings.get("top_box_fee", "100") or 0)
    if shop is not None and "delivery_fee" in shop.keys():
        delivery_fee = float(shop["delivery_fee"] or 0)
    else:
        delivery_fee = float(settings.get("delivery_fee", "250") or 0)

    addons_per_day = (helmet_fee if extra_helmet else 0.0) + (top_box_fee if top_box else 0.0)
    addons_total = rental_days * addons_per_day
    delivery_total = delivery_fee if pickup_method == "delivery" else 0.0
    total_amount = round(base_subtotal + addons_total + delivery_total, 2)

    commission_rate = float(settings.get("commission_rate", "10") or 0)
    commission_rate = max(0.0, min(100.0, commission_rate))
    platform_fee = round(total_amount * (commission_rate / 100.0), 2)
    shop_payout = round(total_amount - platform_fee, 2)

    reservation_mode = str(settings.get("reservation_mode", "off") or "off").strip().lower()
    if reservation_mode not in VALID_RESERVATION_MODES:
        reservation_mode = "off"
    reservation_configured = is_reservation_payment_configured(settings)
    reservation_percent = float(settings.get("reservation_percent", "10") or 0)
    reservation_percent = max(0.0, min(100.0, reservation_percent))
    if reservation_mode != "off" and reservation_configured and reservation_percent > 0:
        reservation_fee = round(total_amount * (reservation_percent / 100.0), 2)
    else:
        reservation_fee = 0.0
    balance_due = round(max(0.0, total_amount - reservation_fee), 2)

    return {
        "rental_days": rental_days,
        "daily_rate": daily_rate,
        "weekly_rate": weekly_rate,
        "base_subtotal": round(base_subtotal, 2),
        "discount_saved": round(discount_saved, 2),
        "addons_total": round(addons_total, 2),
        "delivery_fee_rate": round(delivery_fee, 2),
        "delivery_total": round(delivery_total, 2),
        "total_amount": total_amount,
        "commission_rate": round(commission_rate, 2),
        "platform_fee": platform_fee,
        "shop_payout": shop_payout,
        "reservation_mode": reservation_mode,
        "reservation_configured": reservation_configured,
        "reservation_percent": round(reservation_percent, 2),
        "reservation_fee": reservation_fee,
        "balance_due": balance_due,
        "deposit_amount": round(deposit, 2),
    }


def _peak_concurrency_in_window(
    intervals: list[tuple[date, date, int]],
    window_start: date,
    window_end: date,
) -> int:
    """Return peak concurrent booked/blocked units on any day in [window_start, window_end]."""
    if not intervals or window_end < window_start:
        return 0
    deltas: dict[date, int] = {}
    for s_dt, e_dt, units in intervals:
        if units <= 0 or e_dt < window_start or s_dt > window_end:
            continue
        cs = max(s_dt, window_start)
        ce = min(e_dt, window_end)
        deltas[cs] = deltas.get(cs, 0) + units
        end_next = ce + timedelta(days=1)
        deltas[end_next] = deltas.get(end_next, 0) - units

    running = 0
    peak = 0
    for day, delta in sorted(deltas.items()):
        if day > window_end:
            break
        running += delta
        if running > peak:
            peak = running
    return peak


def count_overlapping_bookings(
    conn: DatabaseConnection,
    bike_id: int,
    pickup_date: str,
    return_date: str,
    exclude_booking_id: int | None = None,
) -> int:
    """Return peak concurrent blocking bookings + manual blocks across [pickup_date, return_date]."""
    p_dt = parse_iso_date(pickup_date)
    r_dt = parse_iso_date(return_date)
    placeholders = ",".join("?" for _ in BLOCKING_STATUSES)
    query = f"""
        SELECT pickup_date, return_date FROM bookings
        WHERE bike_id = ?
          AND status IN ({placeholders})
          AND pickup_date <= ?
          AND return_date >= ?
    """
    params: list = [bike_id, *BLOCKING_STATUSES, return_date, pickup_date]
    if exclude_booking_id is not None:
        query += " AND id != ?"
        params.append(exclude_booking_id)

    intervals: list[tuple[date, date, int]] = []
    for row in conn.execute(query, params).fetchall():
        try:
            intervals.append((parse_iso_date(row["pickup_date"]), parse_iso_date(row["return_date"]), 1))
        except ValueError:
            continue

    block_rows = conn.execute(
        """
        SELECT start_date, end_date, units_blocked FROM bike_blocks
        WHERE bike_id = ?
          AND start_date <= ?
          AND end_date >= ?
        """,
        (bike_id, return_date, pickup_date),
    ).fetchall()
    for row in block_rows:
        try:
            intervals.append(
                (
                    parse_iso_date(row["start_date"]),
                    parse_iso_date(row["end_date"]),
                    max(1, int(row["units_blocked"] or 1)),
                )
            )
        except ValueError:
            continue

    return _peak_concurrency_in_window(intervals, p_dt, r_dt)


def _merge_date_ranges(sorted_dates: list[date], max_ranges: int = 12) -> list[dict[str, str]]:
    """Merge consecutive date objects into [{pickup_date, return_date}] spans."""
    if not sorted_dates:
        return []
    ranges: list[dict[str, str]] = []
    start = sorted_dates[0]
    prev = sorted_dates[0]
    for cur in sorted_dates[1:]:
        if (cur - prev).days == 1:
            prev = cur
            continue
        ranges.append({"pickup_date": start.isoformat(), "return_date": prev.isoformat()})
        if len(ranges) >= max_ranges:
            return ranges
        start = cur
        prev = cur
    ranges.append({"pickup_date": start.isoformat(), "return_date": prev.isoformat()})
    return ranges[:max_ranges]


def build_bike_schedules(
    conn: DatabaseConnection,
    bike_rows: list,
    ref_pickup_date: str | None = None,
    ref_return_date: str | None = None,
    calendar_days: int = 35,
    lookahead_days: int = 120,
    include_calendar: bool = False,
    include_admin_details: bool = False,
) -> dict[int, dict]:
    """Compute booked ranges, next available dates, and optional 35-day calendars in batch."""
    if not bike_rows:
        return {}

    today = date.today()
    p_dt = today
    if ref_pickup_date:
        try:
            p_dt = max(today, parse_iso_date(ref_pickup_date))
        except ValueError:
            p_dt = today
    r_dt = p_dt
    has_explicit_return = False
    if ref_return_date:
        try:
            parsed_r = parse_iso_date(ref_return_date)
            if parsed_r >= p_dt:
                r_dt = parsed_r
                has_explicit_return = True
        except ValueError:
            pass

    scan_start = today
    scan_end = max(today + timedelta(days=max(calendar_days, 1) - 1), r_dt) + timedelta(days=lookahead_days)
    total_days = (scan_end - scan_start).days + 1
    scan_start_str = scan_start.isoformat()

    bike_ids = [int(row["id"]) for row in bike_rows]
    id_placeholders = ",".join("?" for _ in bike_ids)
    status_placeholders = ",".join("?" for _ in BLOCKING_STATUSES)

    booking_rows = conn.execute(
        f"""
        SELECT id, bike_id, booking_code, customer_name, pickup_date, return_date, status
        FROM bookings
        WHERE bike_id IN ({id_placeholders})
          AND status IN ({status_placeholders})
          AND return_date >= ?
        ORDER BY pickup_date ASC
        """,
        (*bike_ids, *BLOCKING_STATUSES, scan_start_str),
    ).fetchall()

    block_rows = conn.execute(
        f"""
        SELECT id, bike_id, start_date, end_date, units_blocked, reason, created_at
        FROM bike_blocks
        WHERE bike_id IN ({id_placeholders})
          AND end_date >= ?
        ORDER BY start_date ASC, id ASC
        """,
        (*bike_ids, scan_start_str),
    ).fetchall()

    bookings_by_bike: dict[int, list] = {bid: [] for bid in bike_ids}
    for b in booking_rows:
        bookings_by_bike.setdefault(int(b["bike_id"]), []).append(b)

    blocks_by_bike: dict[int, list] = {bid: [] for bid in bike_ids}
    for blk in block_rows:
        blocks_by_bike.setdefault(int(blk["bike_id"]), []).append(blk)

    results: dict[int, dict] = {}
    for row in bike_rows:
        bid = int(row["id"])
        units_count = max(1, int(row["units_count"] or 1))
        bike_status = row["status"]
        diff_arr = [0] * (total_days + 1)

        def _add_interval(s_str: str, e_str: str, units: int) -> None:
            try:
                s_dt = parse_iso_date(s_str)
                e_dt = parse_iso_date(e_str)
            except ValueError:
                return
            if e_dt < scan_start or s_dt > scan_end or units <= 0:
                return
            s_idx = max(0, (s_dt - scan_start).days)
            e_idx = min(total_days - 1, (e_dt - scan_start).days)
            diff_arr[s_idx] += units
            diff_arr[e_idx + 1] -= units

        for b in bookings_by_bike.get(bid, []):
            _add_interval(b["pickup_date"], b["return_date"], 1)
        for blk in blocks_by_bike.get(bid, []):
            _add_interval(blk["start_date"], blk["end_date"], max(1, int(blk["units_blocked"] or 1)))

        day_counts: list[int] = [0] * total_days
        cur = 0
        for i in range(total_days):
            cur += diff_arr[i]
            day_counts[i] = max(0, cur)

        full_dates = [
            scan_start + timedelta(days=i)
            for i in range(total_days)
            if day_counts[i] >= units_count
        ]
        booked_ranges = _merge_date_ranges(full_dates)

        ref_start_idx = max(0, min(total_days - 1, (p_dt - scan_start).days))
        ref_end_idx = max(ref_start_idx, min(total_days - 1, (r_dt - scan_start).days))
        ref_peak = max(day_counts[ref_start_idx : ref_end_idx + 1])

        next_available_date = None
        next_available_return_date = None
        if bike_status == "available" and ref_peak >= units_count:
            span_days = ref_end_idx - ref_start_idx
            for cand_idx in range(ref_start_idx + 1, total_days - span_days):
                if all(day_counts[j] < units_count for j in range(cand_idx, cand_idx + span_days + 1)):
                    cand_start = scan_start + timedelta(days=cand_idx)
                    next_available_date = cand_start.isoformat()
                    if has_explicit_return:
                        next_available_return_date = (cand_start + timedelta(days=span_days)).isoformat()
                    break

        entry: dict = {
            "ref_booked_units": ref_peak,
            "booked_ranges": booked_ranges,
            "next_available_date": next_available_date,
            "next_available_return_date": next_available_return_date,
        }

        if include_calendar:
            cal = []
            for i in range(min(calendar_days, total_days)):
                cnt = day_counts[i]
                avail = max(0, units_count - cnt) if bike_status == "available" else 0
                if bike_status != "available" or avail == 0:
                    st = "booked"
                elif cnt > 0:
                    st = "limited"
                else:
                    st = "available"
                cal.append(
                    {
                        "date": (scan_start + timedelta(days=i)).isoformat(),
                        "booked_units": cnt,
                        "available_units": avail,
                        "units_count": units_count,
                        "status": st,
                    }
                )
            entry["availability_calendar"] = cal

        if include_admin_details:
            entry["upcoming_bookings"] = [
                {
                    "id": b["id"],
                    "booking_code": b["booking_code"],
                    "customer_name": b["customer_name"],
                    "pickup_date": b["pickup_date"],
                    "return_date": b["return_date"],
                    "status": b["status"],
                }
                for b in bookings_by_bike.get(bid, [])[:25]
            ]
            entry["blocks"] = [
                {
                    "id": blk["id"],
                    "start_date": blk["start_date"],
                    "end_date": blk["end_date"],
                    "units_blocked": int(blk["units_blocked"] or 1),
                    "reason": blk["reason"],
                    "created_at": blk["created_at"],
                }
                for blk in blocks_by_bike.get(bid, [])
            ]

        results[bid] = entry
    return results


def generate_booking_code(conn: DatabaseConnection) -> str:
    """Generate a readable unique booking reference like MR-2611-4821."""
    prefix = datetime.now().strftime("MR-%y%m-")
    for _ in range(25):
        suffix = f"{secrets.randbelow(9000) + 1000}"
        code = f"{prefix}{suffix}"
        exists = conn.execute(
            "SELECT 1 FROM bookings WHERE booking_code = ?", (code,)
        ).fetchone()
        if not exists:
            return code
    return f"{prefix}{secrets.token_hex(3).upper()}"


def _unique_slug(
    name: str,
    conn: DatabaseConnection,
    table_name: str,
    fallback: str,
    exclude_id: int | None = None,
) -> str:
    cleaned = "".join(ch.lower() if ch.isalnum() else "-" for ch in name.strip())
    base = "-".join(part for part in cleaned.split("-") if part) or fallback
    candidate = base
    counter = 2
    while True:
        if exclude_id is None:
            row = conn.execute(f"SELECT 1 FROM {table_name} WHERE slug = ?", (candidate,)).fetchone()
        else:
            row = conn.execute(
                f"SELECT 1 FROM {table_name} WHERE slug = ? AND id != ?",
                (candidate, exclude_id),
            ).fetchone()
        if not row:
            return candidate
        candidate = f"{base}-{counter}"
        counter += 1


def slugify_name(name: str, conn: DatabaseConnection, exclude_id: int | None = None) -> str:
    """Generate a unique URL slug for a motorbike."""
    return _unique_slug(name, conn, "bikes", "motorbike", exclude_id=exclude_id)


def slugify_shop_name(name: str, conn: DatabaseConnection, exclude_id: int | None = None) -> str:
    """Generate a unique URL slug for a partner rental shop."""
    return _unique_slug(name, conn, "shops", "rental-shop", exclude_id=exclude_id)


def is_reservation_payment_configured(settings: dict[str, str]) -> bool:
    """Return True when at least one GCash/Maya receiving channel, QR image, or PayMongo key is set."""
    return any(
        str(settings.get(key, "") or "").strip()
        for key in (
            "gcash_qr_url",
            "gcash_number",
            "maya_number",
            "paymongo_secret_key",
            "paymongo_public_key",
            "has_paymongo_secret_key",
        )
    )


def save_uploaded_media(
    conn: DatabaseConnection,
    filename: str,
    data: bytes,
    content_type: str | None = None,
    use_tx: bool = True,
) -> None:
    """Persist uploaded image bytes in DB so ephemeral cloud disks never lose bike photos."""
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    mime = content_type or MEDIA_MIME_TYPES.get(ext, "application/octet-stream")
    now = datetime.now().isoformat(timespec="seconds")
    sql = """
        INSERT INTO uploaded_media (filename, content_type, data, created_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT (filename) DO UPDATE
        SET content_type = excluded.content_type, data = excluded.data
    """
    if use_tx:
        with conn:
            conn.execute(sql, (filename, mime, data, now))
    else:
        conn.execute(sql, (filename, mime, data, now))


def get_uploaded_media(conn: DatabaseConnection, filename: str):
    """Fetch stored media row from DB if present."""
    return conn.execute(
        "SELECT filename, content_type, data FROM uploaded_media WHERE filename = ?",
        (filename,),
    ).fetchone()


def delete_uploaded_media_by_url(
    conn: DatabaseConnection,
    image_url: str | None,
    use_tx: bool = True,
) -> int:
    """Delete an /uploads/<filename> row directly when replaced or removed."""
    url = str(image_url or "").strip()
    if not url.startswith("/uploads/"):
        return 0
    filename = url[len("/uploads/") :].strip()
    if not filename or "/" in filename or "\\" in filename:
        return 0
    if use_tx:
        with conn:
            cur = conn.execute("DELETE FROM uploaded_media WHERE filename = ?", (filename,))
            return int(getattr(cur, "rowcount", 0) or 0)
    cur = conn.execute("DELETE FROM uploaded_media WHERE filename = ?", (filename,))
    return int(getattr(cur, "rowcount", 0) or 0)


def delete_unused_uploaded_media(conn: DatabaseConnection, image_url: str | None) -> None:
    """Clean up unreferenced DB-stored uploads when a photo/QR/receipt is deleted or replaced."""
    if not image_url or not image_url.startswith("/uploads/"):
        return
    still_used = (
        conn.execute("SELECT 1 FROM bikes WHERE image_url = ? LIMIT 1", (image_url,)).fetchone()
        or conn.execute(
            "SELECT 1 FROM bookings WHERE payment_proof_url = ? LIMIT 1",
            (image_url,),
        ).fetchone()
        or conn.execute(
            "SELECT 1 FROM settings WHERE key = 'gcash_qr_url' AND value = ? LIMIT 1",
            (image_url,),
        ).fetchone()
        or conn.execute(
            "SELECT 1 FROM shops WHERE logo_url = ? OR cover_url = ? LIMIT 1",
            (image_url, image_url),
        ).fetchone()
    )
    if not still_used:
        delete_uploaded_media_by_url(conn, image_url)
