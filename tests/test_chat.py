"""צ'אט: פתיחת שיחות, הרשאות, סימון נקרא ומסירה מיידית."""

import threading
import time
import unittest

from pronear import chat, db, services, timeutil as tu
from pronear.services import AppError
from tests.base import DBTestCase
from tests.test_api import ApiTestCase


class ChatBase(DBTestCase):
    def setUp(self):
        super().setUp()
        self.pro_user = services.register_user("רון החשמלאי", "pro@example.com", "password123",
                                               role="pro")["user"]
        self.pro = services.upsert_professional(self.pro_user["id"], {
            "profession": "חשמלאי", "lat": 32.08, "lng": 34.78, "hourly_rate": 200,
            "availability": [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)]})
        self.client = services.register_user("דנה", "client@example.com", "password123")["user"]
        self.stranger = services.register_user("זר", "x@example.com", "password123")["user"]


class ConversationTests(ChatBase):
    def test_client_opens_conversation(self):
        conv = chat.open_conversation(self.client, self.pro["id"])
        self.assertEqual(conv["other_name"], "רון החשמלאי")
        self.assertEqual(conv["role"], "client")
        self.assertEqual(conv["unread"], 0)

    def test_opening_twice_returns_same_conversation(self):
        first = chat.open_conversation(self.client, self.pro["id"])
        second = chat.open_conversation(self.client, self.pro["id"])
        self.assertEqual(first["id"], second["id"])

    def test_cannot_open_with_self(self):
        with self.assertRaises(AppError):
            chat.open_conversation(self.pro_user, self.pro["id"])

    def test_unknown_pro_is_404(self):
        with self.assertRaises(AppError) as ctx:
            chat.open_conversation(self.client, 9999)
        self.assertEqual(ctx.exception.status, 404)

    def test_inactive_pro_rejected(self):
        db.execute("UPDATE professionals SET active=0 WHERE id=?", (self.pro["id"],))
        with self.assertRaises(AppError):
            chat.open_conversation(self.client, self.pro["id"])

    def test_both_sides_see_the_same_thread(self):
        conv = chat.open_conversation(self.client, self.pro["id"])
        pro_view = chat.conversation_view(conv["id"], self.pro_user)
        self.assertEqual(pro_view["id"], conv["id"])
        self.assertEqual(pro_view["role"], "pro")
        self.assertEqual(pro_view["other_name"], "דנה")

    def test_stranger_has_no_access(self):
        conv = chat.open_conversation(self.client, self.pro["id"])
        for action in (lambda: chat.conversation_view(conv["id"], self.stranger),
                       lambda: chat.fetch_messages(self.stranger, conv["id"]),
                       lambda: chat.send_message(self.stranger, conv["id"], "היי")):
            with self.assertRaises(AppError) as ctx:
                action()
            self.assertEqual(ctx.exception.status, 403)

    def test_conversation_from_booking_works_for_both(self):
        start = tu.local_midnight(tu.now_ts() + 2 * tu.DAY) + 10 * tu.HOUR
        booking = services.create_booking(self.client["id"], {
            "pro_id": self.pro["id"], "start": start, "duration_minutes": 60})
        from_client = chat.conversation_for_booking(self.client, booking["id"])
        from_pro = chat.conversation_for_booking(self.pro_user, booking["id"])
        self.assertEqual(from_client["id"], from_pro["id"])
        self.assertEqual(from_client["booking_id"], booking["id"])

    def test_booking_of_others_is_forbidden(self):
        start = tu.local_midnight(tu.now_ts() + 2 * tu.DAY) + 10 * tu.HOUR
        booking = services.create_booking(self.client["id"], {
            "pro_id": self.pro["id"], "start": start, "duration_minutes": 60})
        with self.assertRaises(AppError) as ctx:
            chat.conversation_for_booking(self.stranger, booking["id"])
        self.assertEqual(ctx.exception.status, 403)


class MessageTests(ChatBase):
    def setUp(self):
        super().setUp()
        self.conv = chat.open_conversation(self.client, self.pro["id"])["id"]

    def test_send_and_read_back(self):
        chat.send_message(self.client, self.conv, "  שלום, יש לי תקלה בלוח  ")
        data = chat.fetch_messages(self.pro_user, self.conv)
        self.assertEqual(len(data["messages"]), 1)
        self.assertEqual(data["messages"][0]["body"], "שלום, יש לי תקלה בלוח")   # רווחים נחתכים
        self.assertFalse(data["messages"][0]["mine"])
        self.assertEqual(data["messages"][0]["sender_name"], "דנה")

    def test_after_cursor_returns_only_new(self):
        chat.send_message(self.client, self.conv, "ראשונה")
        first = chat.fetch_messages(self.pro_user, self.conv)
        chat.send_message(self.pro_user, self.conv, "שנייה")
        second = chat.fetch_messages(self.pro_user, self.conv, after_id=first["last_id"])
        self.assertEqual([m["body"] for m in second["messages"]], ["שנייה"])

    def test_reading_marks_as_read_for_sender(self):
        chat.send_message(self.client, self.conv, "היי")
        self.assertEqual(chat.conversation_view(self.conv, self.pro_user)["unread"], 1)
        chat.fetch_messages(self.pro_user, self.conv)
        self.assertEqual(chat.conversation_view(self.conv, self.pro_user)["unread"], 0)
        # השולח רואה שההודעה נקראה
        self.assertTrue(chat.fetch_messages(self.client, self.conv)["messages"][0]["read"])

    def test_unread_total_counts_across_conversations(self):
        chat.send_message(self.client, self.conv, "אחת")
        chat.send_message(self.client, self.conv, "שתיים")
        self.assertEqual(chat.unread_total(self.pro_user), 2)
        self.assertEqual(chat.unread_total(self.client), 0)   # הודעות של עצמי לא נספרות

    def test_empty_and_oversized_rejected(self):
        for bad in ("", "   ", None):
            with self.assertRaises(AppError):
                chat.send_message(self.client, self.conv, bad)
        with self.assertRaises(AppError):
            chat.send_message(self.client, self.conv, "א" * (chat.MAX_BODY + 1))

    def test_list_conversations_sorted_by_activity(self):
        other_user = services.register_user("מקצוען ב", "pro2@example.com", "password123",
                                            role="pro")["user"]
        other_pro = services.upsert_professional(other_user["id"], {
            "profession": "גנן", "lat": 32.08, "lng": 34.78, "hourly_rate": 100})
        second = chat.open_conversation(self.client, other_pro["id"])["id"]
        chat.send_message(self.client, self.conv, "ישנה")
        time.sleep(1.05)
        chat.send_message(self.client, second, "חדשה")
        listed = chat.list_conversations(self.client)
        self.assertEqual(listed[0]["id"], second)

    def test_long_poll_returns_as_soon_as_message_arrives(self):
        """המתנה ארוכה חייבת להתעורר מיד עם שליחה, לא בסוף פסק הזמן."""
        result = {}

        def waiter():
            from pronear import config, db as tdb
            config.DB_PATH = self._dir.name + "/test.db"
            started = time.time()
            data = chat.fetch_messages(self.pro_user, self.conv, after_id=0, wait=True)
            result["elapsed"] = time.time() - started
            result["bodies"] = [m["body"] for m in data["messages"]]
            tdb.close_conn()

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.35)                       # לוודא שההמתנה כבר התחילה
        chat.send_message(self.client, self.conv, "דחוף!")
        thread.join(timeout=10)

        self.assertEqual(result.get("bodies"), ["דחוף!"])
        self.assertLess(result["elapsed"], 5, "ההודעה לא נמסרה מיד")


class ChatApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.pro_token, _ = self.signup("pro@example.com", "רון")
        _, self.pro = self.call("POST", "/api/pros", {
            "profession": "חשמלאי", "lat": 32.08, "lng": 34.78, "hourly_rate": 200}, token=self.pro_token)
        self.client_token, _ = self.signup("client@example.com", "דנה")

    def test_full_conversation_flow(self):
        status, conv = self.call("POST", "/api/conversations", {"pro_id": self.pro["id"]},
                                 token=self.client_token)
        self.assertEqual(status, 201)
        status, sent = self.call("POST", f"/api/conversations/{conv['id']}/messages",
                                 {"body": "מתי אתה פנוי?"}, token=self.client_token)
        self.assertEqual(status, 201)

        status, payload = self.call("GET", f"/api/conversations/{conv['id']}/messages?after=0",
                                    token=self.pro_token)
        self.assertEqual([m["body"] for m in payload["messages"]], ["מתי אתה פנוי?"])

        _, listing = self.call("GET", "/api/conversations", token=self.pro_token)
        self.assertEqual(len(listing["conversations"]), 1)
        self.assertEqual(listing["unread"], 0)      # השליפה סימנה כנקרא

    def test_requires_login(self):
        self.assertEqual(self.call("GET", "/api/conversations")[0], 401)
        self.assertEqual(self.call("POST", "/api/conversations", {"pro_id": self.pro["id"]})[0], 401)

    def test_missing_target_is_400(self):
        status, payload = self.call("POST", "/api/conversations", {}, token=self.client_token)
        self.assertEqual(status, 400)
        self.assertEqual(payload["field"], "pro_id")

    def test_admin_can_read_but_not_write(self):
        from pronear import services as svc
        admin = svc.create_admin("מנהל", "admin@example.com", "password123")
        _, conv = self.call("POST", "/api/conversations", {"pro_id": self.pro["id"]},
                            token=self.client_token)
        self.call("POST", f"/api/conversations/{conv['id']}/messages", {"body": "היי"},
                  token=self.client_token)

        _, listing = self.call("GET", "/api/admin/conversations", token=admin["token"])
        self.assertEqual(len(listing["conversations"]), 1)
        _, thread = self.call("GET", f"/api/admin/conversations/{conv['id']}", token=admin["token"])
        self.assertEqual([m["body"] for m in thread["messages"]], ["היי"])
        # מנהל אינו צד בשיחה, ולכן אינו יכול לכתוב בה
        status, _ = self.call("POST", f"/api/conversations/{conv['id']}/messages",
                              {"body": "מנהל מדבר"}, token=admin["token"])
        self.assertEqual(status, 403)

    def test_admin_chat_routes_locked_to_admins(self):
        self.assertEqual(self.call("GET", "/api/admin/conversations", token=self.client_token)[0], 403)
        self.assertEqual(self.call("GET", "/api/admin/conversations/1", token=self.client_token)[0], 403)


if __name__ == "__main__":
    unittest.main()


class ReadReceiptTests(ChatBase):
    def setUp(self):
        super().setUp()
        self.conv = chat.open_conversation(self.client, self.pro["id"])["id"]

    def test_read_up_to_reported_to_sender(self):
        sent = chat.send_message(self.client, self.conv, "היי")
        # לפני שהצד השני קרא
        self.assertEqual(chat.fetch_messages(self.client, self.conv)["read_up_to"], 0)
        chat.fetch_messages(self.pro_user, self.conv)          # איש המקצוע קורא
        self.assertEqual(chat.fetch_messages(self.client, self.conv)["read_up_to"], sent["id"])

    def test_waiting_sender_wakes_on_read(self):
        """מי שממתין ב-long poll מקבל את אישור הקריאה מיד, לא בסוף פסק הזמן."""
        chat.send_message(self.client, self.conv, "היי")
        result = {}

        def waiter():
            from pronear import config, db as tdb
            config.DB_PATH = self._dir.name + "/test.db"
            started = time.time()
            data = chat.fetch_messages(self.client, self.conv, after_id=99999, wait=True)
            result["elapsed"] = time.time() - started
            result["read_up_to"] = data["read_up_to"]
            tdb.close_conn()

        thread = threading.Thread(target=waiter)
        thread.start()
        time.sleep(0.35)
        chat.fetch_messages(self.pro_user, self.conv)          # הקריאה מעירה את הממתין
        thread.join(timeout=10)

        self.assertGreater(result.get("read_up_to", 0), 0)
        self.assertLess(result["elapsed"], 5, "אישור הקריאה לא נמסר מיד")
