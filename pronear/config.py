"""הגדרות מערכת. ניתן לדריסה דרך משתני סביבה."""

import os

# אזור זמן ברירת מחדל - כל לוחות הזמינות מוגדרים בזמן מקומי
TIMEZONE = os.environ.get("PRONEAR_TZ", "Asia/Jerusalem")

# מיקום ברירת מחדל למפה כשאין geolocation (מרכז תל אביב)
DEFAULT_LAT = float(os.environ.get("PRONEAR_DEFAULT_LAT", "32.0853"))
DEFAULT_LNG = float(os.environ.get("PRONEAR_DEFAULT_LNG", "34.7818"))

DB_PATH = os.environ.get("PRONEAR_DB", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pronear.db"))

HOST = os.environ.get("PRONEAR_HOST", "127.0.0.1")
PORT = int(os.environ.get("PRONEAR_PORT", "8000"))

# חיפוש
DEFAULT_RADIUS_KM = 15.0
MAX_RADIUS_KM = 200.0
MAX_RESULTS = 60

# דירוג בייסיאני - כמה ביקורות "וירטואליות" בציון הממוצע הכללי
RATING_PRIOR_COUNT = 4.0
RATING_PRIOR_VALUE = 4.0

SESSION_TTL_SECONDS = 60 * 60 * 24 * 14

# חלון ברירת מחדל לחיפוש חלונות זמן פנויים (ימים קדימה)
SLOT_SEARCH_DAYS = 14
