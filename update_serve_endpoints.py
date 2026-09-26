with open('serve.py', 'r', encoding='utf-8') as f:
    text = f.read()

# Let's add the GET endpoints for listings, orders, deliveries, forecasts
get_endpoints = """
        # PS 26033: Direct Produce Listings
        elif path in ('/api/v1/listings', '/api/listings'):
            try:
                with db_session() as conn:
                    rows = conn.execute("SELECT * FROM product_listings ORDER BY id DESC").fetchall()
                self._json({"listings": [dict(r) for r in rows], "count": len(rows)})
            except Exception as e:
                self._json({"listings": [], "count": 0, "error": str(e)})

        # PS 26033: Orders and Negotiations
        elif path in ('/api/v1/orders', '/api/orders'):
            try:
                with db_session() as conn:
                    rows = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
                self._json({"orders": [dict(r) for r in rows], "count": len(rows)})
            except Exception as e:
                self._json({"orders": [], "count": 0, "error": str(e)})

        # PS 26033: Green Logistics Deliveries
        elif path in ('/api/v1/deliveries', '/api/deliveries'):
            try:
                with db_session() as conn:
                    rows = conn.execute("SELECT * FROM deliveries ORDER BY id DESC").fetchall()
                self._json({"deliveries": [dict(r) for r in rows], "count": len(rows)})
            except Exception as e:
                self._json({"deliveries": [], "count": 0, "error": str(e)})

        # PS 26033: AI Demand Forecasts
        elif path in ('/api/v1/demand-forecasts', '/api/forecasts'):
            try:
                with db_session() as conn:
                    rows = conn.execute("SELECT * FROM demand_forecasts ORDER BY id DESC").fetchall()
                self._json({"forecasts": [dict(r) for r in rows], "count": len(rows)})
            except Exception as e:
                self._json({"forecasts": [], "count": 0, "error": str(e)})
"""

# Let's insert into _route_get right before "# MSP endpoint"
if "path in ('/api/v1/listings', '/api/listings')" not in text:
    msp_pos = text.find("        # MSP endpoint")
    if msp_pos != -1:
        text = text[:msp_pos] + get_endpoints + "\n" + text[msp_pos:]
        print("Added GET endpoints to serve.py")

# Let's add POST endpoints for listings and orders
post_endpoints = """
        # PS 26033: Create Direct Produce Listing
        elif path in ('/api/v1/listings', '/api/listings'):
            try:
                lid = f"LST-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                crop = body.get('crop_name', 'Wheat (गेहूं)')
                variety = body.get('crop_variety', 'Standard FAQ')
                qty = float(body.get('quantity_quintals', 50))
                price = float(body.get('price_per_quintal', 2450))
                seller_name = body.get('seller_name', 'Ram Singh')
                seller_id = body.get('seller_id', 'KS-10492')
                grade = body.get('quality_grade', 'Grade-A (FAQ Certified)')
                now_str = datetime.now(timezone.utc).isoformat()
                with db_session() as conn:
                    conn.execute(\"\"\"
                        INSERT INTO product_listings (
                            listing_id, seller_id, seller_name, seller_type,
                            crop_name, crop_variety, quantity_quintals, price_per_quintal,
                            quality_grade, status, created_at, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    \"\"\", (lid, seller_id, seller_name, 'farmer', crop, variety, qty, price, grade, 'ACTIVE', now_str, now_str))
                self._json({"status": "success", "listing_id": lid, "message": "Produce lot published successfully!"}, 201)
            except Exception as e:
                self._json({"error": str(e)}, 500)

        # PS 26033: Submit Buyer Bid / Counter-Offer
        elif path in ('/api/v1/orders', '/api/orders'):
            try:
                oid = f"ORD-{datetime.now().strftime('%Y%m%d%H%M%S')}"
                lid = body.get('listing_id', 'LST-2026-WHT-01')
                buyer = body.get('buyer_name', 'BigBasket Sourcing')
                qty = float(body.get('quantity_quintals', 50))
                price = float(body.get('price_per_quintal', 2450))
                now_str = datetime.now(timezone.utc).isoformat()
                with db_session() as conn:
                    conn.execute(\"\"\"
                        INSERT INTO orders (
                            order_id, listing_id, buyer_name, quantity_quintals, price_per_quintal,
                            total_amount, status, payment_status, created_at, updated_at
                        ) VALUES (?,?,?,?,?,?,?,?,?,?)
                    \"\"\", (oid, lid, buyer, qty, price, qty * price, 'NEGOTIATION_ACTIVE', 'ESCROW_RESERVED', now_str, now_str))
                self._json({"status": "success", "order_id": oid, "message": "Bid submitted to negotiation hub!"}, 201)
            except Exception as e:
                self._json({"error": str(e)}, 500)
"""

if "path in ('/api/v1/listings', '/api/listings'):\n            try:\n                lid =" not in text:
    post_pos = text.find("        # POST /api/farmer/register")
    if post_pos != -1:
        text = text[:post_pos] + post_endpoints + "\n" + text[post_pos:]
        print("Added POST endpoints to serve.py")

with open('serve.py', 'w', encoding='utf-8') as f:
    f.write(text)
print("Updated serve.py successfully!")
