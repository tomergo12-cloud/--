"""אימות משתמשים: גיבוב סיסמאות ואסימוני סשן."""

from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from typing import Optional

from . import config, db, timeutil as tu

_ITERATIONS = 120_000
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$")


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, _ITERATIONS)
    return f"pbkdf2_sha256${_ITERATIONS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iters))
    except (ValueError, AttributeError):
        return False
    return hmac.compare_digest(dk.hex(), hash_hex)


def valid_email(email: str) -> bool:
    return bool(email and EMAIL_RE.match(email.strip()))


def create_session(user_id: int) -> dict:
    token = secrets.token_urlsafe(32)
    now = tu.now_ts()
    expires = now + config.SESSION_TTL_SECONDS
    db.execute(
        "INSERT INTO sessions(token, user_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, user_id, now, expires),
    )
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    return {"token": token, "expires_at": expires}


def user_for_token(token: Optional[str]) -> Optional[dict]:
    if not token:
        return None
    row = db.query_one(
        "SELECT u.id, u.name, u.email, u.phone, u.role, u.blocked, u.created_at, s.expires_at "
        "FROM sessions s JOIN users u ON u.id = s.user_id WHERE s.token = ?",
        (token,),
    )
    if row is None:
        return None
    if int(row["expires_at"]) < tu.now_ts():
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
        return None
    if row["blocked"]:
        # חשבון שנחסם מנותק מיד, גם אם הסשן עדיין בתוקף
        db.execute("DELETE FROM sessions WHERE user_id=?", (row["id"],))
        return None
    user = dict(row)
    user.pop("expires_at", None)
    user["blocked"] = bool(user["blocked"])
    return user


def destroy_session(token: Optional[str]) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token=?", (token,))
