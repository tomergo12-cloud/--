"""מנוע זמינות: הפיכת לוח שבועי + חסימות + הזמנות לחלונות זמן פנויים אמיתיים."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple

from . import db, timeutil as tu

Interval = Tuple[int, int]

# סטטוסים שתופסים מקום בלוח
BLOCKING_STATUSES = ("pending", "confirmed")


# ---------- אלגברה של קטעי זמן ----------

def merge(intervals: Iterable[Interval]) -> List[Interval]:
    """איחוד קטעים חופפים/נוגעים לרשימה ממוינת ומינימלית."""
    items = sorted((int(a), int(b)) for a, b in intervals if int(b) > int(a))
    out: List[Interval] = []
    for start, end in items:
        if out and start <= out[-1][1]:
            if end > out[-1][1]:
                out[-1] = (out[-1][0], end)
        else:
            out.append((start, end))
    return out


def subtract(base: Sequence[Interval], blocks: Sequence[Interval]) -> List[Interval]:
    """הפחתת קטעים חסומים מרשימת קטעים פנויים."""
    result = list(merge(base))
    for bs, be in merge(blocks):
        nxt: List[Interval] = []
        for s, e in result:
            if be <= s or bs >= e:      # אין חפיפה
                nxt.append((s, e))
                continue
            if bs > s:
                nxt.append((s, bs))     # שארית לפני החסימה
            if be < e:
                nxt.append((be, e))     # שארית אחרי החסימה
        result = nxt
    return result


def clip(intervals: Sequence[Interval], start: int, end: int) -> List[Interval]:
    out = []
    for s, e in intervals:
        s2, e2 = max(s, start), min(e, end)
        if e2 > s2:
            out.append((s2, e2))
    return out


# ---------- בניית לוח מהכללים ----------

def expand_rules(rules: Sequence[dict], start_ts: int, end_ts: int) -> List[Interval]:
    """הרחבת כללים שבועיים חוזרים לקטעי זמן קונקרטיים בטווח המבוקש.

    עובד ביום מקומי כדי לכבד מעברי שעון קיץ/חורף.
    """
    if end_ts <= start_ts or not rules:
        return []
    by_day: dict[int, list[Interval]] = {}
    for rule in rules:
        by_day.setdefault(int(rule["weekday"]), []).append(
            (int(rule["start_min"]), int(rule["end_min"]))
        )

    out: List[Interval] = []
    day = tu.local_midnight(start_ts)
    # מתחילים יום אחורה כדי לתפוס משמרת שהתחילה אתמול וגולשת
    day -= tu.DAY
    while day < end_ts:
        weekday = tu.weekday_of(day + tu.HOUR * 12)  # אמצע היום - חסין לשעון קיץ
        for start_min, end_min in by_day.get(weekday, []):
            if end_min <= start_min:
                continue
            s = tu.local_day_offset(day, start_min)
            e = tu.local_day_offset(day, end_min)
            if e > start_ts and s < end_ts:
                out.append((s, e))
        day = tu.local_midnight(day + tu.DAY + tu.HOUR * 6)
    return clip(merge(out), start_ts, end_ts)


# ---------- שליפות מה-DB ----------

def rules_for(pro_id: int) -> List[dict]:
    rows = db.query(
        "SELECT weekday, start_min, end_min FROM availability_rules WHERE pro_id=? ORDER BY weekday, start_min",
        (pro_id,),
    )
    return [dict(r) for r in rows]


def blocks_for(pro_id: int, start_ts: int, end_ts: int) -> List[Interval]:
    """כל מה שחוסם: חסימות ידניות + הזמנות פעילות."""
    blocks: List[Interval] = []
    for r in db.query(
        "SELECT start_ts, end_ts FROM time_off WHERE pro_id=? AND end_ts>? AND start_ts<?",
        (pro_id, start_ts, end_ts),
    ):
        blocks.append((int(r["start_ts"]), int(r["end_ts"])))
    placeholders = ",".join("?" * len(BLOCKING_STATUSES))
    for r in db.query(
        f"SELECT start_ts, end_ts FROM bookings WHERE pro_id=? AND status IN ({placeholders}) "
        "AND end_ts>? AND start_ts<?",
        (pro_id, *BLOCKING_STATUSES, start_ts, end_ts),
    ):
        blocks.append((int(r["start_ts"]), int(r["end_ts"])))
    return merge(blocks)


def free_windows(
    pro_id: int,
    start_ts: int,
    end_ts: int,
    min_minutes: int = 0,
    rules: Optional[Sequence[dict]] = None,
) -> List[Interval]:
    """חלונות פנויים אמיתיים של איש מקצוע בטווח נתון."""
    if end_ts <= start_ts:
        return []
    rules = rules_for(pro_id) if rules is None else rules
    base = expand_rules(rules, start_ts, end_ts)
    if not base:
        return []
    free = subtract(base, blocks_for(pro_id, start_ts, end_ts))
    if min_minutes > 0:
        need = min_minutes * tu.MINUTE
        free = [(s, e) for s, e in free if e - s >= need]
    return free


def is_free_at(pro_id: int, start_ts: int, end_ts: int, rules: Optional[Sequence[dict]] = None) -> bool:
    """האם כל הקטע המבוקש נמצא בתוך חלון פנוי אחד."""
    if end_ts <= start_ts:
        return False
    for s, e in free_windows(pro_id, start_ts, end_ts, rules=rules):
        if s <= start_ts and e >= end_ts:
            return True
    return False


def available_now(pro_id: int, now: Optional[int] = None, rules: Optional[Sequence[dict]] = None) -> bool:
    now = tu.now_ts() if now is None else now
    windows = free_windows(pro_id, now, now + tu.HOUR, rules=rules)
    return any(s <= now < e for s, e in windows)


def next_free(
    pro_id: int,
    after_ts: Optional[int] = None,
    min_minutes: int = 60,
    horizon_days: int = 14,
    rules: Optional[Sequence[dict]] = None,
) -> Optional[Interval]:
    """החלון הפנוי הקרוב ביותר שאורכו לפחות min_minutes."""
    after_ts = tu.now_ts() if after_ts is None else after_ts
    horizon = after_ts + horizon_days * tu.DAY
    windows = free_windows(pro_id, after_ts, horizon, min_minutes=min_minutes, rules=rules)
    return windows[0] if windows else None


def slots(
    pro_id: int,
    start_ts: int,
    end_ts: int,
    duration_minutes: int,
    step_minutes: int = 30,
) -> List[Interval]:
    """פירוק החלונות הפנויים לסלוטים בני-הזמנה, מיושרים לרשת של step דקות."""
    duration = max(1, int(duration_minutes)) * tu.MINUTE
    step = max(5, int(step_minutes)) * tu.MINUTE
    out: List[Interval] = []
    for ws, we in free_windows(pro_id, start_ts, end_ts):
        # יישור לרשת: הסלוט הראשון מתחיל בכפולה של step מחצות המקומית
        offset = (tu.minutes_into_day(ws) * tu.MINUTE) % step
        cursor = ws if offset == 0 else ws + (step - offset)
        while cursor + duration <= we:
            out.append((cursor, cursor + duration))
            cursor += step
            if len(out) >= 200:
                return out
    return out
