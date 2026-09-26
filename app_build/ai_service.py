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

"""Lightweight AI/ML service for Kisan Setu Marketplace.

Provides:
- Demand forecasting via simple moving-average over historical orders
- Delivery route optimization via nearest-neighbor TSP heuristic

Designed as a prototype-grade module — real production would swap in
proper ML models (ARIMA/Prophet for demand, OR-Tools for routing).
"""

from __future__ import annotations

import asyncio
import logging
import math
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine great-circle distance between two lat/lon points in km."""
    R = 6371.0  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


class AIService:
    """Encapsulates AI/ML operations backed by SQLite order history."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ── Demand Forecasting ───────────────────────────────────────────────

    async def forecast_demand(
        self,
        crop_name: str,
        district: str,
        horizon_days: int = 7,
        lookback_weeks: int = 4,
    ) -> dict[str, Any]:
        """Predict demand for a crop in a district using moving-average.

        Uses historical order quantities from the past ``lookback_weeks`` weeks
        to compute a weekly average, then projects forward ``horizon_days``.
        Falls back to seed/demo predictions when insufficient history exists.
        """
        def _forecast() -> dict[str, Any]:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cutoff = (
                    datetime.now(timezone.utc) - timedelta(weeks=lookback_weeks)
                ).isoformat()

                # Aggregate weekly order quantities for this crop+district
                cursor.execute(
                    """
                    SELECT
                        strftime('%Y-W%W', created_at) AS week,
                        SUM(quantity_quintals) AS total_qty
                    FROM orders
                    WHERE LOWER(crop_name) = LOWER(?)
                      AND LOWER(delivery_district) = LOWER(?)
                      AND created_at >= ?
                    GROUP BY week
                    ORDER BY week;
                    """,
                    (crop_name, district, cutoff),
                )
                rows = [dict(r) for r in cursor.fetchall()]

            if len(rows) >= 2:
                # Moving average of weekly demand
                weekly_totals = [r["total_qty"] for r in rows]
                avg_weekly = sum(weekly_totals) / len(weekly_totals)
                daily_avg = avg_weekly / 7.0
                predicted = round(daily_avg * horizon_days, 2)
                confidence = min(85.0, 50.0 + len(rows) * 5.0)
                model_type = "moving_average"
            else:
                # Fallback: seed demo prediction based on known crop patterns
                demo_demand = {
                    "wheat": 120.0,
                    "rice": 95.0,
                    "mustard": 45.0,
                    "cotton": 60.0,
                    "maize": 55.0,
                    "gram": 35.0,
                    "soybean": 40.0,
                    "paddy": 90.0,
                    "sugarcane": 150.0,
                    "groundnut": 30.0,
                    "barley": 25.0,
                    "sunflower": 20.0,
                }
                base = demo_demand.get(crop_name.lower(), 50.0)
                predicted = round(base * (horizon_days / 7.0), 2)
                confidence = 55.0
                model_type = "heuristic_fallback"

            return {
                "crop_name": crop_name,
                "district": district,
                "horizon_days": horizon_days,
                "predicted_demand_quintals": predicted,
                "confidence_pct": confidence,
                "model_type": model_type,
                "data_points_used": len(rows) if rows else 0,
                "forecast_date": (
                    datetime.now(timezone.utc) + timedelta(days=horizon_days)
                ).strftime("%Y-%m-%d"),
                "generated_at": _utc_now_iso(),
            }

        return await asyncio.to_thread(_forecast)

    # ── Route Optimization ───────────────────────────────────────────────

    async def optimize_route(
        self,
        pickup: dict[str, float],
        deliveries: list[dict[str, float]],
    ) -> dict[str, Any]:
        """Suggest an optimized delivery route using nearest-neighbor heuristic.

        Args:
            pickup: ``{"lat": float, "lng": float}`` — the origin (farmer/warehouse).
            deliveries: list of ``{"lat": float, "lng": float, "order_id": str}``
                        representing drop-off points.

        Returns:
            Ordered waypoints, total distance, and estimated duration.
        """
        def _optimize() -> dict[str, Any]:
            if not deliveries:
                return {
                    "optimized_route": [],
                    "total_distance_km": 0.0,
                    "estimated_duration_min": 0,
                    "waypoint_count": 0,
                    "method": "nearest_neighbor",
                    "generated_at": _utc_now_iso(),
                }

            # Nearest-neighbor TSP starting from pickup point
            current_lat = pickup["lat"]
            current_lng = pickup["lng"]
            remaining = list(range(len(deliveries)))
            route_order: list[int] = []
            total_distance = 0.0

            while remaining:
                nearest_idx = -1
                nearest_dist = float("inf")
                for idx in remaining:
                    d = deliveries[idx]
                    dist = _haversine_km(current_lat, current_lng, d["lat"], d["lng"])
                    if dist < nearest_dist:
                        nearest_dist = dist
                        nearest_idx = idx
                route_order.append(nearest_idx)
                total_distance += nearest_dist
                current_lat = deliveries[nearest_idx]["lat"]
                current_lng = deliveries[nearest_idx]["lng"]
                remaining.remove(nearest_idx)

            # Build ordered waypoints
            optimized_waypoints = []
            for seq, idx in enumerate(route_order):
                d = deliveries[idx]
                optimized_waypoints.append({
                    "sequence": seq + 1,
                    "order_id": d.get("order_id", f"stop-{seq+1}"),
                    "lat": d["lat"],
                    "lng": d["lng"],
                    "distance_from_prev_km": round(
                        _haversine_km(
                            pickup["lat"] if seq == 0 else deliveries[route_order[seq - 1]]["lat"],
                            pickup["lng"] if seq == 0 else deliveries[route_order[seq - 1]]["lng"],
                            d["lat"],
                            d["lng"],
                        ),
                        2,
                    ),
                })

            # Rough estimate: 30 km/h average speed in rural India + 10 min per stop
            estimated_minutes = int((total_distance / 30.0) * 60) + len(deliveries) * 10

            return {
                "pickup": pickup,
                "optimized_route": optimized_waypoints,
                "total_distance_km": round(total_distance, 2),
                "estimated_duration_min": estimated_minutes,
                "waypoint_count": len(optimized_waypoints),
                "method": "nearest_neighbor",
                "generated_at": _utc_now_iso(),
            }

        return await asyncio.to_thread(_optimize)
