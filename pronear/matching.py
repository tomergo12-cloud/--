"""דירוג התאמה: איך מחליטים מי מוצג ראשון."""

from __future__ import annotations

from typing import Optional

from . import config, geo, timeutil as tu

# משקלים (סכום = 1.0). זמינות ומרחק הם הלב של המוצר.
WEIGHTS = {
    "availability": 0.36,
    "distance": 0.26,
    "rating": 0.22,
    "price": 0.10,
    "trust": 0.06,
}


def bayesian_rating(avg: Optional[float], count: int) -> float:
    """ממוצע משוקלל שמונע מ-5 כוכבים בודדים לנצח 4.8 עם 200 ביקורות."""
    count = max(0, int(count or 0))
    avg = float(avg or 0.0)
    prior_n, prior_v = config.RATING_PRIOR_COUNT, config.RATING_PRIOR_VALUE
    return (avg * count + prior_v * prior_n) / (count + prior_n)


def availability_score(minutes_until_free: Optional[int], available_now: bool) -> float:
    """1.0 = פנוי עכשיו. דועך ככל שההמתנה ארוכה יותר."""
    if available_now:
        return 1.0
    if minutes_until_free is None:
        return 0.0
    m = max(0, int(minutes_until_free))
    if m <= 60:
        return 0.92
    if m <= 180:
        return 0.80
    if m <= 60 * 24:
        return 0.62
    if m <= 60 * 24 * 3:
        return 0.42
    if m <= 60 * 24 * 7:
        return 0.25
    return 0.12


def distance_score(distance_km: float, radius_km: float) -> float:
    """דעיכה לינארית עד גבול החיפוש, עם בונוס למי שממש קרוב."""
    radius_km = max(0.5, float(radius_km))
    d = max(0.0, float(distance_km))
    if d >= radius_km:
        return 0.0
    base = 1.0 - (d / radius_km)
    if d <= 2.0:
        base = min(1.0, base + 0.10)
    return round(base, 4)


def price_score(hourly_rate: Optional[int], budget: Optional[int]) -> float:
    """התאמה לתקציב. בלי תקציב - ניטרלי (לא מעניש יקרים)."""
    if not budget or budget <= 0:
        return 0.6
    rate = int(hourly_rate or 0)
    if rate <= 0:
        return 0.5
    if rate <= budget:
        # ככל שנשאר יותר מרווח מהתקציב - ציון גבוה יותר, אך לא מתגמל זול קיצוני
        return round(min(1.0, 0.75 + 0.25 * (budget - rate) / budget), 4)
    over = (rate - budget) / budget
    return round(max(0.0, 0.6 - over * 1.5), 4)


def trust_score(verified: bool, years_experience: int, jobs_done: int) -> float:
    score = 0.0
    if verified:
        score += 0.45
    score += min(0.30, (int(years_experience or 0) / 20.0) * 0.30)
    score += min(0.25, (int(jobs_done or 0) / 50.0) * 0.25)
    return round(min(1.0, score), 4)


def score_candidate(
    *,
    distance_km: float,
    radius_km: float,
    available_now: bool,
    minutes_until_free: Optional[int],
    rating_avg: Optional[float],
    rating_count: int,
    hourly_rate: Optional[int],
    budget: Optional[int],
    verified: bool,
    years_experience: int,
    jobs_done: int,
) -> dict:
    """מחזיר ציון 0-100 יחד עם פירוק שקוף לרכיבים (מוצג למשתמש)."""
    parts = {
        "availability": availability_score(minutes_until_free, available_now),
        "distance": distance_score(distance_km, radius_km),
        "rating": (bayesian_rating(rating_avg, rating_count) - 1.0) / 4.0,
        "price": price_score(hourly_rate, budget),
        "trust": trust_score(verified, years_experience, jobs_done),
    }
    total = sum(WEIGHTS[k] * v for k, v in parts.items())
    return {
        "score": round(total * 100, 1),
        "parts": {k: round(v * 100, 1) for k, v in parts.items()},
        "weights": WEIGHTS,
    }


def eta_text(distance_km: float, minutes_until_free: Optional[int], available_now: bool) -> str:
    """טקסט קצר בעברית: מתי הוא יכול להיות אצלי."""
    drive = geo.travel_minutes(distance_km)
    if available_now:
        return f"יכול להגיע תוך ~{max(15, drive)} דקות"
    if minutes_until_free is None:
        return "אין זמינות בשבועיים הקרובים"
    total = minutes_until_free + drive
    if total < 60:
        return f"פנוי בעוד ~{total} דקות"
    if total < 60 * 24:
        return f"פנוי בעוד ~{round(total / 60)} שעות"
    days = round(total / (60 * 24))
    return "פנוי מחר" if days <= 1 else f"פנוי בעוד ~{days} ימים"
