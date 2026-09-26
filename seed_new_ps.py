import sqlite3
import datetime

db_path = 'app_build/data/kisan_setu.db'
con = sqlite3.connect(db_path)
cur = con.cursor()

# 1. Clear old problem statement tables
cur.execute("DELETE FROM slot_bookings;")
cur.execute("DELETE FROM pfms_vouchers;")
cur.execute("DELETE FROM land_records;")
print("Cleared old problem statement tables (slot_bookings, pfms_vouchers, land_records).")

# 2. Clear and populate product_listings for New PS 26033
cur.execute("DELETE FROM product_listings;")

now = datetime.datetime.now(datetime.timezone.utc).isoformat()
listings = [
    (
        'LST-2026-WHT-01', 'KS-10492', 'Ram Singh', 'farmer',
        'Wheat (गेहूं)', 'Sharbati Premium Grade-A', 150.0, 2480.0, 2425.0,
        '2026-09-24', '2026-09-25', '2026-10-15',
        'Taraori Village', 'Karnal', 'Haryana', 29.8021, 76.9248,
        11.2, 0.4, 'Grade-A (FAQ Certified)',
        'https://images.unsplash.com/photo-1574323347407-f5e1ad6d020b?auto=format&fit=crop&w=400&q=80',
        'ACTIVE', 142, now, now
    ),
    (
        'LST-2026-RIC-02', 'KS-20811', 'Gurpreet Singh Dhillon', 'fpo',
        'Basmati Rice (बासमती चावल)', '1121 Extra Long Grain', 200.0, 3850.0, 3600.0,
        '2026-09-20', '2026-09-22', '2026-10-30',
        'Nissing Sector', 'Karnal', 'Haryana', 29.7421, 76.8123,
        12.0, 0.2, 'Export Grade Premium',
        'https://images.unsplash.com/photo-1586201375761-83865001e31c?auto=format&fit=crop&w=400&q=80',
        'ACTIVE', 289, now, now
    ),
    (
        'LST-2026-MST-03', 'KS-31902', 'Hariram Meena', 'farmer',
        'Mustard (सरसों)', 'Pusa Bold High Oil (42%)', 80.0, 5950.0, 5650.0,
        '2026-09-25', '2026-09-26', '2026-10-20',
        'Gharaunda', 'Karnal', 'Haryana', 29.5398, 76.9734,
        7.5, 0.8, 'Grade-A Oil Content',
        'https://images.unsplash.com/photo-1508746829417-e6f548d8d6ed?auto=format&fit=crop&w=400&q=80',
        'ACTIVE', 98, now, now
    ),
    (
        'LST-2026-TOM-04', 'KS-44120', 'Sukhwinder Kaur', 'farmer',
        'Tomato (टमाटर)', 'Himsona Hybrid Firm Flesh', 45.0, 1820.0, 1600.0,
        '2026-09-26', '2026-09-26', '2026-10-02',
        'Indri Block', 'Karnal', 'Haryana', 29.8821, 77.0612,
        88.0, 0.1, 'Grade-A Table Variety',
        'https://images.unsplash.com/photo-1592924357228-91a4daadcfea?auto=format&fit=crop&w=400&q=80',
        'ACTIVE', 315, now, now
    ),
    (
        'LST-2026-POT-05', 'KS-51009', 'Mahesh Kumar Verma', 'farmer',
        'Potato (आलू)', 'Kufri Jyoti Processing Grade', 300.0, 1420.0, 1250.0,
        '2026-09-22', '2026-09-24', '2026-11-15',
        'Shahabad', 'Kurukshetra', 'Haryana', 30.1682, 76.8712,
        78.0, 0.5, 'Chips Processing FAQ',
        'https://images.unsplash.com/photo-1518977676601-b53f82aba655?auto=format&fit=crop&w=400&q=80',
        'ACTIVE', 174, now, now
    )
]

cur.executemany("""
INSERT INTO product_listings (
    listing_id, seller_id, seller_name, seller_type,
    crop_name, crop_variety, quantity_quintals, price_per_quintal, msp_reference,
    harvest_date, available_from, available_until,
    location_village, location_district, location_state, latitude, longitude,
    quality_moisture_pct, quality_foreign_matter_pct, quality_grade, photo_url,
    status, views_count, created_at, updated_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
""", listings)
print(f"Inserted {len(listings)} active produce listings for PS 26033.")

# 3. Clear and populate orders / negotiations for New PS 26033
cur.execute("DELETE FROM orders;")

orders = [
    (
        'ORD-2026-BB-101', 'LST-2026-WHT-01', 'BUYER-BB-09',
        'BigBasket Institutional Sourcing', 'retail_chain', '+91 98112 00192',
        'KS-10492', 'Ram Singh', 'Wheat (गेहूं)', 100.0, 2460.0, 246000.0,
        'BigBasket Mega Fulfillment Hub, Kundli Sector 57, Sonipat', 'Sonipat',
        28.8712, 77.1294, 'NEGOTIATION_ACTIVE', 'ESCROW_RESERVED', 'ESCROW-BB-8921',
        now, now
    ),
    (
        'ORD-2026-ITC-102', 'LST-2026-RIC-02', 'BUYER-ITC-44',
        'ITC Agri-Business Division (Aashirvaad)', 'fmcg_processor', '+91 98220 44911',
        'KS-20811', 'Gurpreet Singh Dhillon', 'Basmati Rice (बासमती चावल)', 150.0, 3820.0, 573000.0,
        'ITC Processing Plant, GT Road, Karnal', 'Karnal',
        29.6912, 76.9812, 'CONFIRMED', 'ESCROW_FUNDED', 'ESCROW-ITC-9902',
        now, now
    ),
    (
        'ORD-2026-BLK-103', 'LST-2026-TOM-04', 'BUYER-BLK-03',
        'Blinkit Quick Commerce Dark Store', 'quick_commerce', '+91 98771 22390',
        'KS-44120', 'Sukhwinder Kaur', 'Tomato (टमाटर)', 30.0, 1800.0, 54000.0,
        'Blinkit Hub 14, Azadpur Mandi Ring Road, Delhi', 'New Delhi',
        28.7123, 77.1729, 'IN_TRANSIT', 'PAID', 'PAY-BLK-11029',
        now, now
    )
]

cur.executemany("""
INSERT INTO orders (
    order_id, listing_id, buyer_id, buyer_name, buyer_type, buyer_phone,
    seller_id, seller_name, crop_name, quantity_quintals, price_per_quintal,
    total_amount, delivery_address, delivery_district, delivery_lat, delivery_lng,
    status, payment_status, payment_ref, created_at, updated_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
""", orders)
print(f"Inserted {len(orders)} active buyer orders & negotiations for PS 26033.")

# 4. Clear and populate deliveries for New PS 26033
cur.execute("DELETE FROM deliveries;")

deliveries = [
    (
        'DEL-2026-EV-901', 'ORD-2026-BLK-103', 'Manpreet Singh (Driver)', '+91 97120 33912',
        'HR-05-EV-4412 (Euler Turbo EV 3.5T)', 29.8821, 77.0612, 28.7123, 77.1729,
        124.5, 140, 'Karnal Indri -> GT Road NH-44 -> Azadpur Cold Hub', 'IN_TRANSIT',
        now, None, now, now
    ),
    (
        'DEL-2026-EV-902', 'ORD-2026-ITC-102', 'Virender Yadav (Driver)', '+91 99104 55192',
        'HR-05-AG-9912 (Eicher Pro Cold Chain 14ft)', 29.7421, 76.8123, 29.6912, 76.9812,
        28.0, 45, 'Nissing -> Karnal Processing Plant', 'ASSIGNED',
        None, None, now, now
    )
]

cur.executemany("""
INSERT INTO deliveries (
    delivery_id, order_id, driver_name, driver_phone, vehicle_number,
    pickup_lat, pickup_lng, dropoff_lat, dropoff_lng, estimated_distance_km,
    estimated_duration_min, route_waypoints, current_stage, picked_up_at,
    delivered_at, created_at, updated_at
) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?);
""", deliveries)
print(f"Inserted {len(deliveries)} active green logistics dispatches for PS 26033.")

# 5. Populate demand_forecasts for New PS 26033
cur.execute("DELETE FROM demand_forecasts;")

forecasts = [
    ('Wheat (गेहूं)', 'Karnal', '2026-09-30', 4500.0, 94.2, 'ARIMA-Agmarknet-AI', now),
    ('Basmati Rice (बासमती चावल)', 'Karnal', '2026-09-30', 6200.0, 91.8, 'ARIMA-Agmarknet-AI', now),
    ('Mustard (सरसों)', 'Karnal', '2026-09-30', 2800.0, 89.5, 'ARIMA-Agmarknet-AI', now),
    ('Tomato (टमाटर)', 'Delhi NCR', '2026-09-28', 8500.0, 96.0, 'XGBoost-QuickCommerce', now),
    ('Potato (आलू)', 'Delhi NCR', '2026-10-05', 12000.0, 93.4, 'XGBoost-ProcessingFMCG', now),
]

cur.executemany("""
INSERT INTO demand_forecasts (
    crop_name, district, forecast_date, predicted_demand_quintals, confidence_pct, model_type, generated_at
) VALUES (?,?,?,?,?,?,?);
""", forecasts)
print(f"Inserted {len(forecasts)} AI demand forecasts for PS 26033.")

con.commit()
con.close()
print("Database successfully synchronized for PS 26033!")
