import datetime as dt
import unittest

from pronear import config, timeutil as tu


class TimezoneGuardTests(unittest.TestCase):
    def setUp(self):
        self._zone = config.TIMEZONE

    def tearDown(self):
        config.TIMEZONE = self._zone

    def test_missing_tz_database_raises_actionable_error(self):
        config.TIMEZONE = "Nowhere/Missing"
        with self.assertRaises(tu.TimezoneUnavailable) as ctx:
            tu.ensure_timezone()
        # ההודעה חייבת להסביר איך לתקן - זו שגיאת התקנה נפוצה ב-Windows
        self.assertIn("pip install tzdata", str(ctx.exception))
        self.assertIn("Nowhere/Missing", str(ctx.exception))

    def test_valid_timezone_passes(self):
        config.TIMEZONE = "Asia/Jerusalem"
        tu.ensure_timezone()

    def test_tz_is_cached(self):
        self.assertIs(tu.tz(), tu.tz())


class ParsingTests(unittest.TestCase):
    def test_parse_iso_formats(self):
        expected = tu.from_local(dt.datetime(2026, 8, 28, 20, 45))
        for value in ("2026-08-28T20:45", "2026-08-28 20:45", str(expected)):
            self.assertEqual(tu.parse_iso(value), expected)

    def test_parse_iso_tolerates_unencoded_plus(self):
        with_offset = tu.parse_iso("2026-08-28T20:45+03:00")
        self.assertEqual(tu.parse_iso("2026-08-28T20:45 03:00"), with_offset)

    def test_parse_iso_rejects_garbage(self):
        for value in ("", None, "not-a-date", "2026-13-45"):
            self.assertIsNone(tu.parse_iso(value))

    def test_parse_hhmm(self):
        self.assertEqual(tu.parse_hhmm("09:30"), 570)
        self.assertEqual(tu.parse_hhmm("9:30"), 570)
        self.assertEqual(tu.parse_hhmm("0930"), 570)
        self.assertEqual(tu.parse_hhmm("24:00"), 1440)
        for bad in ("25:00", "abc", "12:99"):
            with self.assertRaises(ValueError):
                tu.parse_hhmm(bad)

    def test_hhmm_roundtrip(self):
        for minutes in (0, 75, 570, 1439):
            self.assertEqual(tu.parse_hhmm(tu.hhmm(minutes)), minutes)


class LocalDayTests(unittest.TestCase):
    def test_local_day_offset_survives_dst_change(self):
        # יום מעבר השעון: 09:00 מקומי נשאר 09:00, גם כשהיממה קצרה מ-24 שעות
        day = tu.from_local(dt.datetime(2026, 3, 27, 0, 0))
        nine = tu.local_day_offset(day, 9 * 60)
        self.assertEqual(tu.minutes_into_day(nine), 9 * 60)

    def test_local_day_offset_midnight_boundary(self):
        day = tu.from_local(dt.datetime(2026, 5, 4, 0, 0))
        self.assertEqual(tu.local_day_offset(day, 0), day)
        self.assertEqual(tu.minutes_into_day(tu.local_day_offset(day, 1440)), 0)

    def test_weekday_convention_sunday_is_zero(self):
        sunday = tu.from_local(dt.datetime(2026, 5, 3, 12, 0))
        self.assertEqual(tu.weekday_of(sunday), 0)
        self.assertEqual(tu.WEEKDAY_NAMES[tu.weekday_of(sunday)], "ראשון")


if __name__ == "__main__":
    unittest.main()
