#!/usr/bin/env python3
"""יצירת מסד נתונים לדוגמה עם אנשי מקצוע באזור גוש דן.

שימוש:  python3 seed.py [--reset]
"""

from __future__ import annotations

import argparse
import os
import random
import sys

from pronear import config, db, services, timeutil as tu

random.seed(7)

CITIES = [
    ("תל אביב", 32.0853, 34.7818),
    ("רמת גן", 32.0684, 34.8248),
    ("גבעתיים", 32.0723, 34.8102),
    ("בני ברק", 32.0807, 34.8338),
    ("חולון", 32.0117, 34.7725),
    ("בת ים", 32.0171, 34.7509),
    ("הרצליה", 32.1624, 34.8443),
    ("רמת השרון", 32.1461, 34.8386),
    ("פתח תקווה", 32.0878, 34.8878),
    ("ראשון לציון", 31.9730, 34.7925),
]

FIRST = ["אבי", "דנה", "יוסי", "מיכל", "רון", "נועה", "איתי", "שירה", "עומר", "תמר",
         "גיל", "ליאת", "עידו", "הילה", "אלון", "מאיה", "ניר", "רותם", "יובל", "אורי",
         "סאמר", "לינא", "בוריס", "אנה", "מוחמד", "יעל", "דוד", "שקד"]
LAST = ["כהן", "לוי", "מזרחי", "פרץ", "ביטון", "אזולאי", "דהן", "אברהם", "פרידמן",
        "שפירא", "חדד", "גבאי", "מלכה", "ברוך", "נחמיאס", "סבן", "אוחיון", "טל"]

HEADLINES = {
    "חשמלאי": ["חשמלאי מוסמך - תקלות, לוחות ותאורה", "שירותי חשמל 24/7 לבית ולעסק"],
    "אינסטלטור": ["פתיחת סתימות ותיקוני נזילות", "אינסטלציה ותיקון דודים"],
    "מנעולן": ["פריצת דלתות והחלפת צילינדרים", "מנעולן מהיר - הגעה תוך חצי שעה"],
    "טכנאי מזגנים": ["ניקוי, גז ותיקוני מזגנים", "התקנת מזגנים ותחזוקה"],
    "טכנאי מחשבים": ["תיקון מחשבים בבית הלקוח", "שחזור מידע והתקנת מערכות"],
    "הובלות": ["הובלות דירות ומשרדים", "הובלה קטנה עם מנוף"],
    "שיפוצניק": ["שיפוצים כלליים וריצוף", "עבודות גבס, איטום וצבע"],
    "נגר": ["נגרות בהתאמה אישית", "תיקון ארונות והרכבת רהיטים"],
    "צבע": ["צביעת דירות בגמר מושלם", "צבע וטיח - עבודה נקייה"],
    "גנן": ["עיצוב וטיפוח גינות", "גיזום, דשא והשקיה"],
    "מנקה": ["ניקיון דירות ומשרדים", "ניקיון אחרי שיפוץ"],
    "טכנאי מכונות כביסה": ["תיקון מכונות כביסה ומייבשים", "טכנאי מוסמך לכל המותגים"],
    "מורה פרטי": ["מתמטיקה 5 יח\"ל", "אנגלית ובגרויות"],
    "מאמן כושר": ["אימון אישי בבית או בפארק", "כושר פונקציונלי ושיקום"],
    "ספר": ["תספורות גברים בבית הלקוח", "עיצוב שיער וזקן"],
    "קוסמטיקאית": ["טיפולי פנים ולק ג'ל", "עיצוב גבות ומניקור"],
    "צלם": ["צילומי אירועים ומשפחה", "צילומי מוצר לעסקים"],
    "וטרינר": ["ביקורי בית לחיות מחמד", "חיסונים ובדיקות"],
    "בייביסיטר": ["שמרטפות בערבים", "ליווי ילדים מהגן"],
}

TAGS = {
    "חשמלאי": "תקלות,לוח חשמל,תאורה,שקעים,חירום",
    "אינסטלטור": "סתימות,נזילות,דוד שמש,ברזים",
    "מנעולן": "פריצת דלת,צילינדר,מנעול רב בריח",
    "טכנאי מזגנים": "מילוי גז,ניקוי,התקנה,מיני מרכזי",
    "טכנאי מחשבים": "ויראוסים,שדרוג,לפטופ,רשתות",
    "הובלות": "הובלת דירה,מנוף,אריזה",
    "שיפוצניק": "ריצוף,גבס,איטום,אמבטיה",
    "נגר": "ארונות,מטבח,הרכבה",
    "צבע": "צביעה,טיח,שפכטל",
    "גנן": "גיזום,דשא,השקיה,עיצוב",
    "מנקה": "ניקיון דירה,חלונות,אחרי שיפוץ",
    "טכנאי מכונות כביסה": "מכונת כביסה,מייבש,מדיח",
    "מורה פרטי": "מתמטיקה,אנגלית,פיזיקה,בגרות",
    "מאמן כושר": "אימון אישי,הרזיה,שיקום",
    "ספר": "תספורת,זקן,ילדים",
    "קוסמטיקאית": "פנים,לק ג'ל,גבות",
    "צלם": "אירועים,משפחה,מוצר",
    "וטרינר": "כלבים,חתולים,חיסונים",
    "בייביסיטר": "ערבים,סופ\"ש,ליווי",
}

RATE_RANGE = {
    "חשמלאי": (180, 320), "אינסטלטור": (200, 350), "מנעולן": (250, 450),
    "טכנאי מזגנים": (200, 380), "טכנאי מחשבים": (150, 280), "הובלות": (300, 600),
    "שיפוצניק": (150, 300), "נגר": (160, 300), "צבע": (120, 240), "גנן": (100, 200),
    "מנקה": (60, 120), "טכנאי מכונות כביסה": (180, 320), "מורה פרטי": (100, 220),
    "מאמן כושר": (120, 250), "ספר": (80, 180), "קוסמטיקאית": (120, 260),
    "צלם": (250, 700), "וטרינר": (300, 550), "בייביסיטר": (40, 70),
}

REVIEW_TEXTS = [
    "הגיע בזמן, עבודה נקייה ומחיר הוגן.", "מקצוען אמיתי, פתר תוך רבע שעה.",
    "שירות מעולה, ממליץ בחום!", "איכותי אבל קצת התעכב.", "יחס אנושי ומחיר טוב.",
    "עשה עבודה יסודית והסביר הכול.", "סבבה, בסך הכול מרוצה.",
    "הציל אותי בשעת לילה מאוחרת.", "מדויק, אמין וזמין.", "לא הכי זול, אבל שווה כל שקל.",
]


def jitter(value: float, spread: float) -> float:
    return value + random.uniform(-spread, spread)


def random_schedule() -> list[dict]:
    """לוחות שונים: ימי עבודה רגילים, ערבים, סופ\"ש, ומעטים 24/7."""
    style = random.random()
    rules = []
    if style < 0.12:                       # זמין כמעט תמיד (חירום)
        return [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)]
    if style < 0.30:                       # משמרות ערב
        for d in range(0, 6):
            rules.append({"weekday": d, "start": "15:00", "end": "23:00"})
        return rules
    if style < 0.45:                       # כולל סופ"ש
        for d in range(0, 7):
            rules.append({"weekday": d, "start": "09:00", "end": "19:00"})
        return rules
    start = random.choice(["07:00", "08:00", "09:00"])
    end = random.choice(["16:00", "17:00", "18:00", "20:00"])
    for d in range(0, 5):
        rules.append({"weekday": d, "start": start, "end": end})
    if random.random() < 0.6:
        rules.append({"weekday": 5, "start": start, "end": "13:00"})
    return rules


def build(count: int = 48) -> None:
    try:
        tu.ensure_timezone()
    except tu.TimezoneUnavailable as exc:
        sys.exit(f"\nלא ניתן ליצור נתוני דמו:\n{exc}\n")
    db.init_db()
    if db.query_one("SELECT id FROM professionals LIMIT 1"):
        print("במסד כבר יש נתונים. הרץ עם --reset כדי לבנות מחדש.")
        return

    professions = list(HEADLINES)
    made = 0
    for i in range(count):
        profession = professions[i % len(professions)]
        city, clat, clng = random.choice(CITIES)
        name = f"{random.choice(FIRST)} {random.choice(LAST)}"
        email = f"pro{i+1}@pronear.demo"
        account = services.register_user(name, email, "demo12345", f"05{random.randint(0,9)}-{random.randint(1000000,9999999)}")
        lo, hi = RATE_RANGE[profession]
        pro = services.upsert_professional(account["user"]["id"], {
            "profession": profession,
            "headline": random.choice(HEADLINES[profession]),
            "bio": f"{random.randint(2, 22)} שנות ניסיון באזור {city} והסביבה. עבודה באחריות, הצעת מחיר לפני התחלה.",
            "city": city,
            "lat": jitter(clat, 0.02),
            "lng": jitter(clng, 0.02),
            "service_radius_km": random.choice([8, 12, 15, 20, 25, 35]),
            "hourly_rate": random.randrange(lo, hi, 10),
            "min_job_minutes": random.choice([30, 60, 60, 90, 120]),
            "years_experience": random.randint(1, 25),
            "emergency": random.random() < 0.25,
            "tags": TAGS[profession],
            "availability": random_schedule(),
        })
        db.execute("UPDATE professionals SET verified=? WHERE id=?",
                   (1 if random.random() < 0.55 else 0, pro["id"]))

        # ביקורות היסטוריות: הזמנה שהסתיימה + דירוג
        for _ in range(random.randint(0, 9)):
            client = _demo_client()
            past_start = tu.now_ts() - random.randint(2, 120) * tu.DAY
            bid = db.insert(
                "INSERT INTO bookings(pro_id, client_user_id, start_ts, end_ts, status, address, note, created_at) "
                "VALUES (?,?,?,?, 'done', ?, '', ?)",
                (pro["id"], client, past_start, past_start + 2 * tu.HOUR, city, past_start),
            )
            rating = random.choices([5, 4, 3, 2], weights=[55, 28, 12, 5])[0]
            db.execute(
                "INSERT INTO reviews(pro_id, booking_id, client_user_id, rating, comment, created_at) VALUES (?,?,?,?,?,?)",
                (pro["id"], bid, client, rating, random.choice(REVIEW_TEXTS), past_start + 3 * tu.HOUR),
            )
        # חסימה עתידית אקראית (חופשה/עבודה פרטית)
        if random.random() < 0.35:
            start = tu.now_ts() + random.randint(1, 6) * tu.DAY
            db.execute("INSERT INTO time_off(pro_id, start_ts, end_ts, reason) VALUES (?,?,?,?)",
                       (pro["id"], start, start + random.choice([4, 8, 24, 48]) * tu.HOUR, "לא זמין"))
        made += 1

    # משתמש לקוח לדמו
    try:
        services.register_user("לקוח לדוגמה", "demo@pronear.demo", "demo12345", "050-1234567")
    except services.AppError:
        pass
    print(f"נוצרו {made} אנשי מקצוע. התחברות לדוגמה: demo@pronear.demo / demo12345")


_clients: list[int] = []


def _demo_client() -> int:
    """יוצר מאגר קטן של לקוחות שכותבים ביקורות."""
    if len(_clients) < 12:
        idx = len(_clients) + 1
        acc = services.register_user(f"{random.choice(FIRST)} {random.choice(LAST)}",
                                     f"client{idx}@pronear.demo", "demo12345")
        _clients.append(acc["user"]["id"])
    return random.choice(_clients)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--reset", action="store_true", help="מחיקת מסד קיים ובנייה מחדש")
    parser.add_argument("--count", type=int, default=48)
    parser.add_argument("--db", default=None)
    args = parser.parse_args()
    if args.db:
        config.DB_PATH = args.db
    if args.reset:
        for suffix in ("", "-wal", "-shm"):
            path = config.DB_PATH + suffix
            if os.path.exists(path):
                os.remove(path)
        db.close_conn()
    build(args.count)
