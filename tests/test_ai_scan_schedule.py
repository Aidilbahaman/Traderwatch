#!/usr/bin/env python3
"""Regression: AI engine scan 24 jam selagi pasaran buka (owner 2026-11-20).

Sebelum ini sesi 08:00-01:00 MYT sahaja (01:00-08:00 tak scan). Sekarang
in_session() hanya false bila pasaran forex tutup: Jumaat 21:00 UTC hingga
Ahad 21:00 UTC — window sama seperti signal-lifecycle-alert.market_closed.
"""
import importlib.util
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'engine'
MYT = timezone(timedelta(hours=8))


def load_ai_engine():
    spec = importlib.util.spec_from_file_location(
        'ai_engine_schedule', ENGINE / 'signal-engine-ai.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def utc(y, mo, d, h, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=timezone.utc)


class AiScanScheduleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = load_ai_engine()

    def test_weekday_scans_all_hours(self):
        # Rabu 2026-11-18: setiap jam, termasuk 01:00-08:00 MYT yang dulu skip.
        for hour_myt in range(24):
            t = datetime(2026, 11, 18, hour_myt, 30, tzinfo=MYT)
            self.assertTrue(self.ai.in_session(t), f"Rabu {hour_myt:02d}:30 MYT")

    def test_early_morning_myt_now_scans(self):
        # 05:40 MYT = 21:40 UTC Rabu — dulu di luar sesi, sekarang scan.
        self.assertTrue(self.ai.in_session(datetime(2026, 11, 19, 5, 40, tzinfo=MYT)))

    def test_friday_cutoff_21utc(self):
        self.assertTrue(self.ai.in_session(utc(2026, 11, 20, 20, 59)))   # Jumaat
        self.assertFalse(self.ai.in_session(utc(2026, 11, 20, 21, 0)))

    def test_saturday_closed(self):
        self.assertFalse(self.ai.in_session(utc(2026, 11, 21, 12, 0)))

    def test_sunday_reopens_21utc(self):
        self.assertFalse(self.ai.in_session(utc(2026, 11, 22, 20, 59)))  # Ahad
        self.assertTrue(self.ai.in_session(utc(2026, 11, 22, 21, 0)))

    def test_monday_myt_reopens_0500(self):
        # Ahad 21:00 UTC = Isnin 05:00 MYT. Sebelum itu masih tutup.
        self.assertFalse(self.ai.in_session(datetime(2026, 11, 23, 0, 0, tzinfo=MYT)))
        self.assertFalse(self.ai.in_session(datetime(2026, 11, 23, 4, 59, tzinfo=MYT)))
        self.assertTrue(self.ai.in_session(datetime(2026, 11, 23, 5, 0, tzinfo=MYT)))


if __name__ == '__main__':
    unittest.main()