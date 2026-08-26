import datetime as dt
import unittest

from pronear import db, services, timeutil as tu
from pronear.services import AppError
from tests.base import DBTestCase


class UserTests(DBTestCase):
    def test_register_and_login(self):
        acc = services.register_user("דנה כהן", "Dana@Example.com", "password123", "050-1111111")
        self.assertIn("token", acc)
        logged = services.login("dana@example.com", "password123")  # אימייל לא רגיש לרישיות
        self.assertEqual(logged["user"]["id"], acc["user"]["id"])

    def test_wrong_password_rejected(self):
        services.register_user("דנה", "d@example.com", "password123")
        with self.assertRaises(AppError) as ctx:
            services.login("d@example.com", "wrong-password")
        self.assertEqual(ctx.exception.status, 401)

    def test_duplicate_email_rejected(self):
        services.register_user("אבי", "dup@example.com", "password123")
        with self.assertRaises(AppError) as ctx:
            services.register_user("בני", "DUP@example.com", "password123")
        self.assertEqual(ctx.exception.status, 409)

    def test_validation_errors(self):
        with self.assertRaises(AppError):
            services.register_user("אבי", "bad-email", "password123")
        with self.assertRaises(AppError):
            services.register_user("דנה", "ok@example.com", "short")


class ProfessionalTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.owner = services.register_user("רון חשמלאי", "ron@example.com", "password123")["user"]["id"]

    def _make_pro(self, **over):
        data = {"profession": "חשמלאי", "lat": 32.08, "lng": 34.78, "city": "תל אביב",
                "service_radius_km": 20, "hourly_rate": 250, "min_job_minutes": 60,
                "years_experience": 8}
        data.update(over)
        return services.upsert_professional(self.owner, data)

    def test_create_gets_default_schedule(self):
        pro = self._make_pro()
        self.assertTrue(pro["availability"])
        self.assertEqual(pro["availability"][0]["start"], "08:00")

    def test_update_is_idempotent_on_same_user(self):
        first = self._make_pro()
        second = self._make_pro(hourly_rate=300)
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(second["hourly_rate"], 300)

    def test_invalid_location_rejected(self):
        with self.assertRaises(AppError):
            self._make_pro(lat=999)

    def test_availability_merges_overlaps(self):
        pro = self._make_pro(availability=[
            {"weekday": 1, "start": "08:00", "end": "12:00"},
            {"weekday": 1, "start": "11:00", "end": "16:00"},
        ])
        rules = [r for r in pro["availability"] if r["weekday"] == 1]
        self.assertEqual(len(rules), 1)
        self.assertEqual((rules[0]["start"], rules[0]["end"]), ("08:00", "16:00"))

    def test_bad_availability_rejected(self):
        with self.assertRaises(AppError):
            self._make_pro(availability=[{"weekday": 1, "start": "18:00", "end": "09:00"}])
        with self.assertRaises(AppError):
            self._make_pro(availability=[{"weekday": 9, "start": "08:00", "end": "09:00"}])

    def test_owner_check(self):
        pro = self._make_pro()
        other = services.register_user("זר", "other@example.com", "password123")["user"]["id"]
        with self.assertRaises(AppError) as ctx:
            services.require_owner(pro["id"], other)
        self.assertEqual(ctx.exception.status, 403)


class SearchTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.always = self._pro("קרוב תמיד", "near@example.com", "חשמלאי", 32.081, 34.781,
                                [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)])
        self.far = self._pro("רחוק", "far@example.com", "חשמלאי", 32.79, 34.99,
                             [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)],
                             radius=100)
        self.closed = self._pro("סגור", "closed@example.com", "אינסטלטור", 32.083, 34.783, [])

    def _pro(self, name, email, profession, lat, lng, availability, radius=25, rate=200):
        uid = services.register_user(name, email, "password123")["user"]["id"]
        return services.upsert_professional(uid, {
            "profession": profession, "lat": lat, "lng": lng, "service_radius_km": radius,
            "hourly_rate": rate, "min_job_minutes": 60, "availability": availability,
        })

    def test_radius_filters_far_pro(self):
        res = services.search(lat=32.0853, lng=34.7818, radius_km=10)
        ids = [r["id"] for r in res["results"]]
        self.assertIn(self.always["id"], ids)
        self.assertNotIn(self.far["id"], ids)

    def test_service_radius_of_pro_is_respected(self):
        # איש מקצוע עם רדיוס שירות של 1 ק"מ לא יופיע ללקוח במרחק 5 ק"מ
        tight = self._pro("צר", "tight@example.com", "גנן", 32.13, 34.80, 
                          [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)], radius=1)
        res = services.search(lat=32.0853, lng=34.7818, radius_km=30)
        self.assertNotIn(tight["id"], [r["id"] for r in res["results"]])

    def test_available_now_filter(self):
        res = services.search(lat=32.0853, lng=34.7818, radius_km=10, only_available_now=True)
        ids = [r["id"] for r in res["results"]]
        self.assertIn(self.always["id"], ids)
        self.assertNotIn(self.closed["id"], ids)

    def test_profession_filter(self):
        res = services.search(lat=32.0853, lng=34.7818, radius_km=30, profession="אינסטלטור")
        self.assertTrue(all(r["profession"] == "אינסטלטור" for r in res["results"]))

    def test_text_search_matches_tags(self):
        uid = services.register_user("מומחה", "tagged@example.com", "password123")["user"]["id"]
        services.upsert_professional(uid, {
            "profession": "שיפוצניק", "lat": 32.086, "lng": 34.782, "service_radius_km": 20,
            "hourly_rate": 150, "tags": "ריצוף,אמבטיה",
            "availability": [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)]})
        res = services.search(lat=32.0853, lng=34.7818, radius_km=20, text="אמבטיה")
        self.assertEqual([r["profession"] for r in res["results"]], ["שיפוצניק"])

    def test_max_rate_filter(self):
        res = services.search(lat=32.0853, lng=34.7818, radius_km=30, max_rate=150)
        self.assertTrue(all(r["hourly_rate"] <= 150 for r in res["results"]))

    def test_sorting_by_distance(self):
        res = services.search(lat=32.0853, lng=34.7818, radius_km=100, sort="distance")
        distances = [r["distance_km"] for r in res["results"]]
        self.assertEqual(distances, sorted(distances))

    def test_search_at_specific_time(self):
        # יום שני הקרוב ב-03:00 - רק מי שפתוח 24/7 יימצא
        base = tu.local_midnight(tu.now_ts() + 3 * tu.DAY) + 3 * tu.HOUR
        res = services.search(lat=32.0853, lng=34.7818, radius_km=10, when="at", at_ts=base,
                              duration_minutes=60)
        ids = [r["id"] for r in res["results"]]
        self.assertIn(self.always["id"], ids)
        self.assertNotIn(self.closed["id"], ids)

    def test_invalid_location_rejected(self):
        with self.assertRaises(AppError):
            services.search(lat=200, lng=34.78)


class BookingTests(DBTestCase):
    def setUp(self):
        super().setUp()
        self.pro_user = services.register_user("איש מקצוע", "pro@example.com", "password123")["user"]["id"]
        self.pro = services.upsert_professional(self.pro_user, {
            "profession": "חשמלאי", "lat": 32.08, "lng": 34.78, "service_radius_km": 20,
            "hourly_rate": 200, "min_job_minutes": 60,
            "availability": [{"weekday": d, "start": "00:00", "end": "24:00"} for d in range(7)],
        })
        self.client = services.register_user("לקוח", "client@example.com", "password123")["user"]["id"]
        self.start = tu.local_midnight(tu.now_ts() + 2 * tu.DAY) + 10 * tu.HOUR

    def _book(self, **over):
        data = {"pro_id": self.pro["id"], "start": self.start, "duration_minutes": 60,
                "address": "הרצל 1", "lat": 32.085, "lng": 34.781}
        data.update(over)
        return services.create_booking(self.client, data)

    def test_create_and_price_estimate(self):
        booking = self._book(duration_minutes=90)
        self.assertEqual(booking["status"], "pending")
        self.assertEqual(booking["estimated_price"], 300)

    def test_double_booking_rejected(self):
        self._book()
        with self.assertRaises(AppError) as ctx:
            self._book()
        self.assertEqual(ctx.exception.status, 409)

    def test_adjacent_booking_allowed(self):
        self._book()
        later = self._book(start=self.start + tu.HOUR)
        self.assertEqual(later["status"], "pending")

    def test_past_booking_rejected(self):
        with self.assertRaises(AppError):
            self._book(start=tu.now_ts() - tu.DAY)

    def test_outside_service_area_rejected(self):
        with self.assertRaises(AppError) as ctx:
            self._book(lat=32.79, lng=34.99)
        self.assertIn("אזור השירות", ctx.exception.message)

    def test_below_minimum_duration_rejected(self):
        with self.assertRaises(AppError):
            self._book(duration_minutes=30)

    def test_cannot_book_self(self):
        with self.assertRaises(AppError):
            services.create_booking(self.pro_user, {"pro_id": self.pro["id"], "start": self.start})

    def test_status_flow_pro_confirms_then_done(self):
        booking = self._book()
        confirmed = services.set_booking_status(booking["id"], self.pro_user, "confirmed")
        self.assertEqual(confirmed["status"], "confirmed")
        self.assertIn("contact_phone", confirmed)
        done = services.set_booking_status(booking["id"], self.pro_user, "done")
        self.assertEqual(done["status"], "done")

    def test_client_cannot_confirm_own_booking(self):
        booking = self._book()
        with self.assertRaises(AppError) as ctx:
            services.set_booking_status(booking["id"], self.client, "confirmed")
        self.assertEqual(ctx.exception.status, 409)

    def test_stranger_cannot_view_booking(self):
        booking = self._book()
        stranger = services.register_user("זר", "stranger@example.com", "password123")["user"]["id"]
        with self.assertRaises(AppError) as ctx:
            services.get_booking(booking["id"], stranger)
        self.assertEqual(ctx.exception.status, 403)

    def test_cancelled_booking_frees_the_slot(self):
        booking = self._book()
        services.set_booking_status(booking["id"], self.client, "cancelled")
        again = self._book()
        self.assertEqual(again["status"], "pending")

    def test_pending_booking_blocks_search_at_that_time(self):
        self._book()
        res = services.search(lat=32.085, lng=34.781, radius_km=10, when="at", at_ts=self.start,
                              duration_minutes=60)
        self.assertNotIn(self.pro["id"], [r["id"] for r in res["results"]])

    def test_review_requires_done_status(self):
        booking = self._book()
        with self.assertRaises(AppError):
            services.add_review(self.client, booking["id"], 5, "מעולה")
        services.set_booking_status(booking["id"], self.pro_user, "confirmed")
        services.set_booking_status(booking["id"], self.pro_user, "done")
        review = services.add_review(self.client, booking["id"], 5, "מעולה")
        self.assertEqual(review["rating_summary"]["count"], 1)
        with self.assertRaises(AppError):  # ביקורת כפולה
            services.add_review(self.client, booking["id"], 4, "שוב")

    def test_contact_hidden_until_confirmed(self):
        booking = self._book()
        pro_view = services.get_professional(self.pro["id"], viewer_id=self.client)
        self.assertNotIn("phone", pro_view)
        services.set_booking_status(booking["id"], self.pro_user, "confirmed")
        pro_view = services.get_professional(self.pro["id"], viewer_id=self.client)
        self.assertIn("phone", pro_view)

    def test_list_bookings_by_role(self):
        self._book()
        self.assertEqual(len(services.list_bookings(self.client, "client")), 1)
        self.assertEqual(len(services.list_bookings(self.pro_user, "pro")), 1)


class TimeOffTests(DBTestCase):
    def setUp(self):
        super().setUp()
        uid = services.register_user("איש מקצוע", "p@example.com", "password123")["user"]["id"]
        self.pro = services.upsert_professional(uid, {
            "profession": "גנן", "lat": 32.08, "lng": 34.78, "hourly_rate": 100,
            "availability": [{"weekday": d, "start": "08:00", "end": "18:00"} for d in range(7)]})

    def test_add_list_delete(self):
        start = tu.now_ts() + tu.DAY
        off = services.add_time_off(self.pro["id"], start, start + tu.HOUR * 3, "חופשה")
        self.assertEqual(len(services.list_time_off(self.pro["id"])), 1)
        services.delete_time_off(self.pro["id"], off["id"])
        self.assertEqual(services.list_time_off(self.pro["id"]), [])

    def test_invalid_range_rejected(self):
        start = tu.now_ts() + tu.DAY
        with self.assertRaises(AppError):
            services.add_time_off(self.pro["id"], start, start - tu.HOUR)


if __name__ == "__main__":
    unittest.main()
