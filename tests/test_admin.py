"""תפקידים, פאנל הניהול והעלאת תמונות."""

import base64
import unittest

from pronear import api, db, services, timeutil as tu, uploads
from pronear.services import AppError
from tests.base import DBTestCase
from tests.test_api import ApiTestCase, Headers

PNG = "data:image/png;base64," + base64.b64encode(bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c636000000200010005fe02fea7c9a1cc0000000049454e44ae426082")).decode()


class RoleTests(DBTestCase):
    def test_client_is_default_role(self):
        acc = services.register_user("לקוח", "c@example.com", "password123")
        self.assertEqual(acc["user"]["role"], "client")

    def test_registering_as_pro_sets_role(self):
        acc = services.register_user("מקצוען", "p@example.com", "password123", role="pro")
        self.assertEqual(acc["user"]["role"], "pro")

    def test_cannot_register_as_admin(self):
        with self.assertRaises(AppError) as ctx:
            services.register_user("גנב", "x@example.com", "password123", role="admin")
        self.assertEqual(ctx.exception.field, "role")

    def test_creating_profile_promotes_client_to_pro(self):
        acc = services.register_user("לקוח", "c2@example.com", "password123")
        self.assertEqual(acc["user"]["role"], "client")
        services.upsert_professional(acc["user"]["id"], {
            "profession": "גנן", "lat": 32.08, "lng": 34.78, "hourly_rate": 100})
        self.assertEqual(services.public_user(acc["user"]["id"])["role"], "pro")

    def test_create_admin_helper(self):
        acc = services.create_admin("מנהל", "a@example.com", "password123")
        self.assertEqual(acc["user"]["role"], "admin")

    def test_require_admin(self):
        services.require_admin({"role": "admin"})
        for role in ("client", "pro", None):
            with self.assertRaises(AppError) as ctx:
                services.require_admin({"role": role})
            self.assertEqual(ctx.exception.status, 403)


class BlockingTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.admin = services.create_admin("מנהל", "admin@example.com", "password123")["user"]["id"]
        self.user = services.register_user("לקוח", "c@example.com", "password123")["user"]["id"]

    def test_blocked_user_cannot_login(self):
        services.admin_set_blocked(self.user, True, self.admin)
        with self.assertRaises(AppError) as ctx:
            services.login("c@example.com", "password123")
        self.assertEqual(ctx.exception.status, 403)

    def test_blocking_kills_active_sessions(self):
        session = services.login("c@example.com", "password123")
        from pronear import security
        self.assertIsNotNone(security.user_for_token(session["token"]))
        services.admin_set_blocked(self.user, True, self.admin)
        self.assertIsNone(security.user_for_token(session["token"]))

    def test_unblock_restores_access(self):
        services.admin_set_blocked(self.user, True, self.admin)
        services.admin_set_blocked(self.user, False, self.admin)
        self.assertIn("token", services.login("c@example.com", "password123"))

    def test_cannot_block_self_or_admin(self):
        with self.assertRaises(AppError):
            services.admin_set_blocked(self.admin, True, self.admin)
        other_admin = services.create_admin("מנהל ב", "admin2@example.com", "password123")["user"]["id"]
        with self.assertRaises(AppError):
            services.admin_set_blocked(other_admin, True, self.admin)


class UploadTests(unittest.TestCase):
    def test_valid_png_saved_and_resolvable(self):
        url = uploads.save(PNG, prefix="test")
        self.assertTrue(url.startswith(uploads.URL_PREFIX))
        self.assertIsNotNone(uploads.resolve(url))

    def test_same_content_reuses_file(self):
        self.assertEqual(uploads.save(PNG, prefix="same"), uploads.save(PNG, prefix="same"))

    def test_rejects_wrong_type_and_garbage(self):
        fake = base64.b64encode(b"GIF89a not an image").decode()
        for bad in ("", "data:image/gif;base64,AAAA", "data:image/png;base64,!!!",
                    "data:image/png;base64," + fake):
            with self.assertRaises(uploads.UploadError):
                uploads.save(bad)

    def test_rejects_oversized_image(self):
        big = b"\x89PNG\r\n\x1a\n" + b"0" * (uploads.MAX_BYTES + 10)
        with self.assertRaises(uploads.UploadError):
            uploads.save("data:image/png;base64," + base64.b64encode(big).decode())

    def test_resolve_blocks_path_traversal(self):
        for path in ("/uploads/../../etc/passwd", "/uploads/sub/dir.png", "/etc/passwd", ""):
            self.assertIsNone(uploads.resolve(path))


class AdminApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        admin = services.create_admin("מנהל", "admin@example.com", "password123")
        self.admin_token = admin["token"]
        self.pro_token, _ = self.signup("pro@example.com", "רון")
        _, self.pro = self.call("POST", "/api/pros", {
            "profession": "חשמלאי", "lat": 32.081, "lng": 34.781, "hourly_rate": 250,
            "city": "תל אביב", "service_radius_km": 20}, token=self.pro_token)
        self.client_token, self.client_id = self.signup("client@example.com", "לקוח")

    def test_stats_requires_admin(self):
        self.assertEqual(self.call("GET", "/api/admin/stats")[0], 401)
        self.assertEqual(self.call("GET", "/api/admin/stats", token=self.client_token)[0], 403)
        status, payload = self.call("GET", "/api/admin/stats", token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["pros_total"], 1)

    def test_every_admin_route_is_locked(self):
        routes = [("GET", "/api/admin/pros"), ("GET", "/api/admin/users"),
                  ("GET", "/api/admin/bookings"), ("GET", "/api/admin/reviews"),
                  ("PATCH", f"/api/admin/pros/{self.pro['id']}"),
                  ("DELETE", f"/api/admin/pros/{self.pro['id']}"),
                  ("POST", f"/api/admin/users/{self.client_id}/blocked"),
                  ("DELETE", "/api/admin/reviews/1")]
        for method, path in routes:
            status, _ = self.call(method, path, {"verified": True}, token=self.client_token)
            self.assertEqual(status, 403, f"{method} {path} לא חסום ללקוח")

    def test_admin_can_verify_and_deactivate(self):
        status, payload = self.call("PATCH", f"/api/admin/pros/{self.pro['id']}",
                                    {"verified": True, "active": False}, token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertTrue(payload["verified"])
        self.assertFalse(payload["active"])

    def test_admin_edit_validates_input(self):
        status, _ = self.call("PATCH", f"/api/admin/pros/{self.pro['id']}",
                              {"hourly_rate": -5}, token=self.admin_token)
        self.assertEqual(status, 400)

    def test_deactivated_pro_leaves_search(self):
        self.call("PATCH", f"/api/admin/pros/{self.pro['id']}", {"active": False}, token=self.admin_token)
        _, payload = self.call("GET", "/api/search?lat=32.0853&lng=34.7818&radius_km=10")
        self.assertEqual(payload["total"], 0)

    def test_admin_delete_pro(self):
        status, _ = self.call("DELETE", f"/api/admin/pros/{self.pro['id']}", token=self.admin_token)
        self.assertEqual(status, 200)
        _, payload = self.call("GET", "/api/admin/pros", token=self.admin_token)
        self.assertEqual(payload["pros"], [])

    def test_admin_lists_filter(self):
        _, payload = self.call("GET", "/api/admin/users?role=admin", token=self.admin_token)
        self.assertEqual([u["role"] for u in payload["users"]], ["admin"])
        _, payload = self.call("GET", "/api/admin/pros?q=חשמלאי", token=self.admin_token)
        self.assertEqual(len(payload["pros"]), 1)
        _, payload = self.call("GET", "/api/admin/pros?q=אין-כזה", token=self.admin_token)
        self.assertEqual(payload["pros"], [])

    def test_block_user_through_api(self):
        status, payload = self.call("POST", f"/api/admin/users/{self.client_id}/blocked",
                                    {"blocked": True}, token=self.admin_token)
        self.assertEqual(status, 200)
        self.assertTrue(payload["blocked"])
        # הסשן של המשתמש החסום מפסיק לעבוד מיד
        self.assertEqual(self.call("GET", "/api/auth/me", token=self.client_token)[0], 401)

    def test_admin_deletes_review(self):
        start = tu.local_midnight(tu.now_ts() + 2 * tu.DAY) + 10 * tu.HOUR
        self.call("PUT", f"/api/pros/{self.pro['id']}/availability",
                  {"availability": [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)]},
                  token=self.pro_token)
        _, booking = self.call("POST", "/api/bookings", {
            "pro_id": self.pro["id"], "start": start, "duration_minutes": 60}, token=self.client_token)
        self.call("POST", f"/api/bookings/{booking['id']}/status", {"status": "confirmed"}, token=self.pro_token)
        self.call("POST", f"/api/bookings/{booking['id']}/status", {"status": "done"}, token=self.pro_token)
        self.call("POST", f"/api/bookings/{booking['id']}/review", {"rating": 1, "comment": "רע"},
                  token=self.client_token)

        _, payload = self.call("GET", "/api/admin/reviews?max_rating=2", token=self.admin_token)
        self.assertEqual(len(payload["reviews"]), 1)
        review_id = payload["reviews"][0]["id"]
        self.assertEqual(self.call("DELETE", f"/api/admin/reviews/{review_id}", token=self.admin_token)[0], 200)
        _, pro = self.call("GET", f"/api/pros/{self.pro['id']}")
        self.assertEqual(pro["rating"]["count"], 0)


class PhotoApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.pro_token, _ = self.signup("pro@example.com", "רון")
        _, self.pro = self.call("POST", "/api/pros", {
            "profession": "נגר", "lat": 32.08, "lng": 34.78, "hourly_rate": 200}, token=self.pro_token)

    def test_owner_can_upload_and_clear(self):
        status, payload = self.call("POST", f"/api/pros/{self.pro['id']}/photo",
                                    {"photo": PNG}, token=self.pro_token)
        self.assertEqual(status, 200)
        self.assertTrue(payload["photo"].startswith("/uploads/"))
        _, pro = self.call("GET", f"/api/pros/{self.pro['id']}")
        self.assertEqual(pro["photo"], payload["photo"])
        self.assertEqual(self.call("DELETE", f"/api/pros/{self.pro['id']}/photo",
                                   token=self.pro_token)[0], 200)

    def test_stranger_cannot_upload(self):
        other, _ = self.signup("other@example.com", "זר")
        status, _ = self.call("POST", f"/api/pros/{self.pro['id']}/photo", {"photo": PNG}, token=other)
        self.assertEqual(status, 403)

    def test_admin_can_upload_for_anyone(self):
        admin = services.create_admin("מנהל", "admin@example.com", "password123")
        status, _ = self.call("POST", f"/api/pros/{self.pro['id']}/photo",
                              {"photo": PNG}, token=admin["token"])
        self.assertEqual(status, 200)

    def test_bad_image_returns_400(self):
        status, payload = self.call("POST", f"/api/pros/{self.pro['id']}/photo",
                                    {"photo": "data:image/gif;base64,AAAA"}, token=self.pro_token)
        self.assertEqual(status, 400)
        self.assertEqual(payload["field"], "photo")


if __name__ == "__main__":
    unittest.main()
