import datetime as dt
import unittest

from pronear import availability as av, db, services, timeutil as tu
from tests.base import DBTestCase


class IntervalAlgebraTests(unittest.TestCase):
    def test_merge_overlapping_and_touching(self):
        self.assertEqual(av.merge([(0, 5), (5, 9), (20, 25)]), [(0, 9), (20, 25)])

    def test_merge_drops_empty(self):
        self.assertEqual(av.merge([(5, 5), (1, 3)]), [(1, 3)])

    def test_subtract_middle(self):
        self.assertEqual(av.subtract([(0, 100)], [(40, 60)]), [(0, 40), (60, 100)])

    def test_subtract_full_cover(self):
        self.assertEqual(av.subtract([(10, 20)], [(0, 30)]), [])

    def test_subtract_edges(self):
        self.assertEqual(av.subtract([(0, 10)], [(0, 4)]), [(4, 10)])
        self.assertEqual(av.subtract([(0, 10)], [(6, 10)]), [(0, 6)])

    def test_clip(self):
        self.assertEqual(av.clip([(0, 100)], 20, 50), [(20, 50)])
        self.assertEqual(av.clip([(0, 10)], 50, 60), [])


class ExpandRulesTests(unittest.TestCase):
    def test_weekly_rule_expands_once_per_week(self):
        # יום ראשון 09:00-17:00 לאורך 14 יום => שני מופעים
        start = tu.from_local(dt.datetime(2026, 3, 1, 0, 0))  # ראשון
        end = start + 14 * tu.DAY
        rules = [{"weekday": 0, "start_min": 9 * 60, "end_min": 17 * 60}]
        windows = av.expand_rules(rules, start, end)
        self.assertEqual(len(windows), 2)
        for s, e in windows:
            self.assertEqual(tu.weekday_of(s), 0)
            self.assertEqual(tu.minutes_into_day(s), 9 * 60)
            self.assertEqual((e - s), 8 * tu.HOUR)

    def test_expand_clips_to_range(self):
        start = tu.from_local(dt.datetime(2026, 3, 2, 12, 0))
        end = tu.from_local(dt.datetime(2026, 3, 2, 14, 0))
        rules = [{"weekday": 1, "start_min": 8 * 60, "end_min": 20 * 60}]
        self.assertEqual(av.expand_rules(rules, start, end), [(start, end)])

    def test_dst_transition_keeps_local_hours(self):
        # מעבר לשעון קיץ בישראל 2026 - הלוח נשאר 09:00 מקומי בכל יום
        start = tu.from_local(dt.datetime(2026, 3, 25, 0, 0))
        end = tu.from_local(dt.datetime(2026, 4, 1, 0, 0))
        rules = [{"weekday": d, "start_min": 9 * 60, "end_min": 10 * 60} for d in range(7)]
        for s, e in av.expand_rules(rules, start, end):
            self.assertEqual(tu.minutes_into_day(s), 9 * 60)
            self.assertEqual(tu.minutes_into_day(e), 10 * 60)

    def test_no_rules_no_windows(self):
        self.assertEqual(av.expand_rules([], 0, 10**6), [])


class FreeWindowTests(DBTestCase):
    def setUp(self):
        super().setUp()
        acc = services.register_user("בודק", "t@example.com", "password123")
        self.user_id = acc["user"]["id"]
        pro = services.upsert_professional(self.user_id, {
            "profession": "חשמלאי", "lat": 32.08, "lng": 34.78,
            "service_radius_km": 20, "hourly_rate": 200, "min_job_minutes": 60,
            "availability": [{"weekday": d, "start": "08:00", "end": "18:00"} for d in range(7)],
        })
        self.pro_id = pro["id"]
        self.day = tu.from_local(dt.datetime(2026, 5, 4, 0, 0))  # שני

    def test_full_day_window(self):
        windows = av.free_windows(self.pro_id, self.day, self.day + tu.DAY)
        self.assertEqual(len(windows), 1)
        self.assertEqual(tu.minutes_into_day(windows[0][0]), 8 * 60)

    def test_time_off_splits_window(self):
        services.add_time_off(self.pro_id, self.day + 10 * tu.HOUR, self.day + 12 * tu.HOUR, "פגישה")
        windows = av.free_windows(self.pro_id, self.day, self.day + tu.DAY)
        self.assertEqual(len(windows), 2)
        self.assertFalse(av.is_free_at(self.pro_id, self.day + 10 * tu.HOUR + 60, self.day + 11 * tu.HOUR))

    def test_booking_blocks_slot(self):
        db.execute(
            "INSERT INTO bookings(pro_id, client_user_id, start_ts, end_ts, status, created_at) "
            "VALUES (?,?,?,?, 'confirmed', 0)",
            (self.pro_id, self.user_id, self.day + 9 * tu.HOUR, self.day + 11 * tu.HOUR),
        )
        self.assertFalse(av.is_free_at(self.pro_id, self.day + 9 * tu.HOUR, self.day + 10 * tu.HOUR))
        self.assertTrue(av.is_free_at(self.pro_id, self.day + 11 * tu.HOUR, self.day + 12 * tu.HOUR))

    def test_declined_booking_does_not_block(self):
        db.execute(
            "INSERT INTO bookings(pro_id, client_user_id, start_ts, end_ts, status, created_at) "
            "VALUES (?,?,?,?, 'declined', 0)",
            (self.pro_id, self.user_id, self.day + 9 * tu.HOUR, self.day + 11 * tu.HOUR),
        )
        self.assertTrue(av.is_free_at(self.pro_id, self.day + 9 * tu.HOUR, self.day + 10 * tu.HOUR))

    def test_min_duration_filter(self):
        services.add_time_off(self.pro_id, self.day + 9 * tu.HOUR, self.day + 17 * tu.HOUR, "")
        # נותרו 08:00-09:00 ו-17:00-18:00 => אין חלון של 90 דקות
        self.assertEqual(av.free_windows(self.pro_id, self.day, self.day + tu.DAY, min_minutes=90), [])
        self.assertEqual(len(av.free_windows(self.pro_id, self.day, self.day + tu.DAY, min_minutes=60)), 2)

    def test_next_free_skips_blocked_day(self):
        services.add_time_off(self.pro_id, self.day, self.day + tu.DAY, "חופש")
        nxt = av.next_free(self.pro_id, self.day + 8 * tu.HOUR, min_minutes=60)
        self.assertIsNotNone(nxt)
        self.assertGreaterEqual(nxt[0], self.day + tu.DAY)

    def test_slots_are_aligned_and_bounded(self):
        found = av.slots(self.pro_id, self.day, self.day + tu.DAY, duration_minutes=60, step_minutes=30)
        self.assertTrue(found)
        for s, e in found:
            self.assertEqual(e - s, tu.HOUR)
            self.assertEqual(tu.minutes_into_day(s) % 30, 0)
        self.assertEqual(found[0][0], self.day + 8 * tu.HOUR)

    def test_available_now_respects_schedule(self):
        inside = self.day + 9 * tu.HOUR
        outside = self.day + 3 * tu.HOUR
        self.assertTrue(av.available_now(self.pro_id, inside))
        self.assertFalse(av.available_now(self.pro_id, outside))


if __name__ == "__main__":
    unittest.main()
