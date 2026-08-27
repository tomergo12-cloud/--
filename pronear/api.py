"""ניתוב REST על גבי http.server, ללא תלויות חיצוניות."""

from __future__ import annotations

import json
import re
from typing import Callable, Optional
from urllib.parse import parse_qs, urlparse

from . import availability as av, config, db, security, services, timeutil as tu
from .services import AppError

Handler = Callable[["Request"], object]
_ROUTES: list[tuple[str, re.Pattern, Handler]] = []


class Request:
    def __init__(self, method: str, path: str, query: dict, body: dict, headers):
        self.method = method
        self.path = path
        self.query = query
        self.body = body or {}
        self.headers = headers
        self._user: Optional[dict] = None
        self._user_loaded = False

    # ----- קלט -----
    def q(self, key: str, default=None):
        values = self.query.get(key)
        return values[0] if values else default

    def qf(self, key: str, default=None) -> Optional[float]:
        raw = self.q(key)
        if raw in (None, ""):
            return default
        try:
            return float(raw)
        except ValueError:
            raise AppError(f"ערך לא מספרי בפרמטר {key}", field=key)

    def qi(self, key: str, default=None) -> Optional[int]:
        val = self.qf(key, None)
        return default if val is None else int(val)

    def qb(self, key: str, default=False) -> bool:
        raw = self.q(key)
        if raw is None:
            return default
        return str(raw).lower() in ("1", "true", "yes", "on")

    # ----- זהות -----
    @property
    def token(self) -> Optional[str]:
        auth = self.headers.get("Authorization") or ""
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return self.headers.get("X-Auth-Token")

    @property
    def user(self) -> Optional[dict]:
        if not self._user_loaded:
            self._user = security.user_for_token(self.token)
            self._user_loaded = True
        return self._user

    def require_user(self) -> dict:
        user = self.user
        if user is None:
            raise AppError("נדרשת התחברות", status=401)
        return user

    def require_pro(self) -> tuple[dict, int]:
        user = self.require_user()
        pro_id = services.pro_id_of_user(user["id"])
        if pro_id is None:
            raise AppError("אין לך פרופיל איש מקצוע", status=403)
        return user, pro_id


def route(method: str, pattern: str):
    regex = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", pattern) + "$")

    def wrap(fn: Handler) -> Handler:
        _ROUTES.append((method.upper(), regex, fn))
        return fn

    return wrap


def dispatch(method: str, raw_path: str, body: dict, headers) -> tuple[int, object]:
    parsed = urlparse(raw_path)
    path = parsed.path.rstrip("/") or "/"
    query = parse_qs(parsed.query)
    req = Request(method.upper(), path, query, body, headers)

    path_matched = False
    for route_method, regex, fn in _ROUTES:
        match = regex.match(path)
        if not match:
            continue
        path_matched = True
        if route_method != req.method:
            continue
        try:
            result = fn(req, **{k: v for k, v in match.groupdict().items()})
        except AppError as exc:
            return exc.status, {"error": exc.message, "field": exc.field}
        if isinstance(result, tuple):
            status, payload = result
            return status, payload
        return 200, result
    return (405 if path_matched else 404), {
        "error": "המסלול לא נתמך" if path_matched else "לא נמצא"
    }


# ---------------- מסלולים ----------------

@route("GET", "/api/health")
def health(req: Request):
    return {"ok": True, "version": "1.0.0", "now": tu.now_ts(), "tz": config.TIMEZONE}


@route("GET", "/api/meta")
def meta(req: Request):
    rows = db.query(
        "SELECT profession, COUNT(*) AS c FROM professionals WHERE active=1 GROUP BY profession ORDER BY c DESC"
    )
    return {
        "professions": services.PROFESSIONS,
        "professions_in_use": [{"name": r["profession"], "count": int(r["c"])} for r in rows],
        "weekdays": tu.WEEKDAY_NAMES,
        "default_location": {"lat": config.DEFAULT_LAT, "lng": config.DEFAULT_LNG},
        "default_radius_km": config.DEFAULT_RADIUS_KM,
    }


@route("POST", "/api/auth/register")
def register(req: Request):
    b = req.body
    return 201, services.register_user(b.get("name"), b.get("email"), b.get("password"), b.get("phone", ""))


@route("POST", "/api/auth/login")
def login(req: Request):
    return services.login(req.body.get("email"), req.body.get("password"))


@route("POST", "/api/auth/logout")
def logout(req: Request):
    security.destroy_session(req.token)
    return {"ok": True}


@route("GET", "/api/auth/me")
def me(req: Request):
    user = req.require_user()
    out = {"user": services.public_user(user["id"])}
    pro_id = out["user"]["pro_id"]
    if pro_id:
        out["professional"] = services.get_professional(pro_id, viewer_id=user["id"])
    return out


@route("GET", "/api/search")
def search(req: Request):
    lat, lng = req.qf("lat"), req.qf("lng")
    if lat is None or lng is None:
        raise AppError("חובה לציין מיקום (lat/lng)", field="lat")
    when = (req.q("when") or "now").lower()
    at_ts = tu.parse_iso(req.q("at")) if req.q("at") else None
    if when == "at" and at_ts is None:
        raise AppError("זמן מבוקש לא תקין", field="at")
    return services.search(
        lat=lat,
        lng=lng,
        profession=(req.q("profession") or "").strip(),
        text=(req.q("q") or "").strip(),
        radius_km=req.qf("radius_km", config.DEFAULT_RADIUS_KM),
        when=when,
        at_ts=at_ts,
        duration_minutes=req.qi("duration", 60),
        max_rate=req.qi("max_rate"),
        min_rating=req.qf("min_rating"),
        only_available_now=req.qb("available_now"),
        verified_only=req.qb("verified"),
        sort=(req.q("sort") or "match"),
        limit=req.qi("limit", config.MAX_RESULTS),
    )


@route("GET", "/api/pros/{pro_id}")
def get_pro(req: Request, pro_id: str):
    viewer = req.user["id"] if req.user else None
    return services.get_professional(int(pro_id), viewer_id=viewer)


@route("POST", "/api/pros")
def create_pro(req: Request):
    user = req.require_user()
    return 201, services.upsert_professional(user["id"], req.body)


@route("PUT", "/api/pros/{pro_id}")
def update_pro(req: Request, pro_id: str):
    user = req.require_user()
    services.require_owner(int(pro_id), user["id"])
    return services.upsert_professional(user["id"], req.body)


@route("PUT", "/api/pros/{pro_id}/availability")
def put_availability(req: Request, pro_id: str):
    user = req.require_user()
    services.require_owner(int(pro_id), user["id"])
    rules = req.body.get("availability", req.body.get("rules"))
    if rules is None:
        raise AppError("חסר לוח זמינות", field="availability")
    return {"availability": services.set_availability(int(pro_id), rules)}


@route("GET", "/api/pros/{pro_id}/slots")
def get_slots(req: Request, pro_id: str):
    pro = services.get_professional(int(pro_id))
    start = tu.parse_iso(req.q("from")) or tu.now_ts()
    days = max(1, min(req.qi("days", 7), 30))
    end = tu.parse_iso(req.q("to")) or (start + days * tu.DAY)
    duration = max(15, min(req.qi("duration", pro["min_job_minutes"]), 12 * 60))
    found = av.slots(int(pro_id), start, end, duration, step_minutes=req.qi("step", 30))
    return {
        "pro_id": int(pro_id),
        "duration_minutes": duration,
        "slots": [
            {"start": s, "end": e, "start_iso": tu.to_iso(s), "end_iso": tu.to_iso(e),
             "day": tu.WEEKDAY_NAMES[tu.weekday_of(s)]}
            for s, e in found
        ],
    }


@route("GET", "/api/pros/{pro_id}/time-off")
def get_time_off(req: Request, pro_id: str):
    user = req.require_user()
    services.require_owner(int(pro_id), user["id"])
    return {"time_off": services.list_time_off(int(pro_id))}


@route("POST", "/api/pros/{pro_id}/time-off")
def post_time_off(req: Request, pro_id: str):
    user = req.require_user()
    services.require_owner(int(pro_id), user["id"])
    b = req.body
    return 201, services.add_time_off(int(pro_id), b.get("start"), b.get("end"), b.get("reason", ""))


@route("DELETE", "/api/pros/{pro_id}/time-off/{off_id}")
def del_time_off(req: Request, pro_id: str, off_id: str):
    user = req.require_user()
    services.require_owner(int(pro_id), user["id"])
    services.delete_time_off(int(pro_id), int(off_id))
    return {"ok": True}


@route("POST", "/api/bookings")
def post_booking(req: Request):
    user = req.require_user()
    return 201, services.create_booking(user["id"], req.body)


@route("GET", "/api/bookings")
def get_bookings(req: Request):
    user = req.require_user()
    return {"bookings": services.list_bookings(user["id"], req.q("role", "all"), req.q("status"))}


@route("GET", "/api/bookings/{booking_id}")
def get_booking(req: Request, booking_id: str):
    user = req.require_user()
    return services.get_booking(int(booking_id), user["id"])


@route("POST", "/api/bookings/{booking_id}/status")
def post_booking_status(req: Request, booking_id: str):
    user = req.require_user()
    return services.set_booking_status(int(booking_id), user["id"], (req.body.get("status") or "").strip())


@route("POST", "/api/bookings/{booking_id}/review")
def post_review(req: Request, booking_id: str):
    user = req.require_user()
    b = req.body
    return 201, services.add_review(user["id"], int(booking_id), b.get("rating"), b.get("comment", ""))
