# Motorbike Rentals Camiguin — Centralized Marketplace & PWA

A mobile-first **Centralized Multi-Vendor Motorbike Rental Marketplace + Progressive Web App (PWA)** built with **Python (Flask)** supporting **both local SQLite** and **cloud PostgreSQL (`DATABASE_URL`, e.g. Neon + Render)** with DB-persisted image uploads — zero Node.js required.

## Quick Start (Windows / Local SQLite)

Double-click `start_app.bat` or run in PowerShell / Terminal:

```powershell
python run.py --port 5050
```

*(If port `5050` is already in use, `run.py` automatically picks the next free port.)*

Then open in your browser:
- **Marketplace Storefront**: `http://127.0.0.1:5050`
- **My Bookings Tracker**: `http://127.0.0.1:5050/bookings`
- **Partner Rental Portal (Owner Login / Register)**: `http://127.0.0.1:5050/partner`
- **Main Platform Admin Center**: `http://127.0.0.1:5050/admin`
- **Health / DB Backend Check**: `http://127.0.0.1:5050/api/health`

## Default Accounts (Change Passwords After Going Live!)

- **Main Platform Admin (`/admin`)**: Password **`admin1234`** *(or set `ADMIN_PASSWORD` env var on first boot; editable anytime in **Admin -> Platform Settings**)*
- **Sample Partner Rental Shops (`/partner`)**:
  - `yumbing@camiguinrentals.ph` (Yumbing Island Scooters — Mambajao) | Password: **`partner1234`**
  - `benoni@camiguinrentals.ph` (Benoni Port Moto Express — Mahinog) | Password: **`partner1234`**
  - `main@camiguinrentals.ph` (Camiguin Central Hub — Mambajao) | Password: **`partner1234`**

## Key Features Included

1. **Centralized Marketplace Storefront (`/`)**
   - Filter motorbikes by **Camiguin Municipality** (`Mambajao`, `Mahinog`, `Catarman`, `Sagay`, `Guinsiliban`), **Rental Shop**, **Category**, **Transmission**, keyword search, sort, and **Available Only** toggle.
   - Automatic weekly rate savings on 7+ day rentals, itemized quote preview, and overlap-safe booking locks (SQLite `BEGIN IMMEDIATE` / PostgreSQL `SELECT ... FOR UPDATE`).
2. **Partner Owner Portal (`/partner`)**
   - Other motorbike rental owners can register their shop online (**Status starts as `Pending Admin Approval`**).
   - Strict shop isolation: each rental partner sees and manages only their own motorbikes, bookings, WhatsApp/pickup details, gross revenue, platform commission deduction, and net payout.
3. **Main Platform Admin Center (`/admin`)**
   - Approve, suspend, create, or manage Partner Shops and view per-shop revenue breakdown.
   - Editable **Platform Commission %** (default `10%`) applied dynamically to new bookings.
   - Centralized oversight of all bookings, fleet units, and platform settings.
4. **Dual Database + Persistent Uploads (`SQLite` & `PostgreSQL`)**
   - Runs automatically on local **SQLite (`motoride.db`)** when `DATABASE_URL` is unset, or switches automatically to **PostgreSQL** (`psycopg[binary]`) when `DATABASE_URL` is provided (ideal for **Neon + Render**).
   - Partner/Admin uploaded motorbike photos are stored in the `uploaded_media` database table and served from `/uploads/<filename>`, surviving container restarts on ephemeral cloud hosts like Render Free Tier.
5. **Installable App (PWA)**
   - Works on Android, iPhone/iPad (Add to Home Screen), and Windows/macOS Chrome/Edge with Service Worker (`/sw.js`) and `/offline` fallback.

## Hosting 24/7 Free Online (GitHub + Neon + Render)

- See [DEPLOY.md](./DEPLOY.md) for the complete **₱0 Forever** guide on deploying via **GitHub + Neon PostgreSQL + Render** (no credit card, no monthly extend click) as well as **PythonAnywhere** and Android APK packaging via **PWABuilder**.

## Running Automated Tests

```powershell
python -m unittest discover -s tests -v
```
