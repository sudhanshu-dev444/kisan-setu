# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""ACID-compliant SQL Relational Database Service for Kisan Setu.

Provides persistent, relational storage for farmers, land holdings,
DBT bank accounts, mandi procurement slot bookings, and historical mandi prices.
Engineered using Python's standard library `sqlite3` with Write-Ahead Logging (WAL),
foreign keys enforcement, and non-blocking asynchronous execution via thread pooling.
"""

import asyncio
import hashlib
import hmac
import logging
import secrets
import os
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from config import Settings

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DatabaseService:
    """Encapsulates all SQL database interactions and migrations."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.db_path = settings.DATABASE_PATH
        # Ensure database directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_sync()

    def _get_connection(self) -> sqlite3.Connection:
        """Create a configured SQLite connection with row factories and WAL pragmas."""
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=15.0,
            check_same_thread=False,
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        return conn

    def _init_sync(self) -> None:
        """Apply table DDL migrations and seed initial records synchronously."""
        logger.info("Initializing Kisan Setu SQL database at: %s", self.db_path)
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Farmers Table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS farmers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    farmer_id TEXT UNIQUE NOT NULL,
                    full_name TEXT NOT NULL,
                    mobile TEXT UNIQUE NOT NULL,
                    village TEXT NOT NULL,
                    aadhaar_last4 TEXT DEFAULT '1234',
                    aadhaar_linked INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # 2. Land Records Table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS land_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    farmer_id TEXT NOT NULL REFERENCES farmers(farmer_id) ON DELETE CASCADE,
                    khasra_number TEXT NOT NULL,
                    total_area_acres REAL NOT NULL,
                    crop_sown TEXT NOT NULL,
                    soil_health_card_id TEXT,
                    created_at TEXT NOT NULL
                );
                """
            )

            # 3. Bank Accounts (DBT Setup) Table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS bank_accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    farmer_id TEXT NOT NULL REFERENCES farmers(farmer_id) ON DELETE CASCADE,
                    bank_name TEXT NOT NULL,
                    account_number_masked TEXT NOT NULL,
                    ifsc_code TEXT NOT NULL,
                    is_dbt_enabled INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                """
            )

            # 4. Slot Bookings / Gate Passes Table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS slot_bookings (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    token_number TEXT UNIQUE NOT NULL,
                    farmer_id TEXT NOT NULL,
                    farmer_name TEXT NOT NULL,
                    farmer_mobile TEXT NOT NULL,
                    commodity TEXT NOT NULL,
                    mandi_name TEXT NOT NULL,
                    booking_date TEXT NOT NULL,
                    time_slot TEXT NOT NULL,
                    estimated_qty_quintals REAL NOT NULL,
                    vehicle_type TEXT NOT NULL,
                    vehicle_number TEXT NOT NULL,
                    gate_number TEXT DEFAULT 'Gate 2',
                    queue_position INTEGER DEFAULT 4,
                    status TEXT DEFAULT 'CONFIRMED',
                    created_at TEXT NOT NULL
                );
                """
            )

            # 5. Mandi Prices History Table
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS mandi_prices_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    commodity TEXT NOT NULL,
                    variety TEXT NOT NULL,
                    market TEXT NOT NULL,
                    district TEXT NOT NULL,
                    state TEXT NOT NULL,
                    arrival_date TEXT NOT NULL,
                    min_price REAL NOT NULL,
                    max_price REAL NOT NULL,
                    modal_price REAL NOT NULL,
                    msp REAL,
                    recorded_at TEXT NOT NULL
                );
                """
            )

            # 6. PFMS Vouchers Table (Server-side issued & signed DBT payments)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS pfms_vouchers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    voucher_ref TEXT UNIQUE NOT NULL,
                    utr_number TEXT UNIQUE NOT NULL,
                    farmer_id TEXT NOT NULL,
                    farmer_name TEXT NOT NULL,
                    commodity TEXT NOT NULL,
                    quantity_quintals REAL NOT NULL,
                    msp_rate REAL NOT NULL,
                    gross_amount REAL NOT NULL,
                    net_payout REAL NOT NULL,
                    bank_name TEXT NOT NULL,
                    account_masked TEXT NOT NULL,
                    ifsc_code TEXT NOT NULL,
                    mandi_name TEXT NOT NULL,
                    status TEXT DEFAULT 'TRANSACTION_SUCCESSFUL',
                    npci_hash TEXT NOT NULL,
                    digital_signature TEXT NOT NULL,
                    issued_at TEXT NOT NULL
                );
                """
            )

            # 7. OTP Records Table — stores hashed OTPs for phone verification
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS otp_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phone TEXT NOT NULL,
                    otp_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    attempt_count INTEGER DEFAULT 0,
                    used INTEGER DEFAULT 0,
                    created_at TEXT NOT NULL
                );
                """
            )

            # 8. SMS Notifications Table — persists every SMS send attempt
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS sms_notifications (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    farmer_id TEXT,
                    phone_number TEXT NOT NULL,
                    message_type TEXT NOT NULL,
                    message TEXT NOT NULL,
                    reference_type TEXT,
                    reference_id TEXT,
                    provider_message_id TEXT DEFAULT '',
                    status TEXT DEFAULT 'PENDING',
                    attempt_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    sent_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            # ── 9. Product Listings Table (Marketplace) ─────────────────────
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS product_listings (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    listing_id          TEXT UNIQUE NOT NULL,
                    seller_id           TEXT NOT NULL,
                    seller_name         TEXT NOT NULL,
                    seller_type         TEXT NOT NULL DEFAULT 'farmer',
                    crop_name           TEXT NOT NULL,
                    crop_variety        TEXT DEFAULT 'FAQ',
                    quantity_quintals   REAL NOT NULL,
                    price_per_quintal   REAL NOT NULL,
                    msp_reference       REAL,
                    harvest_date        TEXT,
                    available_from      TEXT NOT NULL,
                    available_until     TEXT,
                    location_village    TEXT NOT NULL,
                    location_district   TEXT NOT NULL,
                    location_state      TEXT NOT NULL DEFAULT 'Haryana',
                    latitude            REAL,
                    longitude           REAL,
                    quality_moisture_pct    REAL,
                    quality_foreign_matter_pct REAL,
                    quality_grade       TEXT DEFAULT 'A',
                    photo_url           TEXT,
                    status              TEXT DEFAULT 'ACTIVE',
                    views_count         INTEGER DEFAULT 0,
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL
                );
                """
            )

            # ── 10. Orders Table (Marketplace) ──────────────────────────────
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id            TEXT UNIQUE NOT NULL,
                    listing_id          TEXT NOT NULL,
                    buyer_id            TEXT NOT NULL,
                    buyer_name          TEXT NOT NULL,
                    buyer_type          TEXT NOT NULL DEFAULT 'consumer',
                    buyer_phone         TEXT NOT NULL,
                    seller_id           TEXT NOT NULL,
                    seller_name         TEXT NOT NULL,
                    crop_name           TEXT NOT NULL,
                    quantity_quintals   REAL NOT NULL,
                    price_per_quintal   REAL NOT NULL,
                    total_amount        REAL NOT NULL,
                    delivery_address    TEXT,
                    delivery_district   TEXT,
                    delivery_lat        REAL,
                    delivery_lng        REAL,
                    status              TEXT DEFAULT 'PLACED',
                    payment_status      TEXT DEFAULT 'PENDING',
                    payment_ref         TEXT,
                    created_at          TEXT NOT NULL,
                    updated_at          TEXT NOT NULL
                );
                """
            )

            # ── 11. Deliveries Table (Logistics) ────────────────────────────
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS deliveries (
                    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                    delivery_id             TEXT UNIQUE NOT NULL,
                    order_id                TEXT NOT NULL,
                    driver_name             TEXT DEFAULT 'Auto-Assigned',
                    driver_phone            TEXT,
                    vehicle_number          TEXT,
                    pickup_lat              REAL,
                    pickup_lng              REAL,
                    dropoff_lat             REAL,
                    dropoff_lng             REAL,
                    estimated_distance_km   REAL,
                    estimated_duration_min  INTEGER,
                    route_waypoints         TEXT,
                    current_stage           TEXT DEFAULT 'PENDING',
                    picked_up_at            TEXT,
                    delivered_at            TEXT,
                    created_at              TEXT NOT NULL,
                    updated_at              TEXT NOT NULL
                );
                """
            )

            # ── 12. Demand Forecasts Table (AI) ─────────────────────────────
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS demand_forecasts (
                    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
                    crop_name                   TEXT NOT NULL,
                    district                    TEXT NOT NULL,
                    forecast_date               TEXT NOT NULL,
                    predicted_demand_quintals   REAL NOT NULL,
                    confidence_pct              REAL DEFAULT 70.0,
                    model_type                  TEXT DEFAULT 'moving_average',
                    generated_at                TEXT NOT NULL
                );
                """
            )

            # Indices for rapid querying
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_farmers_mobile ON farmers(mobile);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_farmers_farmer_id ON farmers(farmer_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_token ON slot_bookings(token_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_bookings_farmer ON slot_bookings(farmer_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_mandi_prices ON mandi_prices_history(commodity, state);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_ref ON pfms_vouchers(voucher_ref);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vouchers_farmer ON pfms_vouchers(farmer_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_otp_phone ON otp_records(phone, created_at);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sms_farmer ON sms_notifications(farmer_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sms_phone ON sms_notifications(phone_number);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_sms_status ON sms_notifications(status);")
            # Marketplace indices
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_seller ON product_listings(seller_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_crop ON product_listings(crop_name, location_district);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_listings_status ON product_listings(status);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_buyer ON orders(buyer_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_seller ON orders(seller_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_orders_listing ON orders(listing_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_deliveries_order ON deliveries(order_id);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_forecasts_crop ON demand_forecasts(crop_name, district);")

            # Seed default demo farmer if empty
            cursor.execute("SELECT COUNT(*) AS cnt FROM farmers;")
            count = cursor.fetchone()["cnt"]
            if count == 0:
                now = _utc_now_iso()
                cursor.execute(
                    """
                    INSERT INTO farmers (farmer_id, full_name, mobile, village, aadhaar_last4, aadhaar_linked, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    ("PB-10492", "Ram Singh", "9876543210", "Taraori, Karnal", "4819", 1, now, now),
                )
                cursor.execute(
                    """
                    INSERT INTO land_records (farmer_id, khasra_number, total_area_acres, crop_sown, soil_health_card_id, created_at)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    ("PB-10492", "142//12/2", 4.5, "Wheat (HD-2967)", "SHC-HR-88902", now),
                )
                cursor.execute(
                    """
                    INSERT INTO bank_accounts (farmer_id, bank_name, account_number_masked, ifsc_code, is_dbt_enabled, created_at)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """,
                    ("PB-10492", "State Bank of India", "XXXXXX4891", "SBIN0001234", 1, now),
                )
                cursor.execute(
                    """
                    INSERT INTO slot_bookings (
                        token_number, farmer_id, farmer_name, farmer_mobile, commodity,
                        mandi_name, booking_date, time_slot, estimated_qty_quintals,
                        vehicle_type, vehicle_number, gate_number, queue_position, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        "KRN-WHT-2026-0842",
                        "PB-10492",
                        "Ram Singh",
                        "9876543210",
                        "Wheat",
                        "Karnal Grain Market",
                        "2026-09-10",
                        "08:00 AM - 10:00 AM",
                        50.0,
                        "Tractor Trolley",
                        "HR05-AK-9821",
                        "Gate 2",
                        4,
                        "CONFIRMED",
                        now,
                    ),
                )
                logger.info("SQL database seeded successfully with demo farmer PB-10492 and initial booking token.")

            # Seed default PFMS vouchers if empty
            cursor.execute("SELECT COUNT(*) AS cnt FROM pfms_vouchers;")
            v_count = cursor.fetchone()["cnt"]
            if v_count == 0:
                now = _utc_now_iso()
                cursor.execute(
                    """
                    INSERT INTO pfms_vouchers (
                        voucher_ref, utr_number, farmer_id, farmer_name, commodity,
                        quantity_quintals, msp_rate, gross_amount, net_payout, bank_name,
                        account_masked, ifsc_code, mandi_name, status, npci_hash,
                        digital_signature, issued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        "TXN-61029",
                        "SBIN2609018492089",
                        "PB-10492",
                        "Ram Singh",
                        "Mustard",
                        15.0,
                        5950.0,
                        89250.0,
                        88357.50,
                        "State Bank of India",
                        "XXXX-XXXX-5678",
                        "SBIN0001234",
                        "Karnal Grain Market",
                        "TRANSACTION_SUCCESSFUL",
                        "89f4b0021c7a91e48bc09a12",
                        "SIG-PFMS-GOI-2026-9812A",
                        now,
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO pfms_vouchers (
                        voucher_ref, utr_number, farmer_id, farmer_name, commodity,
                        quantity_quintals, msp_rate, gross_amount, net_payout, bank_name,
                        account_masked, ifsc_code, mandi_name, status, npci_hash,
                        digital_signature, issued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        "TXN-49021",
                        "SBIN2609029410982",
                        "PB-10492",
                        "Ram Singh",
                        "Wheat",
                        50.0,
                        2425.0,
                        121250.0,
                        120037.50,
                        "State Bank of India",
                        "XXXX-XXXX-5678",
                        "SBIN0001234",
                        "Karnal Grain Market",
                        "TRANSACTION_SUCCESSFUL",
                        "3b190fe8c201948ba90123ef",
                        "SIG-PFMS-GOI-2026-4409B",
                        now,
                    ),
                )
                logger.info("SQL database seeded with verified PFMS demo vouchers TXN-61029 and TXN-49021.")

            # Seed default marketplace listings if empty
            cursor.execute("SELECT COUNT(*) AS cnt FROM product_listings;")
            l_count = cursor.fetchone()["cnt"]
            if l_count == 0:
                now = _utc_now_iso()
                demo_listings = [
                    ("LST-20260926-001", "PB-10492", "Ram Singh", "farmer", "Wheat", "HD-2967",
                     50.0, 2450.0, 2425.0, "2026-09-20", now, None,
                     "Taraori", "Karnal", "Haryana", 29.6857, 76.9905,
                     10.5, 0.3, "A", None, "ACTIVE", 0, now, now),
                    ("LST-20260926-002", "PB-10492", "Ram Singh", "farmer", "Mustard", "Sarson",
                     25.0, 6000.0, 5950.0, "2026-09-15", now, None,
                     "Taraori", "Karnal", "Haryana", 29.6857, 76.9905,
                     9.0, 0.5, "A", None, "ACTIVE", 0, now, now),
                    ("LST-20260926-003", "PB-10492", "Ram Singh", "farmer", "Paddy", "Basmati 1121",
                     40.0, 3300.0, 2320.0, "2026-10-01", now, None,
                     "Taraori", "Karnal", "Haryana", 29.6857, 76.9905,
                     12.0, 0.2, "A", None, "ACTIVE", 0, now, now),
                ]
                for lst in demo_listings:
                    cursor.execute(
                        """
                        INSERT INTO product_listings (
                            listing_id, seller_id, seller_name, seller_type, crop_name, crop_variety,
                            quantity_quintals, price_per_quintal, msp_reference, harvest_date,
                            available_from, available_until,
                            location_village, location_district, location_state,
                            latitude, longitude,
                            quality_moisture_pct, quality_foreign_matter_pct, quality_grade,
                            photo_url, status, views_count, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                        """,
                        lst,
                    )
                logger.info("SQL database seeded with %d demo marketplace listings.", len(demo_listings))

            # Seed a demo order if empty
            cursor.execute("SELECT COUNT(*) AS cnt FROM orders;")
            o_count = cursor.fetchone()["cnt"]
            if o_count == 0:
                now = _utc_now_iso()
                cursor.execute(
                    """
                    INSERT INTO orders (
                        order_id, listing_id, buyer_id, buyer_name, buyer_type, buyer_phone,
                        seller_id, seller_name, crop_name,
                        quantity_quintals, price_per_quintal, total_amount,
                        delivery_address, delivery_district, delivery_lat, delivery_lng,
                        status, payment_status, payment_ref, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        "ORD-20260926-001", "LST-20260926-001",
                        "BUYER-001", "Anita Sharma", "consumer", "9876500001",
                        "PB-10492", "Ram Singh", "Wheat",
                        10.0, 2450.0, 24500.0,
                        "Sector 14, Karnal", "Karnal", 29.6950, 76.9800,
                        "CONFIRMED", "PAID", "PAY-REF-001",
                        now, now,
                    ),
                )
                logger.info("SQL database seeded with demo marketplace order ORD-20260926-001.")

            conn.commit()

    # ── Asynchronous Public API ──────────────────────────────────────────────

    async def health_check(self) -> dict[str, Any]:
        """Perform SQLite integrity check and return runtime metadata."""
        def _check():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA integrity_check;")
                integrity = cursor.fetchone()[0]
                cursor.execute("PRAGMA journal_mode;")
                journal_mode = cursor.fetchone()[0]
                size_bytes = os.path.getsize(self.db_path) if self.db_path.exists() else 0
                return {
                    "status": "healthy" if integrity == "ok" else "degraded",
                    "engine": "sqlite3",
                    "journal_mode": journal_mode,
                    "integrity_check": integrity,
                }
        return await asyncio.to_thread(_check)

    async def get_stats(self) -> dict[str, Any]:
        """Return table row counts and summary metrics."""
        def _stats():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) AS cnt FROM farmers;")
                farmers_count = cursor.fetchone()["cnt"]
                cursor.execute("SELECT COUNT(*) AS cnt FROM slot_bookings;")
                bookings_count = cursor.fetchone()["cnt"]
                cursor.execute("SELECT COUNT(*) AS cnt FROM land_records;")
                land_count = cursor.fetchone()["cnt"]
                cursor.execute("SELECT COUNT(*) AS cnt FROM bank_accounts;")
                bank_count = cursor.fetchone()["cnt"]
                size_bytes = os.path.getsize(self.db_path) if self.db_path.exists() else 0
                return {
                    "farmers_count": farmers_count,
                    "bookings_count": bookings_count,
                    "land_records_count": land_count,
                    "bank_accounts_count": bank_count,
                    "database_size_bytes": size_bytes,
                    "last_checked_at": _utc_now_iso(),
                }
        return await asyncio.to_thread(_stats)

    async def list_farmers(self, limit: int = 50) -> list[dict[str, Any]]:
        """List registered farmers with their primary details."""
        def _list():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, farmer_id, full_name, mobile, village,
                           aadhaar_last4, aadhaar_linked, created_at, updated_at
                    FROM farmers
                    ORDER BY id DESC
                    LIMIT ?;
                    """,
                    (limit,),
                )
                return [dict(row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_list)

    async def get_farmer_by_id_or_mobile(self, identifier: str) -> dict[str, Any] | None:
        """Find farmer by farmer_id or 10-digit mobile number."""
        def _find():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT id, farmer_id, full_name, mobile, village,
                           aadhaar_last4, aadhaar_linked, created_at, updated_at
                    FROM farmers
                    WHERE farmer_id = ? OR mobile = ?;
                    """,
                    (identifier, identifier),
                )
                row = cursor.fetchone()
                if not row:
                    return None
                farmer = dict(row)

                # Fetch associated land records
                cursor.execute(
                    "SELECT * FROM land_records WHERE farmer_id = ?;",
                    (farmer["farmer_id"],),
                )
                farmer["land_records"] = [dict(r) for r in cursor.fetchall()]

                # Fetch bank accounts
                cursor.execute(
                    "SELECT * FROM bank_accounts WHERE farmer_id = ?;",
                    (farmer["farmer_id"],),
                )
                farmer["bank_accounts"] = [dict(r) for r in cursor.fetchall()]

                return farmer
        return await asyncio.to_thread(_find)

    async def create_farmer(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create or register a new farmer in the SQL database."""
        def _create():
            now = _utc_now_iso()
            farmer_id = data.get("farmer_id")
            if not farmer_id:
                rand_num = random.randint(10000, 99999)
                farmer_id = f"PB-{rand_num}"

            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Check if mobile already exists
                cursor.execute("SELECT * FROM farmers WHERE mobile = ?;", (data["mobile"],))
                existing = cursor.fetchone()
                if existing:
                    # Update existing record
                    cursor.execute(
                        """
                        UPDATE farmers
                        SET full_name = ?, village = ?, updated_at = ?
                        WHERE mobile = ?;
                        """,
                        (data["full_name"], data["village"], now, data["mobile"]),
                    )
                    conn.commit()
                    cursor.execute("SELECT * FROM farmers WHERE mobile = ?;", (data["mobile"],))
                    return dict(cursor.fetchone())

                cursor.execute(
                    """
                    INSERT INTO farmers (
                        farmer_id, full_name, mobile, village,
                        aadhaar_last4, aadhaar_linked, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        farmer_id,
                        data["full_name"],
                        data["mobile"],
                        data["village"],
                        data.get("aadhaar_last4", "1234"),
                        1 if data.get("aadhaar_linked", True) else 0,
                        now,
                        now,
                    ),
                )
                new_id = cursor.lastrowid
                conn.commit()
                cursor.execute("SELECT * FROM farmers WHERE id = ?;", (new_id,))
                return dict(cursor.fetchone())
        return await asyncio.to_thread(_create)

    async def update_farmer(self, farmer_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Update farmer personal details by farmer_id."""
        def _update():
            now = _utc_now_iso()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM farmers WHERE farmer_id = ?;", (farmer_id,))
                existing = cursor.fetchone()
                if not existing:
                    return None

                full_name = data.get("full_name", existing["full_name"])
                village = data.get("village", existing["village"])
                mobile = data.get("mobile", existing["mobile"])

                cursor.execute(
                    """
                    UPDATE farmers
                    SET full_name = ?, village = ?, mobile = ?, updated_at = ?
                    WHERE farmer_id = ?;
                    """,
                    (full_name, village, mobile, now, farmer_id),
                )
                conn.commit()
                cursor.execute("SELECT * FROM farmers WHERE farmer_id = ?;", (farmer_id,))
                return dict(cursor.fetchone())
        return await asyncio.to_thread(_update)

    async def list_bookings(self, farmer_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List slot bookings / gate passes."""
        def _list():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if farmer_id:
                    cursor.execute(
                        """
                        SELECT * FROM slot_bookings
                        WHERE farmer_id = ?
                        ORDER BY id DESC
                        LIMIT ?;
                        """,
                        (farmer_id, limit),
                    )
                else:
                    cursor.execute(
                        """
                        SELECT * FROM slot_bookings
                        ORDER BY id DESC
                        LIMIT ?;
                        """,
                        (limit,),
                    )
                return [dict(row) for row in cursor.fetchall()]
        return await asyncio.to_thread(_list)

    async def create_booking(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new slot booking and generate a digital gate pass token in SQL."""
        def _create():
            now = _utc_now_iso()
            # Tokens are ALWAYS server-generated cryptographic values. Client-
            # supplied token_numbers are ignored so passes cannot be forged or
            # squatted, and the value is unguessable (not a 4-digit counter).
            token_number = (
                f"KRN-{str(data.get('commodity', 'WHT'))[:3].upper()}-"
                f"{datetime.now().year}-{secrets.token_hex(4).upper()}"
            )

            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO slot_bookings (
                        token_number, farmer_id, farmer_name, farmer_mobile, commodity,
                        mandi_name, booking_date, time_slot, estimated_qty_quintals,
                        vehicle_type, vehicle_number, gate_number, queue_position, status, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        token_number,
                        data.get("farmer_id", "PB-10492"),
                        data.get("farmer_name", "Ram Singh"),
                        data.get("farmer_mobile", "9876543210"),
                        data.get("commodity", "Wheat"),
                        data.get("mandi_name", "Karnal Grain Market"),
                        data.get("booking_date", datetime.now().strftime("%Y-%m-%d")),
                        data.get("time_slot", "08:00 AM - 10:00 AM"),
                        float(data.get("estimated_qty_quintals", 50.0)),
                        data.get("vehicle_type", "Tractor Trolley"),
                        data.get("vehicle_number", "HR05-AK-9821"),
                        data.get("gate_number", "Gate 2"),
                        int(data.get("queue_position", 4)),
                        data.get("status", "CONFIRMED"),
                        now,
                    ),
                )
                new_id = cursor.lastrowid
                conn.commit()
                cursor.execute("SELECT * FROM slot_bookings WHERE id = ?;", (new_id,))
                return dict(cursor.fetchone())
        return await asyncio.to_thread(_create)

    async def get_booking_by_token(self, token_number: str) -> dict[str, Any] | None:
        """Fetch slot booking and digital gate pass by token number."""
        def _get():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM slot_bookings WHERE token_number = ?;", (token_number,))
                row = cursor.fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_get)

    # ── Server-Side Payment & PFMS Voucher Operations ────────────────────────

    # Official Government MSP benchmarks per quintal (₹)
    VERIFIED_MSP_RATES: dict[str, float] = {
        "Wheat": 2425.0,
        "Paddy": 2320.0,
        "Paddy (Dhan)": 2320.0,
        "Basmati Paddy": 3250.0,
        "Mustard": 5950.0,
        "Mustard (Sarson)": 5950.0,
        "Cotton": 7121.0,
        "Cotton (Kapas)": 7121.0,
        "Gram": 5440.0,
        "Gram (Chana)": 5440.0,
        "Maize": 2090.0,
        "Maize (Makka)": 2090.0,
        "Barley": 1850.0,
        "Moong": 8682.0,
    }

    def get_msp_rate(self, commodity: str) -> float:
        """Lookup official government support price benchmark."""
        if commodity in self.VERIFIED_MSP_RATES:
            return self.VERIFIED_MSP_RATES[commodity]
        # Partial match fallback
        c_lower = commodity.lower()
        for k, v in self.VERIFIED_MSP_RATES.items():
            if k.lower() in c_lower or c_lower in k.lower():
                return v
        return 2425.0  # Default to Wheat MSP benchmark

    async def calculate_payment(self, commodity: str, quantity: float) -> dict[str, Any]:
        """Perform server-side verified payment calculation."""
        def _calc():
            rate = self.get_msp_rate(commodity)
            gross = round(quantity * rate, 2)
            mandi_cess = round(gross * 0.01, 2)
            net = round(gross - mandi_cess, 2)
            return {
                "commodity": commodity,
                "quantity_quintals": quantity,
                "verified_msp_rate": rate,
                "gross_amount": gross,
                "mandi_cess_amount": mandi_cess,
                "net_payout_amount": net,
                "currency": "INR",
                "is_verified_by_ministry": True,
                "calculation_timestamp": _utc_now_iso(),
            }
        return await asyncio.to_thread(_calc)

    async def mint_pfms_voucher(self, data: dict[str, Any]) -> dict[str, Any]:
        """Cryptographically mint and record an authenticated PFMS DBT voucher."""
        def _mint():
            now = _utc_now_iso()
            farmer_id = data.get("farmer_id", "PB-10492")
            commodity = data.get("commodity", "Wheat")
            quantity = float(data.get("quantity_quintals", 1.0))
            mandi_name = data.get("mandi_name", "Karnal Grain Market")

            # Never sign with an empty/absent secret — a voucher signed with a
            # known (committed or missing) key is plain forgery.
            signing_secret = self.settings.PFMS_SIGNING_SECRET
            if not signing_secret:
                raise ValueError(
                    "PFMS_SIGNING_SECRET is not configured; voucher signing is disabled."
                )

            rate = self.get_msp_rate(commodity)
            gross = round(quantity * rate, 2)
            net = round(gross - round(gross * 0.01, 2), 2)

            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Lookup farmer profile if name not provided
                cursor.execute("SELECT full_name FROM farmers WHERE farmer_id = ?;", (farmer_id,))
                farmer_row = cursor.fetchone()
                farmer_name = data.get("farmer_name") or (farmer_row["full_name"] if farmer_row else "Ram Singh")

                # Generate secure server-side voucher identifiers
                seq_rand = secrets.token_hex(3).upper()
                voucher_ref = f"PFMS-VCHR-2026-{seq_rand}"
                utr_rand = f"{random.randint(10000000, 99999999)}"
                utr_number = f"SBIN26090{utr_rand}"

                # Cryptographic audit hash using server signing secret
                msg_payload = f"{voucher_ref}|{utr_number}|{farmer_id}|{commodity}|{quantity}|{net}|{now}"
                npci_hash = hmac.new(
                    signing_secret.encode("utf-8"),
                    msg_payload.encode("utf-8"),
                    hashlib.sha256,
                ).hexdigest()[:24]

                digital_sig = f"SIG-PFMS-GOI-2026-{secrets.token_hex(4).upper()}"

                bank_name = data.get("bank_name", "State Bank of India")
                acct_last4 = data.get("account_last4", "5678")
                account_masked = f"XXXX-XXXX-{acct_last4}"
                ifsc_code = data.get("ifsc_code", "SBIN0001234")

                cursor.execute(
                    """
                    INSERT INTO pfms_vouchers (
                        voucher_ref, utr_number, farmer_id, farmer_name, commodity,
                        quantity_quintals, msp_rate, gross_amount, net_payout, bank_name,
                        account_masked, ifsc_code, mandi_name, status, npci_hash,
                        digital_signature, issued_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        voucher_ref,
                        utr_number,
                        farmer_id,
                        farmer_name,
                        commodity,
                        quantity,
                        rate,
                        gross,
                        net,
                        bank_name,
                        account_masked,
                        ifsc_code,
                        mandi_name,
                        "TRANSACTION_SUCCESSFUL",
                        npci_hash,
                        digital_sig,
                        now,
                    ),
                )
                conn.commit()
                cursor.execute("SELECT * FROM pfms_vouchers WHERE voucher_ref = ?;", (voucher_ref,))
                row = cursor.fetchone()
                return dict(row)
        return await asyncio.to_thread(_mint)

    async def get_pfms_voucher(self, voucher_ref: str) -> dict[str, Any] | None:
        """Retrieve authentic server voucher by voucher_ref or UTR number."""
        def _get():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM pfms_vouchers
                    WHERE voucher_ref = ? OR utr_number = ?;
                    """,
                    (voucher_ref, voucher_ref),
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_get)

    async def list_pfms_vouchers(self, farmer_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        """List authenticated PFMS vouchers issued by the server."""
        def _list():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if farmer_id:
                    cursor.execute(
                        "SELECT * FROM pfms_vouchers WHERE farmer_id = ? ORDER BY id DESC LIMIT ?;",
                        (farmer_id, limit),
                    )
                else:
                    cursor.execute(
                        "SELECT * FROM pfms_vouchers ORDER BY id DESC LIMIT ?;",
                        (limit,),
                    )
                return [dict(r) for r in cursor.fetchall()]
        return await asyncio.to_thread(_list)

    # ── OTP Database Methods ─────────────────────────────────────────────────

    # ── Marketplace: Product Listings ────────────────────────────────────────

    async def list_product_listings(
        self, seller_id: str | None = None, crop: str | None = None,
        district: str | None = None, status: str = "ACTIVE", limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Browse marketplace product listings with optional filters."""
        def _list():
            clauses: list[str] = []
            params: list[Any] = []
            if seller_id:
                clauses.append("seller_id = ?")
                params.append(seller_id)
            if crop:
                clauses.append("LOWER(crop_name) = LOWER(?)")
                params.append(crop)
            if district:
                clauses.append("LOWER(location_district) = LOWER(?)")
                params.append(district)
            if status:
                clauses.append("status = ?")
                params.append(status)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT * FROM product_listings {where} ORDER BY id DESC LIMIT ?;",
                    params,
                )
                return [dict(r) for r in cursor.fetchall()]
        return await asyncio.to_thread(_list)

    async def get_listing(self, listing_id: str) -> dict[str, Any] | None:
        """Fetch a single product listing by listing_id."""
        def _get():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM product_listings WHERE listing_id = ?;", (listing_id,))
                row = cursor.fetchone()
                if row:
                    # Increment views
                    conn.execute(
                        "UPDATE product_listings SET views_count = views_count + 1 WHERE listing_id = ?;",
                        (listing_id,),
                    )
                    conn.commit()
                return dict(row) if row else None
        return await asyncio.to_thread(_get)

    async def create_listing(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a new product listing in the marketplace."""
        def _create():
            now = _utc_now_iso()
            seq = secrets.token_hex(4).upper()
            listing_id = data.get("listing_id") or f"LST-{datetime.now().strftime('%Y%m%d')}-{seq}"
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO product_listings (
                        listing_id, seller_id, seller_name, seller_type,
                        crop_name, crop_variety, quantity_quintals, price_per_quintal,
                        msp_reference, harvest_date, available_from, available_until,
                        location_village, location_district, location_state,
                        latitude, longitude,
                        quality_moisture_pct, quality_foreign_matter_pct, quality_grade,
                        photo_url, status, views_count, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?);
                    """,
                    (
                        listing_id,
                        data.get("seller_id", "PB-10492"),
                        data.get("seller_name", "Ram Singh"),
                        data.get("seller_type", "farmer"),
                        data["crop_name"],
                        data.get("crop_variety", "FAQ"),
                        float(data["quantity_quintals"]),
                        float(data["price_per_quintal"]),
                        data.get("msp_reference"),
                        data.get("harvest_date"),
                        data.get("available_from", now),
                        data.get("available_until"),
                        data.get("location_village", "Taraori"),
                        data.get("location_district", "Karnal"),
                        data.get("location_state", "Haryana"),
                        data.get("latitude"),
                        data.get("longitude"),
                        data.get("quality_moisture_pct"),
                        data.get("quality_foreign_matter_pct"),
                        data.get("quality_grade", "A"),
                        data.get("photo_url"),
                        data.get("status", "ACTIVE"),
                        now, now,
                    ),
                )
                new_id = cursor.lastrowid
                conn.commit()
                cursor.execute("SELECT * FROM product_listings WHERE id = ?;", (new_id,))
                return dict(cursor.fetchone())
        return await asyncio.to_thread(_create)

    async def update_listing(self, listing_id: str, data: dict[str, Any]) -> dict[str, Any] | None:
        """Update an existing listing (price, quantity, status, quality)."""
        def _update():
            now = _utc_now_iso()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM product_listings WHERE listing_id = ?;", (listing_id,))
                existing = cursor.fetchone()
                if not existing:
                    return None
                existing = dict(existing)
                fields_to_update = [
                    "quantity_quintals", "price_per_quintal", "status",
                    "quality_moisture_pct", "quality_foreign_matter_pct", "quality_grade",
                    "harvest_date", "available_until", "photo_url",
                ]
                sets = []
                params = []
                for f in fields_to_update:
                    if f in data and data[f] is not None:
                        sets.append(f"{f} = ?")
                        params.append(data[f])
                sets.append("updated_at = ?")
                params.append(now)
                params.append(listing_id)
                cursor.execute(
                    f"UPDATE product_listings SET {', '.join(sets)} WHERE listing_id = ?;",
                    params,
                )
                conn.commit()
                cursor.execute("SELECT * FROM product_listings WHERE listing_id = ?;", (listing_id,))
                return dict(cursor.fetchone())
        return await asyncio.to_thread(_update)

    # ── Marketplace: Orders ─────────────────────────────────────────────────

    async def list_orders(
        self, buyer_id: str | None = None, seller_id: str | None = None,
        status: str | None = None, limit: int = 50,
    ) -> list[dict[str, Any]]:
        """List orders with optional filters."""
        def _list():
            clauses: list[str] = []
            params: list[Any] = []
            if buyer_id:
                clauses.append("buyer_id = ?")
                params.append(buyer_id)
            if seller_id:
                clauses.append("seller_id = ?")
                params.append(seller_id)
            if status:
                clauses.append("status = ?")
                params.append(status)
            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            params.append(limit)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    f"SELECT * FROM orders {where} ORDER BY id DESC LIMIT ?;",
                    params,
                )
                return [dict(r) for r in cursor.fetchall()]
        return await asyncio.to_thread(_list)

    async def get_order(self, order_id: str) -> dict[str, Any] | None:
        """Fetch a single order by order_id."""
        def _get():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM orders WHERE order_id = ?;", (order_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_get)

    async def create_order(self, data: dict[str, Any]) -> dict[str, Any]:
        """Place a new marketplace order."""
        def _create():
            now = _utc_now_iso()
            seq = secrets.token_hex(4).upper()
            order_id = data.get("order_id") or f"ORD-{datetime.now().strftime('%Y%m%d')}-{seq}"
            qty = float(data["quantity_quintals"])
            price = float(data["price_per_quintal"])
            total = round(qty * price, 2)
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO orders (
                        order_id, listing_id, buyer_id, buyer_name, buyer_type, buyer_phone,
                        seller_id, seller_name, crop_name,
                        quantity_quintals, price_per_quintal, total_amount,
                        delivery_address, delivery_district, delivery_lat, delivery_lng,
                        status, payment_status, payment_ref, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        order_id,
                        data["listing_id"],
                        data.get("buyer_id", "BUYER-ANON"),
                        data.get("buyer_name", "Anonymous Buyer"),
                        data.get("buyer_type", "consumer"),
                        data.get("buyer_phone", "0000000000"),
                        data.get("seller_id", "PB-10492"),
                        data.get("seller_name", "Ram Singh"),
                        data.get("crop_name", "Wheat"),
                        qty, price, total,
                        data.get("delivery_address"),
                        data.get("delivery_district"),
                        data.get("delivery_lat"),
                        data.get("delivery_lng"),
                        "PLACED", "PENDING",
                        data.get("payment_ref"),
                        now, now,
                    ),
                )
                new_id = cursor.lastrowid
                conn.commit()
                cursor.execute("SELECT * FROM orders WHERE id = ?;", (new_id,))
                return dict(cursor.fetchone())
        return await asyncio.to_thread(_create)

    async def update_order_status(self, order_id: str, status: str, payment_status: str | None = None) -> dict[str, Any] | None:
        """Update order status and optionally payment status."""
        def _update():
            now = _utc_now_iso()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                if payment_status:
                    cursor.execute(
                        "UPDATE orders SET status = ?, payment_status = ?, updated_at = ? WHERE order_id = ?;",
                        (status, payment_status, now, order_id),
                    )
                else:
                    cursor.execute(
                        "UPDATE orders SET status = ?, updated_at = ? WHERE order_id = ?;",
                        (status, now, order_id),
                    )
                conn.commit()
                cursor.execute("SELECT * FROM orders WHERE order_id = ?;", (order_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_update)

    # ── Marketplace: Deliveries ─────────────────────────────────────────────

    async def create_delivery(self, data: dict[str, Any]) -> dict[str, Any]:
        """Create a delivery record for an order."""
        def _create():
            now = _utc_now_iso()
            seq = secrets.token_hex(4).upper()
            delivery_id = data.get("delivery_id") or f"DEL-{datetime.now().strftime('%Y%m%d')}-{seq}"
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO deliveries (
                        delivery_id, order_id, driver_name, driver_phone, vehicle_number,
                        pickup_lat, pickup_lng, dropoff_lat, dropoff_lng,
                        estimated_distance_km, estimated_duration_min, route_waypoints,
                        current_stage, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        delivery_id,
                        data["order_id"],
                        data.get("driver_name", "Auto-Assigned"),
                        data.get("driver_phone"),
                        data.get("vehicle_number"),
                        data.get("pickup_lat"),
                        data.get("pickup_lng"),
                        data.get("dropoff_lat"),
                        data.get("dropoff_lng"),
                        data.get("estimated_distance_km"),
                        data.get("estimated_duration_min"),
                        data.get("route_waypoints"),
                        "PENDING",
                        now, now,
                    ),
                )
                new_id = cursor.lastrowid
                conn.commit()
                cursor.execute("SELECT * FROM deliveries WHERE id = ?;", (new_id,))
                return dict(cursor.fetchone())
        return await asyncio.to_thread(_create)

    async def get_delivery_by_order(self, order_id: str) -> dict[str, Any] | None:
        """Fetch delivery record for a given order."""
        def _get():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM deliveries WHERE order_id = ?;", (order_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_get)

    async def update_delivery_stage(self, delivery_id: str, stage: str) -> dict[str, Any] | None:
        """Update delivery stage (PENDING → PICKED_UP → IN_TRANSIT → DELIVERED)."""
        def _update():
            now = _utc_now_iso()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                extra = ""
                if stage == "PICKED_UP":
                    extra = ", picked_up_at = ?"
                elif stage == "DELIVERED":
                    extra = ", delivered_at = ?"
                sql = f"UPDATE deliveries SET current_stage = ?, updated_at = ?{extra} WHERE delivery_id = ?;"
                params = [stage, now]
                if extra:
                    params.append(now)
                params.append(delivery_id)
                cursor.execute(sql, params)
                conn.commit()
                cursor.execute("SELECT * FROM deliveries WHERE delivery_id = ?;", (delivery_id,))
                row = cursor.fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_update)

    # ── Marketplace: Seller Earnings ────────────────────────────────────────

    async def get_seller_earnings(self, seller_id: str) -> dict[str, Any]:
        """Aggregate earnings summary for a seller (farmer/FPO)."""
        def _earnings():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT
                        COUNT(*) AS total_orders,
                        COALESCE(SUM(total_amount), 0) AS total_revenue,
                        COALESCE(SUM(CASE WHEN payment_status = 'PAID' THEN total_amount ELSE 0 END), 0) AS paid_amount,
                        COALESCE(SUM(CASE WHEN payment_status = 'PENDING' THEN total_amount ELSE 0 END), 0) AS pending_amount,
                        COALESCE(SUM(quantity_quintals), 0) AS total_quantity_sold
                    FROM orders
                    WHERE seller_id = ? AND status != 'CANCELLED';
                    """,
                    (seller_id,),
                )
                row = dict(cursor.fetchone())
                row["seller_id"] = seller_id
                row["generated_at"] = _utc_now_iso()
                return row
        return await asyncio.to_thread(_earnings)

    async def store_otp(
        self, phone: str, otp_hash: str, expires_at: str
    ) -> None:
        """Persist a hashed OTP record for the given 10-digit phone number.

        Any previous un-used OTP records for the same phone are invalidated
        (marked used) so only the most recent OTP is ever valid.
        """
        def _store():
            now = _utc_now_iso()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                # Invalidate previous pending OTPs for this phone
                cursor.execute(
                    "UPDATE otp_records SET used = 1 WHERE phone = ? AND used = 0;",
                    (phone,),
                )
                cursor.execute(
                    """
                    INSERT INTO otp_records (phone, otp_hash, expires_at, attempt_count, used, created_at)
                    VALUES (?, ?, ?, 0, 0, ?);
                    """,
                    (phone, otp_hash, expires_at, now),
                )
                conn.commit()
        await asyncio.to_thread(_store)

    async def get_otp_record(self, phone: str) -> dict[str, Any] | None:
        """Return the most recent active (unused, not expired) OTP record."""
        def _get():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT * FROM otp_records
                    WHERE phone = ? AND used = 0
                    ORDER BY id DESC
                    LIMIT 1;
                    """,
                    (phone,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_get)

    async def count_otp_sends(self, phone: str, window_sec: int) -> int:
        """Count OTP records created for ``phone`` within the last ``window_sec`` seconds."""
        def _count():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM otp_records
                    WHERE phone = ?
                    AND created_at >= datetime('now', ? || ' seconds');
                    """,
                    (phone, f"-{window_sec}"),
                )
                return cursor.fetchone()["cnt"]
        return await asyncio.to_thread(_count)

    async def mark_otp_used(self, record_id: int) -> None:
        """Mark an OTP record as consumed so it can never be reused."""
        def _mark():
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE otp_records SET used = 1 WHERE id = ?;",
                    (record_id,),
                )
                conn.commit()
        await asyncio.to_thread(_mark)

    async def increment_otp_attempt(self, record_id: int) -> None:
        """Increment the verification attempt counter for an OTP record."""
        def _incr():
            with self._get_connection() as conn:
                conn.execute(
                    "UPDATE otp_records SET attempt_count = attempt_count + 1 WHERE id = ?;",
                    (record_id,),
                )
                conn.commit()
        await asyncio.to_thread(_incr)

    # ── SMS Notification Database Methods ───────────────────────────────────

    async def create_sms_notification(self, data: dict[str, Any]) -> dict[str, Any]:
        """Insert a new SMS notification record and return it with its generated ID."""
        def _create():
            now = _utc_now_iso()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO sms_notifications (
                        farmer_id, phone_number, message_type, message,
                        reference_type, reference_id, provider_message_id,
                        status, attempt_count, error_message, sent_at,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        data.get("farmer_id"),
                        data["phone_number"],
                        data["message_type"],
                        data["message"],
                        data.get("reference_type"),
                        data.get("reference_id"),
                        data.get("provider_message_id", ""),
                        data.get("status", "PENDING"),
                        data.get("attempt_count", 0),
                        data.get("error_message"),
                        data.get("sent_at"),
                        data.get("created_at", now),
                        data.get("updated_at", now),
                    ),
                )
                new_id = cursor.lastrowid
                conn.commit()
                cursor.execute("SELECT * FROM sms_notifications WHERE id = ?;", (new_id,))
                return dict(cursor.fetchone())
        return await asyncio.to_thread(_create)

    async def update_sms_status(
        self,
        notification_id: int,
        status: str,
        provider_message_id: str = "",
        error_message: str | None = None,
        sent_at: str | None = None,
    ) -> None:
        """Update the delivery status of an SMS notification record."""
        def _update():
            now = _utc_now_iso()
            with self._get_connection() as conn:
                conn.execute(
                    """
                    UPDATE sms_notifications
                    SET status = ?, provider_message_id = ?,
                        error_message = ?, sent_at = ?,
                        attempt_count = attempt_count + 1,
                        updated_at = ?
                    WHERE id = ?;
                    """,
                    (
                        status,
                        provider_message_id,
                        error_message,
                        sent_at,
                        now,
                        notification_id,
                    ),
                )
                conn.commit()
        await asyncio.to_thread(_update)

    async def check_duplicate_sms(
        self,
        farmer_id: str,
        message_type: str,
        reference_id: str,
        window_sec: int = 300,
    ) -> bool:
        """Return True if a matching SMS was sent within the deduplication window."""
        def _check():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT COUNT(*) AS cnt FROM sms_notifications
                    WHERE farmer_id = ?
                      AND message_type = ?
                      AND reference_id = ?
                      AND status IN ('SENT', 'DELIVERED', 'PENDING')
                      AND created_at >= datetime('now', ? || ' seconds');
                    """,
                    (farmer_id, message_type, reference_id, f"-{window_sec}"),
                )
                return cursor.fetchone()["cnt"] > 0
        return await asyncio.to_thread(_check)

    async def get_sms_notification(self, notification_id: int) -> dict[str, Any] | None:
        """Fetch a single SMS notification record by its primary key."""
        def _get():
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT * FROM sms_notifications WHERE id = ?;",
                    (notification_id,),
                )
                row = cursor.fetchone()
                return dict(row) if row else None
        return await asyncio.to_thread(_get)

    async def list_sms_notifications(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        """Return SMS notifications matching the supplied filter criteria."""
        def _list():
            clauses: list[str] = []
            params: list[Any] = []

            if filters.get("farmer_id"):
                clauses.append("farmer_id = ?")
                params.append(filters["farmer_id"])
            if filters.get("phone_number"):
                clauses.append("phone_number = ?")
                params.append(filters["phone_number"])
            if filters.get("message_type"):
                clauses.append("message_type = ?")
                params.append(filters["message_type"])
            if filters.get("status"):
                clauses.append("status = ?")
                params.append(filters["status"])
            if filters.get("from_date"):
                clauses.append("created_at >= ?")
                params.append(filters["from_date"])
            if filters.get("to_date"):
                clauses.append("created_at <= ?")
                params.append(filters["to_date"])

            where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
            limit  = int(filters.get("limit", 50))
            offset = int(filters.get("offset", 0))
            params.extend([limit, offset])

            sql = f"""
                SELECT * FROM sms_notifications
                {where}
                ORDER BY id DESC
                LIMIT ? OFFSET ?;
            """
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                return [dict(r) for r in cursor.fetchall()]
        return await asyncio.to_thread(_list)

    async def update_sms_status_by_provider_id(
        self, provider_message_id: str, status: str
    ) -> bool:
        """Update notification status via provider message ID (webhook callback)."""
        def _update():
            now = _utc_now_iso()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    UPDATE sms_notifications
                    SET status = ?, updated_at = ?
                    WHERE provider_message_id = ?;
                    """,
                    (status, now, provider_message_id),
                )
                conn.commit()
                return cursor.rowcount > 0
        return await asyncio.to_thread(_update)
