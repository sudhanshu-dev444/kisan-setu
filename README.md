![Uploading Presentation1.gif…]()
# Kisan Setu (किसान सेतु) — Unified Agricultural Mandi & Direct Procurement 

---

## Architecture & Unified Server Execution

The codebase provides **two complementary execution runtimes** that share the exact same SQLite database (`app_build/data/kisan_setu.db`), seed data, and data models:

```
                          ┌─────────────────────────────┐
                          │   Frontend: index.html      │
                          │   Single-Page App (SPA)     │
                          │   Tailwind CSS / Vanilla JS │
                          └──────────────┬──────────────┘
                                         │
                 ┌───────────────────────┴───────────────────────┐
                 ▼                                               ▼
┌─────────────────────────────────┐             ┌─────────────────────────────────┐
│     serve.py (Port 8080)        │             │   app_build/main.py (Port 8000) │
│  • Standalone Zero-Dependency   │             │  • Production ASGI (FastAPI)   │
│  • Standard Python 3.10+        │             │  • Asynchronous (uvicorn)       │
│  • Built-in sqlite3 + WAL       │             │  • In-Memory Sliding-Window RL  │
│  • Handles /api/* & /api/v1/*   │             │  • Security Headers Middleware  │
└────────────────┬────────────────┘             └────────────────┬────────────────┘
                 │                                               │
                 └───────────────────────┬───────────────────────┘
                                         ▼
                 ┌───────────────────────────────────────────────┐
                 │   app_build/data/kisan_setu.db (SQLite WAL)   │
                 │   Farmers, Bookings, Prices, PFMS Vouchers    │
                 └───────────────────────────────────────────────┘
```

### Option 1: Standalone Zero-Dependency Runner (`serve.py`)
No `pip install` required! Runs immediately using Python's built-in standard library:
```bash
cd "farmgrow-main/Kisan Setu"
python serve.py
```
- **Port:** `8080` (or next free port)
- **Features:**
  - Serves `index.html` and all static web assets with proper MIME types.
  - Native support for all `/api/*` endpoints (OTP, MSP, Mandi, Schemes, Centers, Farmer profile).
  - Native support for all `/api/v1/*` endpoints (SQL DB health, statistics, farmers, slot bookings, market prices, weather, PFMS vouchers) connected to `kisan_setu.db`.

### Option 2: Production ASGI Backend (`app_build/main.py`)
For production deployments requiring high-concurrency async I/O, rate limiting, and security headers:
```bash
cd "farmgrow-main/Kisan Setu/app_build"
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```
- **Port:** `8000`
- **Features:**
  - Full FastAPI framework with Swagger documentation (`/docs`, disabled by default for security).
  - Sliding-window per-IP rate limiting (login/signup 5/min, default 120/min).
  - Full suite of security response headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options).
  - Mounts both `/api/v1/*` and `/api/*` endpoints.

---

## Key Features 

### 1. Zero-Regression Authentication & Session Engine
- **SMS OTP Verification:** Request OTP via `POST /api/auth/send-otp` and verify via `POST /api/auth/verify-otp`.
- **Demo Mode:** Instant login button (`Quick Demo Login (Ram Singh)`) and autofill OTP `482910` for testing.
- **Client Session Persistence:** Session stored in `localStorage` (`kisan_setu_user_session`) and automatically restored across page refreshes.
- **Dynamic UI Personalization (`applyFarmerToUI`):**
  - Personalizes dashboard greeting ("Namaste, [Farmer Name] Ji! 🙏") and farmer subtitle.
  - Dynamically updates the navigation drawer initials avatar, farmer name, and ID.
  - Updates profile modal with active land holding, Aadhaar status, and bank account.
  - Pre-fills DBT card summaries and Sahayak AI chat greeting.

### 2. Relational SQLite Database & Real-Time Inspector
- **Engine:** SQLite 3 in WAL (Write-Ahead Logging) mode.
- **Database Path:** `app_build/data/kisan_setu.db`.
- **Inspector Modal (`sql-db-modal`):** Click the database status button in the header to view:
  - SQLite WAL mode and engine health.
  - Total registered farmers count and live records table.
  - Total procurement slot bookings count and live bookings table.
  - Database disk file size in KB.

### 3. Live Mandi Market Prices & MSP Comparisons
- **Live Mandi Ticker:** Displays real-time modal prices and price difference relative to the Government Minimum Support Price (MSP).
- **Commodity Switcher:** Select from Wheat, Rice, Mustard, Cotton, Maize, Sugarcane, Soybean, Groundnut, Sunflower, Gram (Chana), Barley, or Bajra.
- **APMC Mandi Yard Coverage:** Real-time data across Karnal, Ludhiana, Pune, Nagpur, Taraori, Gharaunda, and Kurukshetra markets.

### 4. Real-Time Agro-Weather & Advisory
- **Weather Detail Modal:** Detailed forecast including temperature, humidity, wind velocity/direction, precipitation probability, feels-like temperature, sunrise/sunset, and farm-specific harvest advisories.
- **Open-Meteo Integration:** Live coordinate-based queries with graceful fallback.

### 5. PFMS Direct Benefit Transfer & Official Voucher Minting
- **Calculation:** Automated gross payout, mandi cess (1.5%), and net DBT payout calculations.
- **Voucher Minting (`/api/v1/payments/voucher/mint`):** Generates server-signed PFMS vouchers with HMAC-SHA256 audit hashes and electronic UTR numbers.
- **Receipt Verification:** Authentic receipts with tamper-proof signatures, printable download, and QR code inspection.

---
4. **CORS Hardening:** Configurable allowed origins; never wildcard with credentials.
5. **No PII Leaks:** Masked Aadhaar (`**3942`) and masked bank accounts (`XXXX-XXXX-5678`) only. Plaintext sensitive identifiers are never logged or echoed.
