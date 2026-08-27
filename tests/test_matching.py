import unittest

from pronear import matching as m


class ScoringTests(unittest.TestCase):
    def test_bayesian_prior_damps_single_review(self):
        few = m.bayesian_rating(5.0, 1)
        many = m.bayesian_rating(4.8, 200)
        self.assertLess(few, many)
        self.assertLess(abs(many - 4.8), 0.05)

    def test_bayesian_no_reviews_is_prior(self):
        self.assertAlmostEqual(m.bayesian_rating(None, 0), 4.0)

    def test_availability_now_beats_later(self):
        self.assertEqual(m.availability_score(0, True), 1.0)
        self.assertGreater(m.availability_score(30, False), m.availability_score(300, False))
        self.assertGreater(m.availability_score(300, False), m.availability_score(60 * 24 * 5, False))
        self.assertEqual(m.availability_score(None, False), 0.0)

    def test_distance_decays_and_zeroes_outside_radius(self):
        self.assertGreater(m.distance_score(1, 10), m.distance_score(5, 10))
        self.assertEqual(m.distance_score(10, 10), 0.0)
        self.assertEqual(m.distance_score(20, 10), 0.0)

    def test_price_within_budget_beats_over_budget(self):
        self.assertGreater(m.price_score(150, 200), m.price_score(260, 200))
        self.assertEqual(m.price_score(300, None), 0.6)  # בלי תקציב - ניטרלי
        self.assertEqual(m.price_score(10000, 100), 0.0)

    def test_trust_bounded(self):
        self.assertLessEqual(m.trust_score(True, 100, 1000), 1.0)
        self.assertEqual(m.trust_score(False, 0, 0), 0.0)

    def _candidate(self, **over):
        base = dict(distance_km=3.0, radius_km=15.0, available_now=False, minutes_until_free=120,
                    rating_avg=4.5, rating_count=20, hourly_rate=200, budget=None,
                    verified=False, years_experience=5, jobs_done=10)
        base.update(over)
        return m.score_candidate(**base)

    def test_score_in_range_and_has_breakdown(self):
        result = self._candidate()
        self.assertTrue(0 <= result["score"] <= 100)
        self.assertEqual(set(result["parts"]), set(m.WEIGHTS))

    def test_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(m.WEIGHTS.values()), 1.0, places=6)

    def test_available_now_outranks_equal_peer(self):
        now = self._candidate(available_now=True, minutes_until_free=0)
        later = self._candidate(available_now=False, minutes_until_free=60 * 30)
        self.assertGreater(now["score"], later["score"])

    def test_closer_outranks_farther(self):
        self.assertGreater(self._candidate(distance_km=1.0)["score"],
                           self._candidate(distance_km=12.0)["score"])

    def test_eta_text_variants(self):
        self.assertIn("להגיע", m.eta_text(2.0, 0, True))
        self.assertIn("אין זמינות", m.eta_text(2.0, None, False))
        self.assertIn("שעות", m.eta_text(2.0, 300, False))


if __name__ == "__main__":
    unittest.main()
