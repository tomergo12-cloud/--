"""חישובי מרחק גאוגרפי ותיבות חיפוש מהירות."""

from __future__ import annotations

import math
from typing import Tuple

EARTH_RADIUS_KM = 6371.0088


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """מרחק אוויר בקילומטרים בין שתי נקודות על פני כדור הארץ."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(min(1.0, math.sqrt(a)))


def bounding_box(lat: float, lng: float, radius_km: float) -> Tuple[float, float, float, float]:
    """תיבה תוחמת (min_lat, max_lat, min_lng, max_lng) לסינון מקדים ב-SQL.

    התיבה תמיד מכילה את העיגול, ולכן מסננת רק מועמדים שבוודאות רחוקים מדי.
    הסינון המדויק נעשה אחר כך עם haversine.
    """
    radius_km = max(0.0, float(radius_km))
    dlat = radius_km / 110.574
    # ליד הקטבים cos שואף לאפס - נגן מפני חלוקה באפס ע"י פתיחת כל טווח האורך
    cos_lat = math.cos(math.radians(lat))
    if abs(cos_lat) < 1e-6:
        return (max(-90.0, lat - dlat), min(90.0, lat + dlat), -180.0, 180.0)
    dlng = radius_km / (111.320 * cos_lat)
    if abs(dlng) >= 180.0:
        return (max(-90.0, lat - dlat), min(90.0, lat + dlat), -180.0, 180.0)
    return (
        max(-90.0, lat - dlat),
        min(90.0, lat + dlat),
        lng - abs(dlng),
        lng + abs(dlng),
    )


def valid_coords(lat, lng) -> bool:
    try:
        lat = float(lat)
        lng = float(lng)
    except (TypeError, ValueError):
        return False
    return -90.0 <= lat <= 90.0 and -180.0 <= lng <= 180.0


def travel_minutes(distance_km: float, avg_speed_kmh: float = 28.0) -> int:
    """הערכת זמן נסיעה גס (מהירות ממוצעת עירונית)."""
    if distance_km <= 0:
        return 0
    return int(round(distance_km / avg_speed_kmh * 60))
