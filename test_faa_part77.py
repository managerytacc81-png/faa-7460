"""
Unit tests for FAA Part 77 Obstruction Evaluation & Lapse Engine
"""

import unittest
from faa_part77_engine import (
    haversine_distance_feet,
    Part77EvaluationEngine,
    OEAAALapseTracker,
    AirportRunway
)

class TestFAAPart77(unittest.TestCase):
    def test_haversine_accuracy(self):
        # 1 degree of latitude is approx 364,000 feet
        d = haversine_distance_feet(36.0, -115.0, 37.0, -115.0)
        self.assertAlmostEqual(d, 364800, delta=2000)

    def test_blanket_200ft_rule(self):
        # Structure 250 ft tall in middle of desert (no airports nearby)
        res = Part77EvaluationEngine.evaluate(35.0, -115.0, 1000.0, 250.0, [])
        self.assertTrue(res.notice_required)
        self.assertIn("exceeds the 200.0 ft AGL blanket threshold", res.reasons[0])

    def test_runway_100_to_1_slope(self):
        # Airport elevation 1000 ft AMSL, runway 5000 ft long
        # Site 10,000 ft away, ground elevation 1000 ft AMSL
        # 100:1 slope allows 1000 + (10000 / 100) = 1100 ft AMSL -> 100 ft AGL allowed
        rw = AirportRunway("TEST-RW", "Test Intl", 36.0, -115.0, 1000.0, 5000.0)
        # Lat offset of approx 10,000 ft is ~0.0274 degrees
        site_lat = 36.0274
        site_lon = -115.0

        # Crane 150 ft tall (exceeds 100 ft allowed)
        res = Part77EvaluationEngine.evaluate(site_lat, site_lon, 1000.0, 150.0, [rw])
        self.assertTrue(res.notice_required)

    def test_lapse_tracker(self):
        # Determination from today should be ACTIVE_VALID
        import datetime
        today_str = datetime.date.today().isoformat()
        res = OEAAALapseTracker.evaluate_case("2026-TEST-01", today_str)
        self.assertEqual(res["status"], "ACTIVE_VALID")
        self.assertGreater(res["days_remaining"], 500)

if __name__ == '__main__':
    unittest.main()
