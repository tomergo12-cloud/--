"""בדיקות API דרך שכבת הניתוב (ללא צורך בשרת חי)."""

import json
import unittest

from pronear import api, timeutil as tu
from tests.base import DBTestCase


class Headers(dict):
    """חיקוי של email.message.Message שמגיע מ-http.server."""

    def get(self, key, default=None):
        for k, v in self.items():
            if k.lower() == str(key).lower():
                return v
        return default


class ApiTestCase(DBTestCase):
    def call(self, method, path, body=None, token=None):
        headers = Headers({"Authorization": f"Bearer {token}"} if token else {})
        status, payload = api.dispatch(method, path, body or {}, headers)
        return status, payload

    def signup(self, email="user@example.com", name="משתמש בדיקה"):
        status, payload = self.call("POST", "/api/auth/register",
                                    {"name": name, "email": email, "password": "password123",
                                     "phone": "050-0000000"})
        self.assertEqual(status, 201, payload)
        return payload["token"], payload["user"]["id"]


class RoutingTests(ApiTestCase):
    def test_health(self):
        status, payload = self.call("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(payload["ok"])

    def test_unknown_route_404(self):
        self.assertEqual(self.call("GET", "/api/nope")[0], 404)

    def test_wrong_method_405(self):
        self.assertEqual(self.call("DELETE", "/api/health")[0], 405)

    def test_trailing_slash_and_query_ignored(self):
        self.assertEqual(self.call("GET", "/api/health/?x=1")[0], 200)

    def test_meta_lists_professions(self):
        status, payload = self.call("GET", "/api/meta")
        self.assertEqual(status, 200)
        self.assertIn("חשמלאי", payload["professions"])


class AuthApiTests(ApiTestCase):
    def test_register_login_me_logout(self):
        token, user_id = self.signup()
        status, payload = self.call("GET", "/api/auth/me", token=token)
        self.assertEqual(status, 200)
        self.assertEqual(payload["user"]["id"], user_id)

        status, payload = self.call("POST", "/api/auth/login",
                                    {"email": "user@example.com", "password": "password123"})
        self.assertEqual(status, 200)

        self.assertEqual(self.call("POST", "/api/auth/logout", token=token)[0], 200)
        self.assertEqual(self.call("GET", "/api/auth/me", token=token)[0], 401)

    def test_me_requires_auth(self):
        self.assertEqual(self.call("GET", "/api/auth/me")[0], 401)

    def test_bad_token_rejected(self):
        self.assertEqual(self.call("GET", "/api/auth/me", token="not-a-real-token")[0], 401)

    def test_duplicate_email_conflict(self):
        self.signup()
        status, payload = self.call("POST", "/api/auth/register",
                                    {"name": "אחר", "email": "user@example.com", "password": "password123"})
        self.assertEqual(status, 409)
        self.assertEqual(payload["field"], "email")


class ProApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.token, self.user_id = self.signup("pro@example.com", "רון החשמלאי")
        status, self.pro = self.call("POST", "/api/pros", {
            "profession": "חשמלאי", "headline": "תקלות חשמל 24/7", "city": "תל אביב",
            "lat": 32.081, "lng": 34.781, "service_radius_km": 20, "hourly_rate": 250,
            "min_job_minutes": 60, "years_experience": 10, "tags": "תקלות,לוח חשמל",
            "availability": [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)],
        }, token=self.token)
        self.assertEqual(status, 201, self.pro)

    def test_create_requires_auth(self):
        self.assertEqual(self.call("POST", "/api/pros", {"profession": "גנן"})[0], 401)

    def test_get_public_profile_hides_phone(self):
        status, payload = self.call("GET", f"/api/pros/{self.pro['id']}")
        self.assertEqual(status, 200)
        self.assertNotIn("phone", payload)
        self.assertTrue(payload["available_now"])

    def test_owner_sees_own_phone(self):
        _, payload = self.call("GET", f"/api/pros/{self.pro['id']}", token=self.token)
        self.assertIn("phone", payload)

    def test_update_by_stranger_forbidden(self):
        other, _ = self.signup("other@example.com", "זר")
        status, _ = self.call("PUT", f"/api/pros/{self.pro['id']}",
                              {"profession": "גנן", "lat": 32.0, "lng": 34.0}, token=other)
        self.assertEqual(status, 403)

    def test_update_availability(self):
        status, payload = self.call("PUT", f"/api/pros/{self.pro['id']}/availability",
                                    {"availability": [{"weekday": 2, "start": "09:00", "end": "13:00"}]},
                                    token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(len(payload["availability"]), 1)
        self.assertEqual(payload["availability"][0]["weekday_name"], "שלישי")

    def test_invalid_availability_400(self):
        status, payload = self.call("PUT", f"/api/pros/{self.pro['id']}/availability",
                                    {"availability": [{"weekday": 2, "start": "25:00", "end": "26:00"}]},
                                    token=self.token)
        self.assertEqual(status, 400)

    def test_slots_endpoint(self):
        status, payload = self.call("GET", f"/api/pros/{self.pro['id']}/slots?days=2&duration=60&step=60")
        self.assertEqual(status, 200)
        self.assertTrue(payload["slots"])
        self.assertEqual(payload["duration_minutes"], 60)

    def test_time_off_crud(self):
        start = tu.now_ts() + tu.DAY
        status, off = self.call("POST", f"/api/pros/{self.pro['id']}/time-off",
                                {"start": start, "end": start + 3 * tu.HOUR, "reason": "חופשה"},
                                token=self.token)
        self.assertEqual(status, 201)
        _, listing = self.call("GET", f"/api/pros/{self.pro['id']}/time-off", token=self.token)
        self.assertEqual(len(listing["time_off"]), 1)
        self.assertEqual(self.call("DELETE", f"/api/pros/{self.pro['id']}/time-off/{off['id']}",
                                   token=self.token)[0], 200)
        _, listing = self.call("GET", f"/api/pros/{self.pro['id']}/time-off", token=self.token)
        self.assertEqual(listing["time_off"], [])

    def test_time_off_of_others_forbidden(self):
        other, _ = self.signup("x@example.com", "זר")
        self.assertEqual(self.call("GET", f"/api/pros/{self.pro['id']}/time-off", token=other)[0], 403)


class SearchApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        token, _ = self.signup("pro@example.com", "רון")
        self.call("POST", "/api/pros", {
            "profession": "אינסטלטור", "lat": 32.081, "lng": 34.781, "service_radius_km": 20,
            "hourly_rate": 200, "city": "תל אביב",
            "availability": [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)],
        }, token=token)

    def test_search_requires_location(self):
        status, payload = self.call("GET", "/api/search?radius_km=10")
        self.assertEqual(status, 400)
        self.assertEqual(payload["field"], "lat")

    def test_search_returns_scored_results(self):
        status, payload = self.call("GET", "/api/search?lat=32.0853&lng=34.7818&radius_km=10&available_now=1")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)
        result = payload["results"][0]
        self.assertTrue(result["available_now"])
        self.assertIn("score_parts", result)
        self.assertLess(result["distance_km"], 1.0)

    def test_search_bad_number_400(self):
        self.assertEqual(self.call("GET", "/api/search?lat=abc&lng=34.7")[0], 400)

    def test_search_with_time_filter(self):
        at = tu.to_iso(tu.now_ts() + 2 * tu.DAY)
        status, payload = self.call("GET", f"/api/search?lat=32.0853&lng=34.7818&when=at&at={at}&duration=60")
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)

    def test_search_profession_filter_excludes(self):
        _, payload = self.call("GET", "/api/search?lat=32.0853&lng=34.7818&profession=חשמלאי")
        self.assertEqual(payload["total"], 0)


class BookingApiTests(ApiTestCase):
    def setUp(self):
        super().setUp()
        self.pro_token, _ = self.signup("pro@example.com", "רון")
        _, self.pro = self.call("POST", "/api/pros", {
            "profession": "חשמלאי", "lat": 32.081, "lng": 34.781, "service_radius_km": 20,
            "hourly_rate": 200, "min_job_minutes": 60,
            "availability": [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)],
        }, token=self.pro_token)
        self.client_token, _ = self.signup("client@example.com", "לקוח")
        self.start = tu.local_midnight(tu.now_ts() + 2 * tu.DAY) + 10 * tu.HOUR

    def _book(self, **over):
        body = {"pro_id": self.pro["id"], "start": tu.to_iso(self.start), "duration_minutes": 60,
                "address": "הרצל 1", "lat": 32.085, "lng": 34.781, "note": "תקלה בלוח"}
        body.update(over)
        return self.call("POST", "/api/bookings", body, token=self.client_token)

    def test_full_booking_lifecycle(self):
        status, booking = self._book()
        self.assertEqual(status, 201, booking)
        self.assertEqual(booking["status"], "pending")

        status, payload = self.call("GET", "/api/bookings?role=pro", token=self.pro_token)
        self.assertEqual(len(payload["bookings"]), 1)

        status, confirmed = self.call("POST", f"/api/bookings/{booking['id']}/status",
                                      {"status": "confirmed"}, token=self.pro_token)
        self.assertEqual(confirmed["status"], "confirmed")

        _, done = self.call("POST", f"/api/bookings/{booking['id']}/status",
                            {"status": "done"}, token=self.pro_token)
        self.assertEqual(done["status"], "done")

        status, review = self.call("POST", f"/api/bookings/{booking['id']}/review",
                                   {"rating": 5, "comment": "מעולה"}, token=self.client_token)
        self.assertEqual(status, 201)
        _, pro = self.call("GET", f"/api/pros/{self.pro['id']}")
        self.assertEqual(pro["rating"]["count"], 1)
        self.assertEqual(pro["rating"]["avg"], 5.0)

    def test_booking_requires_auth(self):
        status, _ = self.call("POST", "/api/bookings", {"pro_id": self.pro["id"]})
        self.assertEqual(status, 401)

    def test_conflicting_booking_409(self):
        self._book()
        status, payload = self._book()
        self.assertEqual(status, 409)

    def test_bad_time_400(self):
        status, _ = self._book(start="not-a-time")
        self.assertEqual(status, 400)

    def test_client_cannot_review_before_done(self):
        _, booking = self._book()
        status, _ = self.call("POST", f"/api/bookings/{booking['id']}/review",
                              {"rating": 5}, token=self.client_token)
        self.assertEqual(status, 409)

    def test_stranger_cannot_read_booking(self):
        _, booking = self._book()
        other, _ = self.signup("z@example.com", "זר")
        self.assertEqual(self.call("GET", f"/api/bookings/{booking['id']}", token=other)[0], 403)

    def test_json_payload_is_serializable(self):
        _, booking = self._book()
        json.dumps(booking, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()
