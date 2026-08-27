"""עבודה עם זמנים: המרה בין epoch (UTC) לזמן מקומי, ופרסינג ISO."""

from __future__ import annotations

import datetime as dt
import re
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from . import config

TZ_HELP = (
    "אזור הזמן '{zone}' לא נמצא במערכת.\n"
    "ב-Windows אין מסד נתוני אזורי זמן מובנה לפייתון — התקן אותו:\n"
    "    pip install tzdata\n"
    "לחלופין אפשר לבחור אזור זמן אחר במשתנה הסביבה PRONEAR_TZ."
)


class TimezoneUnavailable(RuntimeError):
    """מסד נתוני אזורי הזמן חסר - שגיאת התקנה, לא שגיאת נתונים."""

    def __init__(self, zone: str):
        super().__init__(TZ_HELP.format(zone=zone))
        self.zone = zone

_TZ_CACHE: dict[str, ZoneInfo] = {}

MINUTE = 60
HOUR = 3600
DAY = 86400


def tz() -> ZoneInfo:
    zone = config.TIMEZONE
    cached = _TZ_CACHE.get(zone)
    if cached is None:
        try:
            cached = ZoneInfo(zone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise TimezoneUnavailable(zone) from exc
        _TZ_CACHE[zone] = cached
    return cached


def ensure_timezone() -> None:
    """בדיקת התקנה שרצה בעליית השרת ולפני יצירת נתוני דמו."""
    tz()


def now_ts() -> int:
    return int(dt.datetime.now(dt.timezone.utc).timestamp())


def to_local(ts: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(int(ts), tz())


def from_local(d: dt.datetime) -> int:
    """המרת datetime מקומי (naive או aware) ל-epoch שניות."""
    if d.tzinfo is None:
        d = d.replace(tzinfo=tz())
    return int(d.timestamp())


def local_midnight(ts: int) -> int:
    """חצות של אותו יום מקומי, כ-epoch."""
    d = to_local(ts)
    return from_local(dt.datetime(d.year, d.month, d.day))


def weekday_of(ts: int) -> int:
    """יום בשבוע לפי המוסכמה הישראלית: 0=ראשון ... 6=שבת."""
    return (to_local(ts).weekday() + 1) % 7


def minutes_into_day(ts: int) -> int:
    d = to_local(ts)
    return d.hour * 60 + d.minute


def parse_iso(value: str) -> Optional[int]:
    """פרסינג של מחרוזת זמן ל-epoch. תומך ב-ISO ובחותמת אפוק מספרית."""
    if value is None:
        return None
    value = str(value).strip()
    if not value:
        return None
    if value.lstrip("-").isdigit():
        return int(value)
    txt = value.replace("Z", "+00:00")
    # '+' באזור זמן הופך לרווח כשמחרוזת ISO נשלחת ב-query string בלי קידוד
    txt = re.sub(r"\s(\d{2}:?\d{2})$", r"+\1", txt)
    try:
        d = dt.datetime.fromisoformat(txt)
    except ValueError:
        try:
            d = dt.datetime.strptime(txt, "%Y-%m-%d %H:%M")
        except ValueError:
            return None
    return from_local(d)


def to_iso(ts: int) -> str:
    return to_local(ts).isoformat(timespec="minutes")


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def parse_hhmm(value: str) -> int:
    """'09:30' -> 570. מקבל גם '9:30' ו-'0930'."""
    value = str(value).strip()
    if ":" in value:
        h, m = value.split(":", 1)
    elif len(value) == 4 and value.isdigit():
        h, m = value[:2], value[2:]
    else:
        raise ValueError(f"שעה לא תקינה: {value}")
    h, m = int(h), int(m)
    if not (0 <= h <= 24 and 0 <= m < 60):
        raise ValueError(f"שעה לא תקינה: {value}")
    total = h * 60 + m
    if total > 24 * 60:
        raise ValueError(f"שעה לא תקינה: {value}")
    return total


WEEKDAY_NAMES = ["ראשון", "שני", "שלישי", "רביעי", "חמישי", "שישי", "שבת"]


def local_day_offset(day_ts: int, minutes: int) -> int:
    """epoch של השעה המקומית (minutes מחצות) באותו יום מקומי.

    חישוב על שעון הקיר ולא בחיבור שניות - אחרת יום של 23/25 שעות
    (מעבר שעון קיץ/חורף) היה מזיז את כל הלוח בשעה.
    """
    d = to_local(day_ts)
    base = dt.datetime(d.year, d.month, d.day)
    return from_local(base + dt.timedelta(minutes=int(minutes)))
