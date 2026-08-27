import math
import unittest

from pronear import geo


class GeoTests(unittest.TestCase):
    def test_known_distance_tlv_haifa(self):
        d = geo.haversine_km(32.0853, 34.7818, 32.7940, 34.9896)
        self.assertAlmostEqual(d, 80.5, delta=2.0)

    def test_zero_distance(self):
        self.assertEqual(geo.haversine_km(32.0, 34.0, 32.0, 34.0), 0.0)

    def test_symmetry(self):
        a = geo.haversine_km(32.0, 34.0, 31.5, 34.9)
        b = geo.haversine_km(31.5, 34.9, 32.0, 34.0)
        self.assertAlmostEqual(a, b, places=9)

    def test_bounding_box_contains_circle(self):
        lat, lng, r = 32.08, 34.78, 10.0
        min_lat, max_lat, min_lng, max_lng = geo.bounding_box(lat, lng, r)
        # נקודה במרחק r בדיוק צפונה ומזרחה חייבת להיות בתוך התיבה
        north = lat + r / 110.574
        east = lng + r / (111.320 * math.cos(math.radians(lat)))
        self.assertLessEqual(north, max_lat + 1e-9)
        self.assertLessEqual(east, max_lng + 1e-9)
        self.assertGreaterEqual(lat - r / 110.574, min_lat - 1e-9)
        self.assertGreaterEqual(lng, min_lng)

    def test_bounding_box_near_pole_is_safe(self):
        box = geo.bounding_box(89.999, 0.0, 50)
        self.assertEqual((box[2], box[3]), (-180.0, 180.0))

    def test_valid_coords(self):
        self.assertTrue(geo.valid_coords(32.0, 34.0))
        self.assertFalse(geo.valid_coords(95.0, 34.0))
        self.assertFalse(geo.valid_coords("abc", 34.0))
        self.assertFalse(geo.valid_coords(None, None))

    def test_travel_minutes_monotonic(self):
        self.assertEqual(geo.travel_minutes(0), 0)
        self.assertLess(geo.travel_minutes(2), geo.travel_minutes(10))


if __name__ == "__main__":
    unittest.main()
