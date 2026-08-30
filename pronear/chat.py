"""צ'אט בין לקוח לאיש מקצוע.

המסירה מיידית בלי WebSockets: הלקוח מבקש הודעות שאחרי מזהה מסוים, ואם אין
חדשות הבקשה ממתינה בשרת עד שמישהו שולח (או עד פסק זמן). שליחה מעירה את כל
הממתינים, והם שואלים מחדש את מסד הנתונים.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

from . import db, timeutil as tu
from .services import AppError

MAX_BODY = 2000
LONG_POLL_SECONDS = 25.0
_wake = threading.Condition()


def _notify_waiters() -> None:
    with _wake:
        _wake.notify_all()


def _wait_for_message(timeout: float) -> None:
    with _wake:
        _wake.wait(timeout)


# ---------- שיחות ----------

def _participants(conversation_id: int) -> Optional[dict]:
    row = db.query_one(
        "SELECT c.id, c.pro_id, c.client_user_id, c.booking_id, p.user_id AS pro_user_id, "
        "p.profession, pu.name AS pro_name, cu.name AS client_name "
        "FROM conversations c JOIN professionals p ON p.id = c.pro_id "
        "JOIN users pu ON pu.id = p.user_id JOIN users cu ON cu.id = c.client_user_id "
        "WHERE c.id = ?",
        (conversation_id,),
    )
    return dict(row) if row else None


def _require_member(conversation_id: int, user: dict) -> dict:
    conv = _participants(conversation_id)
    if conv is None:
        raise AppError("השיחה לא נמצאה", status=404)
    is_client = int(conv["client_user_id"]) == int(user["id"])
    is_pro = int(conv["pro_user_id"]) == int(user["id"])
    if not (is_client or is_pro):
        raise AppError("אין לך גישה לשיחה הזו", status=403)
    conv["role"] = "client" if is_client else "pro"
    return conv


def open_conversation(user: dict, pro_id: int, booking_id: Optional[int] = None) -> dict:
    """פתיחת שיחה (או החזרת הקיימת) בין המשתמש לאיש המקצוע."""
    pro = db.query_one("SELECT id, user_id, active FROM professionals WHERE id=?", (pro_id,))
    if pro is None:
        raise AppError("איש המקצוע לא נמצא", status=404, field="pro_id")
    if int(pro["user_id"]) == int(user["id"]):
        raise AppError("אי אפשר לפתוח שיחה עם עצמך", field="pro_id")

    # איש מקצוע יוזם רק מול לקוח שכבר פנה אליו; לקוח יכול לפנות לכל פרופיל פעיל
    client_user_id = int(user["id"])
    if not pro["active"]:
        raise AppError("איש המקצוע אינו פעיל כרגע", field="pro_id")

    existing = db.query_one(
        "SELECT id FROM conversations WHERE pro_id=? AND client_user_id=?", (pro_id, client_user_id)
    )
    if existing:
        conv_id = int(existing["id"])
        if booking_id:
            db.execute("UPDATE conversations SET booking_id=? WHERE id=? AND booking_id IS NULL",
                       (booking_id, conv_id))
    else:
        now = tu.now_ts()
        conv_id = db.insert(
            "INSERT INTO conversations(pro_id, client_user_id, booking_id, created_at, last_message_at) "
            "VALUES (?,?,?,?,?)",
            (pro_id, client_user_id, booking_id, now, now),
        )
    return conversation_view(conv_id, user)


def conversation_for_booking(user: dict, booking_id: int) -> dict:
    """פתיחת השיחה שמתאימה להזמנה - עובד משני הצדדים."""
    row = db.query_one(
        "SELECT b.id, b.pro_id, b.client_user_id, p.user_id AS pro_user_id "
        "FROM bookings b JOIN professionals p ON p.id = b.pro_id WHERE b.id=?",
        (booking_id,),
    )
    if row is None:
        raise AppError("ההזמנה לא נמצאה", status=404)
    uid = int(user["id"])
    if uid not in (int(row["client_user_id"]), int(row["pro_user_id"])):
        raise AppError("אין לך גישה להזמנה הזו", status=403)

    existing = db.query_one("SELECT id FROM conversations WHERE pro_id=? AND client_user_id=?",
                            (row["pro_id"], row["client_user_id"]))
    if existing:
        conv_id = int(existing["id"])
        db.execute("UPDATE conversations SET booking_id=? WHERE id=? AND booking_id IS NULL",
                   (booking_id, conv_id))
    else:
        now = tu.now_ts()
        conv_id = db.insert(
            "INSERT INTO conversations(pro_id, client_user_id, booking_id, created_at, last_message_at) "
            "VALUES (?,?,?,?,?)",
            (row["pro_id"], row["client_user_id"], booking_id, now, now),
        )
    return conversation_view(conv_id, user)


def conversation_view(conversation_id: int, user: dict) -> dict:
    conv = _require_member(conversation_id, user)
    other_name = conv["pro_name"] if conv["role"] == "client" else conv["client_name"]
    last = db.query_one(
        "SELECT body, created_at, sender_user_id FROM messages WHERE conversation_id=? "
        "ORDER BY id DESC LIMIT 1", (conversation_id,))
    unread = db.query_one(
        "SELECT COUNT(*) AS c FROM messages WHERE conversation_id=? AND sender_user_id<>? AND read_at IS NULL",
        (conversation_id, user["id"]))
    photo = db.query_one("SELECT photo FROM professionals WHERE id=?", (conv["pro_id"],))
    return {
        "id": int(conv["id"]),
        "pro_id": int(conv["pro_id"]),
        "booking_id": int(conv["booking_id"]) if conv["booking_id"] else None,
        "role": conv["role"],
        "other_name": other_name,
        "profession": conv["profession"],
        "photo": photo["photo"] if conv["role"] == "client" else "",
        "unread": int(unread["c"] or 0),
        "last_message": ({"body": last["body"], "created_at": int(last["created_at"]),
                          "mine": int(last["sender_user_id"]) == int(user["id"])} if last else None),
    }


def list_conversations(user: dict) -> list[dict]:
    """כל השיחות של המשתמש - כלקוח וכאיש מקצוע גם יחד."""
    rows = db.query(
        "SELECT c.id FROM conversations c JOIN professionals p ON p.id = c.pro_id "
        "WHERE c.client_user_id = ? OR p.user_id = ? ORDER BY c.last_message_at DESC LIMIT 100",
        (user["id"], user["id"]),
    )
    return [conversation_view(int(r["id"]), user) for r in rows]


def unread_total(user: dict) -> int:
    row = db.query_one(
        "SELECT COUNT(*) AS c FROM messages m JOIN conversations c ON c.id = m.conversation_id "
        "JOIN professionals p ON p.id = c.pro_id "
        "WHERE m.sender_user_id <> ? AND m.read_at IS NULL "
        "AND (c.client_user_id = ? OR p.user_id = ?)",
        (user["id"], user["id"], user["id"]),
    )
    return int(row["c"] or 0)


# ---------- הודעות ----------

def _rows_after(conversation_id: int, after_id: int, limit: int = 200) -> list[dict]:
    rows = db.query(
        "SELECT m.id, m.sender_user_id, m.body, m.created_at, m.read_at, u.name AS sender_name "
        "FROM messages m JOIN users u ON u.id = m.sender_user_id "
        "WHERE m.conversation_id = ? AND m.id > ? ORDER BY m.id LIMIT ?",
        (conversation_id, after_id, limit),
    )
    return [dict(r) for r in rows]


def _mark_read(conversation_id: int, user_id: int) -> None:
    cursor = db.execute(
        "UPDATE messages SET read_at=? WHERE conversation_id=? AND sender_user_id<>? AND read_at IS NULL",
        (tu.now_ts(), conversation_id, user_id),
    )
    if cursor.rowcount:
        # מעירים גם את הצד ששלח, כדי שאישור הקריאה יופיע אצלו מיד
        _notify_waiters()


def _read_up_to(conversation_id: int, user_id: int) -> int:
    """המזהה הגבוה ביותר של הודעה שלי שהצד השני כבר קרא."""
    row = db.query_one(
        "SELECT MAX(id) AS m FROM messages WHERE conversation_id=? AND sender_user_id=? "
        "AND read_at IS NOT NULL",
        (conversation_id, user_id),
    )
    return int(row["m"] or 0)


def fetch_messages(user: dict, conversation_id: int, after_id: int = 0,
                   wait: bool = False) -> dict:
    """שליפת הודעות חדשות. עם wait הבקשה ממתינה עד שמגיעה הודעה או עד פסק זמן."""
    _require_member(conversation_id, user)
    rows = _rows_after(conversation_id, after_id)
    read_before = _read_up_to(conversation_id, int(user["id"]))
    if not rows and wait:
        # מתעוררים גם על הודעה חדשה וגם על אישור קריאה של הודעה שלי.
        # ההמתנה נמדדת מול שעון מונוטוני, כדי שיקיצת שווא לא תאריך את פסק הזמן.
        deadline = time.monotonic() + LONG_POLL_SECONDS
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _wait_for_message(remaining)
            rows = _rows_after(conversation_id, after_id)
            if rows or _read_up_to(conversation_id, int(user["id"])) != read_before:
                break
    if rows:
        _mark_read(conversation_id, int(user["id"]))
    return {
        "conversation_id": conversation_id,
        "read_up_to": _read_up_to(conversation_id, int(user["id"])),
        "messages": [
            {"id": int(r["id"]), "body": r["body"], "created_at": int(r["created_at"]),
             "sender_name": r["sender_name"], "mine": int(r["sender_user_id"]) == int(user["id"]),
             "read": r["read_at"] is not None}
            for r in rows
        ],
        "last_id": int(rows[-1]["id"]) if rows else after_id,
    }


def send_message(user: dict, conversation_id: int, body: str) -> dict:
    conv = _require_member(conversation_id, user)
    body = (body or "").strip()
    if not body:
        raise AppError("ההודעה ריקה", field="body")
    if len(body) > MAX_BODY:
        raise AppError(f"ההודעה ארוכה מדי (עד {MAX_BODY} תווים)", field="body")

    now = tu.now_ts()
    message_id = db.insert(
        "INSERT INTO messages(conversation_id, sender_user_id, body, created_at) VALUES (?,?,?,?)",
        (conversation_id, user["id"], body, now),
    )
    db.execute("UPDATE conversations SET last_message_at=? WHERE id=?", (now, conversation_id))
    _notify_waiters()
    return {
        "id": message_id, "conversation_id": conversation_id, "body": body,
        "created_at": now, "sender_name": user["name"], "mine": True, "read": False,
        "role": conv["role"],
    }


# ---------- ניהול ----------

def admin_list_conversations(limit: int = 100) -> list[dict]:
    rows = db.query(
        "SELECT c.id, c.pro_id, c.last_message_at, p.profession, "
        "pu.name AS pro_name, pu.email AS pro_email, "
        "cu.name AS client_name, cu.email AS client_email, "
        "(SELECT COUNT(*) FROM messages WHERE conversation_id = c.id) AS message_count, "
        "(SELECT body FROM messages WHERE conversation_id = c.id ORDER BY id DESC LIMIT 1) AS last_body "
        "FROM conversations c JOIN professionals p ON p.id = c.pro_id "
        "JOIN users pu ON pu.id = p.user_id JOIN users cu ON cu.id = c.client_user_id "
        "WHERE message_count > 0 ORDER BY c.last_message_at DESC LIMIT ?",
        (max(1, min(int(limit), 300)),),
    )
    return [
        {"id": int(r["id"]), "pro_id": int(r["pro_id"]),
         "pro_name": r["pro_name"], "pro_email": r["pro_email"],
         "profession": r["profession"], "client_name": r["client_name"],
         "client_email": r["client_email"], "messages": int(r["message_count"]),
         "last_body": r["last_body"] or "", "last_message_at": int(r["last_message_at"])}
        for r in rows
    ]


def admin_read_conversation(conversation_id: int) -> dict:
    conv = _participants(conversation_id)
    if conv is None:
        raise AppError("השיחה לא נמצאה", status=404)
    rows = _rows_after(conversation_id, 0)
    return {
        "id": conversation_id,
        "pro_name": conv["pro_name"],
        "client_name": conv["client_name"],
        "messages": [
            {"id": int(r["id"]), "body": r["body"], "created_at": int(r["created_at"]),
             "sender_name": r["sender_name"],
             "from_pro": int(r["sender_user_id"]) == int(conv["pro_user_id"])}
            for r in rows
        ],
    }
