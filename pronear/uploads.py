"""קליטת תמונות פרופיל: ולידציה, שמירה לדיסק והגשה סטטית.

התמונה מגיעה כ-data URL בגוף ה-JSON (בלי תלות בספריית multipart),
נבדקת מול חתימת הקובץ עצמה - לא מול מה שהלקוח הצהיר - ונשמרת בשם
שנגזר מהתוכן, כך שאותה תמונה לא נשמרת פעמיים.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import os
import re
from typing import Optional

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "uploads")
URL_PREFIX = "/uploads/"

MAX_BYTES = 3 * 1024 * 1024        # 3MB לתמונה
_DATA_URL = re.compile(r"^data:image/(png|jpeg|jpg|webp);base64,(.+)$", re.I | re.S)

# חתימות הקבצים שאנחנו מקבלים בפועל
_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
)
_SAFE_NAME = re.compile(r"^[a-z0-9._-]+$")


class UploadError(ValueError):
    """קלט תמונה לא תקין - מוחזר ללקוח כשגיאת 400."""


def _sniff(blob: bytes) -> str:
    for magic, ext in _SIGNATURES:
        if blob.startswith(magic):
            return ext
    if blob[:4] == b"RIFF" and blob[8:12] == b"WEBP":
        return "webp"
    raise UploadError("סוג הקובץ אינו נתמך. אפשר להעלות PNG, JPEG או WebP.")


def decode(data_url: str) -> tuple[bytes, str]:
    """פענוח data URL לזוג (תוכן, סיומת). זורק UploadError על קלט פגום."""
    if not data_url or not isinstance(data_url, str):
        raise UploadError("לא התקבלה תמונה")
    match = _DATA_URL.match(data_url.strip())
    if not match:
        raise UploadError("פורמט התמונה אינו נתמך. יש לשלוח data URL של PNG, JPEG או WebP.")
    try:
        blob = base64.b64decode(match.group(2), validate=True)
    except (binascii.Error, ValueError):
        raise UploadError("קידוד התמונה פגום")
    if not blob:
        raise UploadError("הקובץ ריק")
    if len(blob) > MAX_BYTES:
        raise UploadError(f"התמונה גדולה מדי (מקסימום {MAX_BYTES // (1024 * 1024)}MB)")
    return blob, _sniff(blob)


def save(data_url: str, prefix: str = "img") -> str:
    """שמירת התמונה והחזרת הנתיב הציבורי שלה."""
    blob, ext = decode(data_url)
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    digest = hashlib.sha256(blob).hexdigest()[:20]
    name = f"{re.sub(r'[^a-z0-9-]', '', prefix.lower()) or 'img'}-{digest}.{ext}"
    path = os.path.join(UPLOAD_DIR, name)
    if not os.path.exists(path):
        with open(path, "wb") as fh:
            fh.write(blob)
    return URL_PREFIX + name


def resolve(public_url: str) -> Optional[str]:
    """המרת נתיב ציבורי לנתיב בדיסק, או None אם הוא חורג מתיקיית ההעלאות."""
    if not public_url or not public_url.startswith(URL_PREFIX):
        return None
    name = public_url[len(URL_PREFIX):]
    if not _SAFE_NAME.match(name) or ".." in name:
        return None
    path = os.path.normpath(os.path.join(UPLOAD_DIR, name))
    if os.path.dirname(path) != os.path.normpath(UPLOAD_DIR):
        return None
    return path if os.path.isfile(path) else None


def delete(public_url: str) -> None:
    """מחיקת תמונה שאיש מקצוע החליף - רק אם אף אחד אחר לא משתמש בה."""
    from . import db

    if not public_url:
        return
    still_used = db.query_one("SELECT id FROM professionals WHERE photo=? LIMIT 1", (public_url,))
    if still_used:
        return
    path = resolve(public_url)
    if path:
        try:
            os.remove(path)
        except OSError:
            pass
