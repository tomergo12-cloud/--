"""לוגיקה עסקית: משתמשים, אנשי מקצוע, חיפוש, הזמנות וביקורות."""

from __future__ import annotations

from typing import Any, Optional, Sequence

from . import availability as av, config, db, geo, matching, security, timeutil as tu, uploads


class AppError(Exception):
    """שגיאה עסקית שמוחזרת ללקוח עם קוד HTTP."""

    def __init__(self, message: str, status: int = 400, field: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.field = field


PROFESSIONS = [
    "חשמלאי", "אינסטלטור", "מנעולן", "טכנאי מזגנים", "טכנאי מחשבים",
    "הובלות", "שיפוצניק", "נגר", "צבע", "גנן", "מנקה", "טכנאי מכונות כביסה",
    "מורה פרטי", "מאמן כושר", "ספר", "קוסמטיקאית", "צלם", "וטרינר", "בייביסיטר",
]

BOOKING_STATUSES = ("pending", "confirmed", "declined", "cancelled", "done")

# client = מזמין עבודות, pro = בעל פרופיל מקצועי, admin = ניהול המערכת.
ROLES = ("client", "pro", "admin")
PUBLIC_ROLES = ("client", "pro")     # התפקידים שאפשר להירשם אליהם מהאתר


# ---------- משתמשים ----------

def register_user(name: str, email: str, password: str, phone: str = "",
                  role: str = "client") -> dict:
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if len(name) < 2:
        raise AppError("שם חייב להכיל לפחות 2 תווים", field="name")
    if not security.valid_email(email):
        raise AppError("כתובת אימייל לא תקינה", field="email")
    if len(password or "") < 8:
        raise AppError("סיסמה חייבת להכיל לפחות 8 תווים", field="password")
    if role not in PUBLIC_ROLES:
        # תפקיד מנהל לא נפתח מהאתר - רק דרך seed.py או create_admin
        raise AppError("תפקיד לא תקין", field="role")
    if db.query_one("SELECT id FROM users WHERE email=?", (email,)):
        raise AppError("כתובת האימייל כבר רשומה במערכת", status=409, field="email")
    uid = db.insert(
        "INSERT INTO users(name, email, phone, password_hash, role, created_at) VALUES (?,?,?,?,?,?)",
        (name, email, (phone or "").strip(), security.hash_password(password), role, tu.now_ts()),
    )
    return {"user": public_user(uid), **security.create_session(uid)}


def login(email: str, password: str) -> dict:
    row = db.query_one("SELECT * FROM users WHERE email=?", ((email or "").strip().lower(),))
    if row is None or not security.verify_password(password or "", row["password_hash"]):
        raise AppError("אימייל או סיסמה שגויים", status=401)
    if row["blocked"]:
        raise AppError("החשבון חסום. אפשר לפנות למנהל המערכת.", status=403)
    return {"user": public_user(row["id"]), **security.create_session(row["id"])}


def create_admin(name: str, email: str, password: str, phone: str = "") -> dict:
    """יצירת מנהל. לא נגיש מה-API - רק מתוך seed.py או סקריפט תחזוקה."""
    account = register_user(name, email, password, phone, role="client")
    db.execute("UPDATE users SET role='admin' WHERE id=?", (account["user"]["id"],))
    account["user"] = public_user(account["user"]["id"])
    return account


def public_user(user_id: int) -> dict:
    row = db.query_one(
        "SELECT id, name, email, phone, role, blocked, created_at FROM users WHERE id=?", (user_id,)
    )
    if row is None:
        raise AppError("משתמש לא נמצא", status=404)
    user = dict(row)
    user["blocked"] = bool(user["blocked"])
    pro = db.query_one("SELECT id FROM professionals WHERE user_id=?", (user_id,))
    user["pro_id"] = int(pro["id"]) if pro else None
    return user


def require_admin(user: dict) -> None:
    if (user or {}).get("role") != "admin":
        raise AppError("הפעולה מותרת למנהלי המערכת בלבד", status=403)


# ---------- אנשי מקצוע ----------

def _num(value: Any, name: str, lo: float, hi: float, default: Optional[float] = None) -> float:
    if value in (None, "") and default is not None:
        return float(default)
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise AppError(f"ערך לא מספרי בשדה {name}", field=name)
    if not (lo <= num <= hi):
        raise AppError(f"הערך בשדה {name} חייב להיות בין {lo} ל-{hi}", field=name)
    return num


def upsert_professional(user_id: int, data: dict) -> dict:
    profession = (data.get("profession") or "").strip()
    if len(profession) < 2:
        raise AppError("יש לבחור מקצוע", field="profession")
    if not geo.valid_coords(data.get("lat"), data.get("lng")):
        raise AppError("מיקום לא תקין", field="lat")

    fields = {
        "profession": profession,
        "headline": (data.get("headline") or "").strip()[:120],
        "bio": (data.get("bio") or "").strip()[:2000],
        "city": (data.get("city") or "").strip()[:80],
        "lat": float(data["lat"]),
        "lng": float(data["lng"]),
        "service_radius_km": _num(data.get("service_radius_km"), "service_radius_km", 0.5, config.MAX_RADIUS_KM, 15),
        "hourly_rate": int(_num(data.get("hourly_rate"), "hourly_rate", 0, 100000, 0)),
        "currency": (data.get("currency") or "ILS")[:8],
        "min_job_minutes": int(_num(data.get("min_job_minutes"), "min_job_minutes", 15, 480, 60)),
        "years_experience": int(_num(data.get("years_experience"), "years_experience", 0, 70, 0)),
        "emergency": 1 if data.get("emergency") else 0,
        "active": 0 if data.get("active") is False else 1,
        "tags": ",".join(t.strip() for t in (data.get("tags") or "").split(",") if t.strip())[:300],
    }

    existing = db.query_one("SELECT id FROM professionals WHERE user_id=?", (user_id,))
    if existing:
        sets = ", ".join(f"{k}=?" for k in fields)
        db.execute(f"UPDATE professionals SET {sets} WHERE id=?", (*fields.values(), existing["id"]))
        pro_id = int(existing["id"])
    else:
        cols = ", ".join(fields)
        marks = ", ".join("?" * len(fields))
        pro_id = db.insert(
            f"INSERT INTO professionals(user_id, {cols}, created_at) VALUES (?, {marks}, ?)",
            (user_id, *fields.values(), tu.now_ts()),
        )
        if data.get("availability") is None:
            set_availability(pro_id, default_availability())
    # מי שיצר פרופיל מקצועי הוא איש מקצוע לכל דבר (מנהל נשאר מנהל)
    db.execute("UPDATE users SET role='pro' WHERE id=? AND role='client'", (user_id,))
    if data.get("availability") is not None:
        set_availability(pro_id, data["availability"])
    return get_professional(pro_id)


def default_availability() -> list[dict]:
    """ברירת מחדל: א'-ה' 08:00-17:00, ו' 08:00-13:00."""
    rules = [{"weekday": d, "start": "08:00", "end": "17:00"} for d in range(0, 5)]
    rules.append({"weekday": 5, "start": "08:00", "end": "13:00"})
    return rules


def set_availability(pro_id: int, rules: Sequence[dict]) -> list[dict]:
    parsed = []
    for rule in rules or []:
        try:
            weekday = int(rule["weekday"])
        except (KeyError, TypeError, ValueError):
            raise AppError("יום לא תקין בלוח הזמינות", field="availability")
        if not 0 <= weekday <= 6:
            raise AppError("יום בשבוע חייב להיות בין 0 (ראשון) ל-6 (שבת)", field="availability")
        try:
            start = tu.parse_hhmm(rule.get("start", rule.get("start_min")))
            end = tu.parse_hhmm(rule.get("end", rule.get("end_min")))
        except (ValueError, TypeError):
            raise AppError("שעה לא תקינה בלוח הזמינות (פורמט HH:MM)", field="availability")
        if end <= start:
            raise AppError("שעת סיום חייבת להיות אחרי שעת ההתחלה", field="availability")
        parsed.append((weekday, start, end))

    # איחוד חפיפות בתוך אותו יום כדי לשמור על לוח נקי
    clean: list[tuple[int, int, int]] = []
    for weekday in range(7):
        day_intervals = [(s, e) for wd, s, e in parsed if wd == weekday]
        for s, e in av.merge(day_intervals):
            clean.append((weekday, s, e))

    with db.transaction() as conn:
        conn.execute("DELETE FROM availability_rules WHERE pro_id=?", (pro_id,))
        conn.executemany(
            "INSERT INTO availability_rules(pro_id, weekday, start_min, end_min) VALUES (?,?,?,?)",
            [(pro_id, wd, s, e) for wd, s, e in clean],
        )
    return availability_of(pro_id)


def availability_of(pro_id: int) -> list[dict]:
    return [
        {
            "weekday": int(r["weekday"]),
            "weekday_name": tu.WEEKDAY_NAMES[int(r["weekday"])],
            "start": tu.hhmm(int(r["start_min"])),
            "end": tu.hhmm(int(r["end_min"])),
        }
        for r in av.rules_for(pro_id)
    ]


def rating_of(pro_id: int) -> dict:
    row = db.query_one(
        "SELECT COUNT(*) AS c, AVG(rating) AS a FROM reviews WHERE pro_id=?", (pro_id,)
    )
    count = int(row["c"] or 0)
    avg = round(float(row["a"]), 2) if count else None
    return {"count": count, "avg": avg}


def jobs_done(pro_id: int) -> int:
    row = db.query_one("SELECT COUNT(*) AS c FROM bookings WHERE pro_id=? AND status='done'", (pro_id,))
    return int(row["c"] or 0)


def get_professional(pro_id: int, viewer_id: Optional[int] = None) -> dict:
    row = db.query_one(
        "SELECT p.*, u.name AS user_name, u.phone AS user_phone FROM professionals p "
        "JOIN users u ON u.id = p.user_id WHERE p.id=?",
        (pro_id,),
    )
    if row is None:
        raise AppError("איש המקצוע לא נמצא", status=404)
    pro = dict(row)
    now = tu.now_ts()
    rules = av.rules_for(pro_id)
    nxt = av.next_free(pro_id, now, min_minutes=int(pro["min_job_minutes"]),
                       horizon_days=config.SLOT_SEARCH_DAYS, rules=rules)
    is_now = av.available_now(pro_id, now, rules=rules)
    out = {
        "id": int(pro["id"]),
        "user_id": int(pro["user_id"]),
        "name": pro["user_name"],
        "profession": pro["profession"],
        "headline": pro["headline"],
        "bio": pro["bio"],
        "city": pro["city"],
        "photo": pro["photo"],
        "lat": pro["lat"],
        "lng": pro["lng"],
        "service_radius_km": pro["service_radius_km"],
        "hourly_rate": int(pro["hourly_rate"]),
        "currency": pro["currency"],
        "min_job_minutes": int(pro["min_job_minutes"]),
        "years_experience": int(pro["years_experience"]),
        "verified": bool(pro["verified"]),
        "emergency": bool(pro["emergency"]),
        "active": bool(pro["active"]),
        "tags": [t for t in (pro["tags"] or "").split(",") if t],
        "rating": rating_of(pro_id),
        "jobs_done": jobs_done(pro_id),
        "availability": availability_of(pro_id),
        "available_now": is_now,
        "next_free": {"start": nxt[0], "end": nxt[1], "start_iso": tu.to_iso(nxt[0])} if nxt else None,
        "reviews": recent_reviews(pro_id),
    }
    # פרטי קשר נחשפים רק לבעל הפרופיל או ללקוח עם הזמנה מאושרת
    if viewer_id is not None and _may_see_contact(pro_id, int(pro["user_id"]), viewer_id):
        out["phone"] = pro["user_phone"]
    return out


def _may_see_contact(pro_id: int, owner_user_id: int, viewer_id: int) -> bool:
    if viewer_id == owner_user_id:
        return True
    row = db.query_one(
        "SELECT id FROM bookings WHERE pro_id=? AND client_user_id=? AND status IN ('confirmed','done') LIMIT 1",
        (pro_id, viewer_id),
    )
    return row is not None


def recent_reviews(pro_id: int, limit: int = 10) -> list[dict]:
    rows = db.query(
        "SELECT r.rating, r.comment, r.created_at, u.name FROM reviews r "
        "JOIN users u ON u.id = r.client_user_id WHERE r.pro_id=? ORDER BY r.created_at DESC LIMIT ?",
        (pro_id, limit),
    )
    return [
        {"rating": int(r["rating"]), "comment": r["comment"], "name": r["name"],
         "created_at": int(r["created_at"])}
        for r in rows
    ]


def pro_id_of_user(user_id: int) -> Optional[int]:
    row = db.query_one("SELECT id FROM professionals WHERE user_id=?", (user_id,))
    return int(row["id"]) if row else None


def require_owner(pro_id: int, user_id: int) -> None:
    row = db.query_one("SELECT user_id FROM professionals WHERE id=?", (pro_id,))
    if row is None:
        raise AppError("איש המקצוע לא נמצא", status=404)
    if int(row["user_id"]) != int(user_id):
        raise AppError("אין לך הרשאה לפעולה הזו", status=403)


# ---------- חיפוש ----------

def search(
    *,
    lat: float,
    lng: float,
    profession: str = "",
    text: str = "",
    radius_km: float = config.DEFAULT_RADIUS_KM,
    when: str = "now",
    at_ts: Optional[int] = None,
    duration_minutes: int = 60,
    max_rate: Optional[int] = None,
    min_rating: Optional[float] = None,
    only_available_now: bool = False,
    verified_only: bool = False,
    sort: str = "match",
    limit: int = config.MAX_RESULTS,
) -> dict:
    """הלב של המוצר: מי פנוי, קרוב ומתאים - מדורג."""
    if not geo.valid_coords(lat, lng):
        raise AppError("מיקום חיפוש לא תקין", field="lat")
    radius_km = max(0.5, min(float(radius_km or config.DEFAULT_RADIUS_KM), config.MAX_RADIUS_KM))
    duration_minutes = max(15, min(int(duration_minutes or 60), 12 * 60))
    now = tu.now_ts()

    min_lat, max_lat, min_lng, max_lng = geo.bounding_box(lat, lng, radius_km + 0.5)
    sql = ("SELECT p.*, u.name AS user_name FROM professionals p JOIN users u ON u.id=p.user_id "
           "WHERE p.active=1 AND p.lat BETWEEN ? AND ? AND p.lng BETWEEN ? AND ?")
    params: list[Any] = [min_lat, max_lat, min_lng, max_lng]
    if profession:
        sql += " AND p.profession = ?"
        params.append(profession)
    if text:
        like = f"%{text.strip()}%"
        sql += " AND (p.profession LIKE ? OR p.headline LIKE ? OR p.bio LIKE ? OR p.tags LIKE ? OR u.name LIKE ?)"
        params.extend([like] * 5)
    if verified_only:
        sql += " AND p.verified = 1"
    if max_rate:
        sql += " AND p.hourly_rate <= ?"
        params.append(int(max_rate))

    window_start = at_ts if (when == "at" and at_ts) else now
    window_end = window_start + duration_minutes * tu.MINUTE

    results = []
    for row in db.query(sql, params):
        pro_id = int(row["id"])
        distance = geo.haversine_km(lat, lng, float(row["lat"]), float(row["lng"]))
        # שני הכיוונים חייבים להסכים: הוא בטווח שלי, ואני בטווח השירות שלו
        if distance > radius_km or distance > float(row["service_radius_km"]) + 0.001:
            continue

        rules = av.rules_for(pro_id)
        rating = rating_of(pro_id)
        if min_rating and (rating["avg"] or 0) < float(min_rating):
            continue

        if when == "at" and at_ts:
            fits = av.is_free_at(pro_id, window_start, window_end, rules=rules)
            if not fits:
                continue
            is_now = False
            minutes_until = max(0, (window_start - now) // tu.MINUTE)
            next_window = (window_start, window_end)
        else:
            is_now = av.available_now(pro_id, now, rules=rules)
            nxt = av.next_free(pro_id, now, min_minutes=duration_minutes,
                               horizon_days=config.SLOT_SEARCH_DAYS, rules=rules)
            if only_available_now and not is_now:
                continue
            if nxt is None and not is_now:
                if only_available_now:
                    continue
                minutes_until = None
                next_window = None
            else:
                next_window = nxt
                minutes_until = 0 if is_now else max(0, (nxt[0] - now) // tu.MINUTE)

        scored = matching.score_candidate(
            distance_km=distance,
            radius_km=radius_km,
            available_now=is_now,
            minutes_until_free=minutes_until,
            rating_avg=rating["avg"],
            rating_count=rating["count"],
            hourly_rate=int(row["hourly_rate"]),
            budget=max_rate,
            verified=bool(row["verified"]),
            years_experience=int(row["years_experience"]),
            jobs_done=jobs_done(pro_id),
        )
        results.append({
            "id": pro_id,
            "name": row["user_name"],
            "profession": row["profession"],
            "headline": row["headline"],
            "city": row["city"],
            "photo": row["photo"],
            "lat": row["lat"],
            "lng": row["lng"],
            "hourly_rate": int(row["hourly_rate"]),
            "currency": row["currency"],
            "min_job_minutes": int(row["min_job_minutes"]),
            "years_experience": int(row["years_experience"]),
            "verified": bool(row["verified"]),
            "emergency": bool(row["emergency"]),
            "tags": [t for t in (row["tags"] or "").split(",") if t],
            "rating": rating,
            "distance_km": round(distance, 2),
            "available_now": is_now,
            "minutes_until_free": minutes_until,
            "next_free": (
                {"start": next_window[0], "end": next_window[1], "start_iso": tu.to_iso(next_window[0])}
                if next_window else None
            ),
            "eta_text": matching.eta_text(distance, minutes_until, is_now),
            "score": scored["score"],
            "score_parts": scored["parts"],
        })

    keys = {
        "match": lambda r: (-r["score"], r["distance_km"]),
        "distance": lambda r: (r["distance_km"], -r["score"]),
        "rating": lambda r: (-(r["rating"]["avg"] or 0), -r["score"]),
        "price": lambda r: (r["hourly_rate"] if r["hourly_rate"] else 10**9, -r["score"]),
        "soonest": lambda r: (
            -1 if r["available_now"] else (r["minutes_until_free"] if r["minutes_until_free"] is not None else 10**9),
            r["distance_km"],
        ),
    }
    results.sort(key=keys.get(sort, keys["match"]))
    total = len(results)
    results = results[: max(1, min(int(limit or config.MAX_RESULTS), config.MAX_RESULTS))]
    return {
        "results": results,
        "total": total,
        "available_now_count": sum(1 for r in results if r["available_now"]),
        "query": {
            "lat": lat, "lng": lng, "radius_km": radius_km, "profession": profession,
            "text": text, "when": when, "at": at_ts, "duration_minutes": duration_minutes,
            "sort": sort,
        },
    }


# ---------- הזמנות ----------

def create_booking(client_user_id: int, data: dict) -> dict:
    pro_id = int(data.get("pro_id") or 0)
    pro = db.query_one("SELECT * FROM professionals WHERE id=?", (pro_id,))
    if pro is None or not pro["active"]:
        raise AppError("איש המקצוע לא נמצא או אינו פעיל", status=404, field="pro_id")
    if int(pro["user_id"]) == int(client_user_id):
        raise AppError("אי אפשר להזמין את עצמך", field="pro_id")

    start = tu.parse_iso(data.get("start"))
    if start is None:
        raise AppError("זמן התחלה לא תקין", field="start")
    duration = int(_num(data.get("duration_minutes"), "duration_minutes", 15, 12 * 60, pro["min_job_minutes"]))
    if duration < int(pro["min_job_minutes"]):
        raise AppError(f"מינימום הזמנה אצל איש המקצוע הזה: {int(pro['min_job_minutes'])} דקות",
                       field="duration_minutes")
    end = start + duration * tu.MINUTE
    if start < tu.now_ts() - 5 * tu.MINUTE:
        raise AppError("לא ניתן להזמין זמן שכבר עבר", field="start")

    lat = data.get("lat")
    lng = data.get("lng")
    if lat is not None and lng is not None:
        if not geo.valid_coords(lat, lng):
            raise AppError("כתובת/מיקום לא תקין", field="lat")
        distance = geo.haversine_km(float(lat), float(lng), float(pro["lat"]), float(pro["lng"]))
        if distance > float(pro["service_radius_km"]) + 0.001:
            raise AppError(
                f"המיקום מחוץ לאזור השירות של איש המקצוע ({round(distance,1)} ק\"מ מתוך "
                f"{round(float(pro['service_radius_km']),1)})",
                field="lat",
            )

    # הבדיקה והכתיבה תחת טרנזקציה אחת - שני לקוחות לא יתפסו את אותו סלוט
    with db.transaction():
        if not av.is_free_at(pro_id, start, end):
            raise AppError("הזמן המבוקש כבר לא פנוי אצל איש המקצוע", status=409, field="start")
        booking_id = db.insert(
            "INSERT INTO bookings(pro_id, client_user_id, start_ts, end_ts, status, address, lat, lng, note, created_at) "
            "VALUES (?,?,?,?,'pending',?,?,?,?,?)",
            (pro_id, client_user_id, start, end, (data.get("address") or "").strip()[:200],
             float(lat) if lat is not None else None, float(lng) if lng is not None else None,
             (data.get("note") or "").strip()[:1000], tu.now_ts()),
        )
    return get_booking(booking_id, client_user_id)


def get_booking(booking_id: int, viewer_id: int) -> dict:
    row = db.query_one(
        "SELECT b.*, p.profession, p.user_id AS pro_user_id, p.hourly_rate, p.currency, "
        "pu.name AS pro_name, pu.phone AS pro_phone, cu.name AS client_name, cu.phone AS client_phone "
        "FROM bookings b JOIN professionals p ON p.id=b.pro_id "
        "JOIN users pu ON pu.id=p.user_id JOIN users cu ON cu.id=b.client_user_id WHERE b.id=?",
        (booking_id,),
    )
    if row is None:
        raise AppError("ההזמנה לא נמצאה", status=404)
    is_client = int(row["client_user_id"]) == int(viewer_id)
    is_pro = int(row["pro_user_id"]) == int(viewer_id)
    if not (is_client or is_pro):
        raise AppError("אין לך הרשאה לצפות בהזמנה הזו", status=403)

    minutes = (int(row["end_ts"]) - int(row["start_ts"])) // 60
    out = {
        "id": int(row["id"]),
        "pro_id": int(row["pro_id"]),
        "pro_name": row["pro_name"],
        "profession": row["profession"],
        "client_name": row["client_name"],
        "start": int(row["start_ts"]),
        "end": int(row["end_ts"]),
        "start_iso": tu.to_iso(int(row["start_ts"])),
        "end_iso": tu.to_iso(int(row["end_ts"])),
        "duration_minutes": minutes,
        "status": row["status"],
        "address": row["address"],
        "note": row["note"],
        "estimated_price": round(int(row["hourly_rate"]) * minutes / 60),
        "currency": row["currency"],
        "role": "client" if is_client else "pro",
        "created_at": int(row["created_at"]),
        "reviewed": db.query_one("SELECT id FROM reviews WHERE booking_id=?", (booking_id,)) is not None,
    }
    if row["status"] in ("confirmed", "done"):
        out["contact_phone"] = row["pro_phone"] if is_client else row["client_phone"]
    return out


def list_bookings(user_id: int, role: str = "all", status: Optional[str] = None) -> list[dict]:
    pro_id = pro_id_of_user(user_id)
    clauses, params = [], []
    if role == "client" or pro_id is None:
        clauses.append("b.client_user_id = ?")
        params.append(user_id)
    elif role == "pro":
        clauses.append("b.pro_id = ?")
        params.append(pro_id)
    else:
        clauses.append("(b.client_user_id = ? OR b.pro_id = ?)")
        params.extend([user_id, pro_id])
    if status:
        clauses.append("b.status = ?")
        params.append(status)
    rows = db.query(
        f"SELECT b.id FROM bookings b WHERE {' AND '.join(clauses)} ORDER BY b.start_ts DESC LIMIT 200",
        params,
    )
    return [get_booking(int(r["id"]), user_id) for r in rows]


_ALLOWED_TRANSITIONS = {
    "pro": {"pending": {"confirmed", "declined"}, "confirmed": {"done", "cancelled"}},
    "client": {"pending": {"cancelled"}, "confirmed": {"cancelled"}},
}


def set_booking_status(booking_id: int, user_id: int, status: str) -> dict:
    if status not in BOOKING_STATUSES:
        raise AppError("סטטוס לא מוכר", field="status")
    row = db.query_one(
        "SELECT b.status, b.client_user_id, p.user_id AS pro_user_id FROM bookings b "
        "JOIN professionals p ON p.id=b.pro_id WHERE b.id=?",
        (booking_id,),
    )
    if row is None:
        raise AppError("ההזמנה לא נמצאה", status=404)
    if int(row["pro_user_id"]) == int(user_id):
        role = "pro"
    elif int(row["client_user_id"]) == int(user_id):
        role = "client"
    else:
        raise AppError("אין לך הרשאה לעדכן את ההזמנה", status=403)

    allowed = _ALLOWED_TRANSITIONS[role].get(row["status"], set())
    if status not in allowed:
        raise AppError(f"לא ניתן לשנות סטטוס מ-{row['status']} ל-{status}", status=409, field="status")
    db.execute("UPDATE bookings SET status=? WHERE id=?", (status, booking_id))
    return get_booking(booking_id, user_id)


def add_time_off(pro_id: int, start: Any, end: Any, reason: str = "") -> dict:
    start_ts, end_ts = tu.parse_iso(start), tu.parse_iso(end)
    if start_ts is None or end_ts is None or end_ts <= start_ts:
        raise AppError("טווח חסימה לא תקין", field="start")
    tid = db.insert(
        "INSERT INTO time_off(pro_id, start_ts, end_ts, reason) VALUES (?,?,?,?)",
        (pro_id, start_ts, end_ts, (reason or "").strip()[:200]),
    )
    return {"id": tid, "start": start_ts, "end": end_ts, "start_iso": tu.to_iso(start_ts),
            "end_iso": tu.to_iso(end_ts), "reason": reason}


def list_time_off(pro_id: int) -> list[dict]:
    rows = db.query(
        "SELECT id, start_ts, end_ts, reason FROM time_off WHERE pro_id=? AND end_ts > ? ORDER BY start_ts",
        (pro_id, tu.now_ts()),
    )
    return [{"id": int(r["id"]), "start": int(r["start_ts"]), "end": int(r["end_ts"]),
             "start_iso": tu.to_iso(int(r["start_ts"])), "end_iso": tu.to_iso(int(r["end_ts"])),
             "reason": r["reason"]} for r in rows]


def delete_time_off(pro_id: int, time_off_id: int) -> None:
    db.execute("DELETE FROM time_off WHERE id=? AND pro_id=?", (time_off_id, pro_id))


# ---------- ביקורות ----------

def add_review(user_id: int, booking_id: int, rating: int, comment: str = "") -> dict:
    row = db.query_one("SELECT * FROM bookings WHERE id=?", (booking_id,))
    if row is None:
        raise AppError("ההזמנה לא נמצאה", status=404)
    if int(row["client_user_id"]) != int(user_id):
        raise AppError("רק הלקוח שהזמין יכול לדרג", status=403)
    if row["status"] != "done":
        raise AppError("אפשר לדרג רק אחרי שהעבודה הסתיימה", status=409)
    if db.query_one("SELECT id FROM reviews WHERE booking_id=?", (booking_id,)):
        raise AppError("כבר הוספת ביקורת להזמנה הזו", status=409)
    try:
        rating = int(rating)
    except (TypeError, ValueError):
        raise AppError("דירוג לא תקין", field="rating")
    if not 1 <= rating <= 5:
        raise AppError("דירוג חייב להיות בין 1 ל-5", field="rating")
    rid = db.insert(
        "INSERT INTO reviews(pro_id, booking_id, client_user_id, rating, comment, created_at) VALUES (?,?,?,?,?,?)",
        (int(row["pro_id"]), booking_id, user_id, rating, (comment or "").strip()[:1000], tu.now_ts()),
    )
    return {"id": rid, "pro_id": int(row["pro_id"]), "rating": rating,
            "rating_summary": rating_of(int(row["pro_id"]))}


# ---------- תמונת פרופיל ----------

def set_photo(pro_id: int, data_url: str) -> dict:
    """שמירת תמונת פרופיל חדשה, ומחיקת הקודמת אם איש מקצוע אחר לא משתמש בה."""
    row = db.query_one("SELECT photo FROM professionals WHERE id=?", (pro_id,))
    if row is None:
        raise AppError("איש המקצוע לא נמצא", status=404)
    try:
        url = uploads.save(data_url, prefix=f"pro-{pro_id}")
    except uploads.UploadError as exc:
        raise AppError(str(exc), field="photo")
    previous = row["photo"]
    db.execute("UPDATE professionals SET photo=? WHERE id=?", (url, pro_id))
    if previous and previous != url:
        uploads.delete(previous)
    return {"photo": url}


def clear_photo(pro_id: int) -> dict:
    row = db.query_one("SELECT photo FROM professionals WHERE id=?", (pro_id,))
    if row is None:
        raise AppError("איש המקצוע לא נמצא", status=404)
    db.execute("UPDATE professionals SET photo='' WHERE id=?", (pro_id,))
    uploads.delete(row["photo"])
    return {"photo": ""}


# ---------- ניהול מערכת ----------

def admin_stats() -> dict:
    now = tu.now_ts()
    pros = db.query("SELECT id FROM professionals WHERE active=1")
    available = sum(1 for r in pros if av.available_now(int(r["id"]), now))
    one = lambda sql, params=(): int(db.query_one(sql, params)["c"] or 0)
    avg_row = db.query_one("SELECT AVG(rating) AS a FROM reviews")
    return {
        "users": one("SELECT COUNT(*) AS c FROM users"),
        "clients": one("SELECT COUNT(*) AS c FROM users WHERE role='client'"),
        "pros_total": one("SELECT COUNT(*) AS c FROM professionals"),
        "pros_active": len(pros),
        "pros_verified": one("SELECT COUNT(*) AS c FROM professionals WHERE verified=1"),
        "available_now": available,
        "bookings": one("SELECT COUNT(*) AS c FROM bookings"),
        "bookings_pending": one("SELECT COUNT(*) AS c FROM bookings WHERE status='pending'"),
        "bookings_done": one("SELECT COUNT(*) AS c FROM bookings WHERE status='done'"),
        "reviews": one("SELECT COUNT(*) AS c FROM reviews"),
        "rating_avg": round(float(avg_row["a"]), 2) if avg_row["a"] is not None else None,
        "blocked_users": one("SELECT COUNT(*) AS c FROM users WHERE blocked=1"),
    }


def admin_list_pros(text: str = "", status: str = "all", limit: int = 200) -> list[dict]:
    sql = ("SELECT p.*, u.name AS user_name, u.email, u.phone, u.blocked "
           "FROM professionals p JOIN users u ON u.id=p.user_id WHERE 1=1")
    params: list[Any] = []
    if text:
        like = f"%{text.strip()}%"
        sql += " AND (u.name LIKE ? OR u.email LIKE ? OR p.profession LIKE ? OR p.city LIKE ?)"
        params.extend([like] * 4)
    if status == "active":
        sql += " AND p.active=1"
    elif status == "inactive":
        sql += " AND p.active=0"
    elif status == "verified":
        sql += " AND p.verified=1"
    elif status == "unverified":
        sql += " AND p.verified=0"
    sql += " ORDER BY p.id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))

    out = []
    for row in db.query(sql, params):
        pro_id = int(row["id"])
        rating = rating_of(pro_id)
        out.append({
            "id": pro_id,
            "user_id": int(row["user_id"]),
            "name": row["user_name"],
            "email": row["email"],
            "phone": row["phone"],
            "profession": row["profession"],
            "city": row["city"],
            "headline": row["headline"],
            "photo": row["photo"],
            "hourly_rate": int(row["hourly_rate"]),
            "service_radius_km": float(row["service_radius_km"]),
            "years_experience": int(row["years_experience"]),
            "verified": bool(row["verified"]),
            "active": bool(row["active"]),
            "blocked": bool(row["blocked"]),
            "rating": rating,
            "jobs_done": jobs_done(pro_id),
            "available_now": av.available_now(pro_id),
            "created_at": int(row["created_at"]),
        })
    return out


def admin_update_pro(pro_id: int, data: dict) -> dict:
    """עריכת שדות בודדים בפרופיל בידי מנהל, בלי לדרוש טופס מלא."""
    allowed = {
        "profession": lambda v: str(v).strip()[:80],
        "headline": lambda v: str(v).strip()[:120],
        "city": lambda v: str(v).strip()[:80],
        "hourly_rate": lambda v: int(_num(v, "hourly_rate", 0, 100000)),
        "service_radius_km": lambda v: _num(v, "service_radius_km", 0.5, config.MAX_RADIUS_KM),
        "years_experience": lambda v: int(_num(v, "years_experience", 0, 70)),
        "verified": lambda v: 1 if v else 0,
        "active": lambda v: 1 if v else 0,
        "emergency": lambda v: 1 if v else 0,
    }
    updates = {k: conv(data[k]) for k, conv in allowed.items() if k in data}
    if not updates:
        raise AppError("לא נשלחו שדות לעדכון")
    if db.query_one("SELECT id FROM professionals WHERE id=?", (pro_id,)) is None:
        raise AppError("איש המקצוע לא נמצא", status=404)
    sets = ", ".join(f"{k}=?" for k in updates)
    db.execute(f"UPDATE professionals SET {sets} WHERE id=?", (*updates.values(), pro_id))
    return get_professional(pro_id)


def admin_delete_pro(pro_id: int) -> dict:
    row = db.query_one("SELECT photo FROM professionals WHERE id=?", (pro_id,))
    if row is None:
        raise AppError("איש המקצוע לא נמצא", status=404)
    db.execute("DELETE FROM professionals WHERE id=?", (pro_id,))
    uploads.delete(row["photo"])
    return {"ok": True, "deleted": pro_id}


def admin_list_users(text: str = "", role: str = "all", limit: int = 200) -> list[dict]:
    sql = ("SELECT u.id, u.name, u.email, u.phone, u.role, u.blocked, u.created_at, "
           "(SELECT id FROM professionals WHERE user_id=u.id) AS pro_id, "
           "(SELECT COUNT(*) FROM bookings WHERE client_user_id=u.id) AS bookings "
           "FROM users u WHERE 1=1")
    params: list[Any] = []
    if text:
        like = f"%{text.strip()}%"
        sql += " AND (u.name LIKE ? OR u.email LIKE ?)"
        params.extend([like, like])
    if role in ROLES:
        sql += " AND u.role = ?"
        params.append(role)
    sql += " ORDER BY u.id DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return [
        {"id": int(r["id"]), "name": r["name"], "email": r["email"], "phone": r["phone"],
         "role": r["role"], "blocked": bool(r["blocked"]), "created_at": int(r["created_at"]),
         "pro_id": int(r["pro_id"]) if r["pro_id"] else None, "bookings": int(r["bookings"])}
        for r in db.query(sql, params)
    ]


def admin_set_blocked(user_id: int, blocked: bool, actor_id: int) -> dict:
    row = db.query_one("SELECT role FROM users WHERE id=?", (user_id,))
    if row is None:
        raise AppError("משתמש לא נמצא", status=404)
    if int(user_id) == int(actor_id):
        raise AppError("אי אפשר לחסום את החשבון שממנו אתה מחובר")
    if row["role"] == "admin":
        raise AppError("אי אפשר לחסום מנהל מערכת")
    db.execute("UPDATE users SET blocked=? WHERE id=?", (1 if blocked else 0, user_id))
    if blocked:
        db.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))   # ניתוק מיידי
    return public_user(user_id)


def admin_list_bookings(status: str = "all", limit: int = 200) -> list[dict]:
    sql = ("SELECT b.*, p.profession, pu.name AS pro_name, pu.email AS pro_email, "
           "cu.name AS client_name, cu.email AS client_email, p.hourly_rate, p.currency FROM bookings b "
           "JOIN professionals p ON p.id=b.pro_id JOIN users pu ON pu.id=p.user_id "
           "JOIN users cu ON cu.id=b.client_user_id WHERE 1=1")
    params: list[Any] = []
    if status in BOOKING_STATUSES:
        sql += " AND b.status=?"
        params.append(status)
    sql += " ORDER BY b.start_ts DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    out = []
    for r in db.query(sql, params):
        minutes = (int(r["end_ts"]) - int(r["start_ts"])) // 60
        out.append({
            "id": int(r["id"]), "pro_id": int(r["pro_id"]), "pro_name": r["pro_name"],
            "pro_email": r["pro_email"], "profession": r["profession"],
            "client_name": r["client_name"], "client_email": r["client_email"],
            "start": int(r["start_ts"]), "start_iso": tu.to_iso(int(r["start_ts"])),
            "duration_minutes": minutes, "status": r["status"], "address": r["address"],
            "note": r["note"], "estimated_price": round(int(r["hourly_rate"]) * minutes / 60),
        })
    return out


def admin_list_reviews(limit: int = 200, max_rating: Optional[int] = None) -> list[dict]:
    sql = ("SELECT r.id, r.rating, r.comment, r.created_at, r.pro_id, "
           "u.name AS client_name, pu.name AS pro_name, p.profession "
           "FROM reviews r JOIN users u ON u.id=r.client_user_id "
           "JOIN professionals p ON p.id=r.pro_id JOIN users pu ON pu.id=p.user_id WHERE 1=1")
    params: list[Any] = []
    if max_rating:
        sql += " AND r.rating <= ?"
        params.append(int(max_rating))
    sql += " ORDER BY r.created_at DESC LIMIT ?"
    params.append(max(1, min(int(limit), 500)))
    return [
        {"id": int(r["id"]), "pro_id": int(r["pro_id"]), "pro_name": r["pro_name"],
         "profession": r["profession"], "client_name": r["client_name"],
         "rating": int(r["rating"]), "comment": r["comment"], "created_at": int(r["created_at"])}
        for r in db.query(sql, params)
    ]


def admin_delete_review(review_id: int) -> dict:
    if db.query_one("SELECT id FROM reviews WHERE id=?", (review_id,)) is None:
        raise AppError("הביקורת לא נמצאה", status=404)
    db.execute("DELETE FROM reviews WHERE id=?", (review_id,))
    return {"ok": True, "deleted": review_id}
