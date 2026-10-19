#!/usr/bin/env python3
"""Regression tests for TraderWatch signal lifecycle and pair dedupe."""
import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'engine'


def load_engine():
    spec = importlib.util.spec_from_file_location('signal_engine', ENGINE / 'signal-engine.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SignalPolicyTests(unittest.TestCase):
    def test_active_pair_blocks_second_timeframe(self):
        engine = load_engine()
        state = {
            'signals': {
                'AUDUSD_20261019_080035': {'status': 'active'},
                'EURUSD_20261019_080005': {'status': 'tp'},
            }
        }
        self.assertTrue(engine.pair_has_active_status('AUD/USD', state))
        self.assertFalse(engine.pair_has_active_status('EUR/USD', state))

    def test_same_run_reservation_blocks_second_setup(self):
        engine = load_engine()
        reserved = {'AUD/USD'}
        self.assertTrue(engine.should_block_pair('AUD/USD', {'signals': {}}, reserved))
        self.assertFalse(engine.should_block_pair('XAU/USD', {'signals': {}}, reserved))

    def test_m15_label_remains_m15(self):
        engine = load_engine()
        self.assertEqual(engine.public_timeframe('M15'), 'M15')
        self.assertEqual(engine.public_timeframe('H1'), 'H1')

    def test_scalping_has_no_time_expiry(self):
        status = load_status()
        self.assertIsNone(status.EXPIRY_SCALP)
        self.assertIsNotNone(status.EXPIRY_H1)
        self.assertEqual(status.EXPIRY_H1.total_seconds(), 48 * 3600)

    def test_engine_uses_m15_not_m1(self):
        engine = load_engine()
        self.assertIn('M15', engine.TIMEFRAMES)
        self.assertNotIn('M1', engine.TIMEFRAMES)
        self.assertEqual(engine.TIMEFRAMES['M15'], '15min')

    def test_m15_stop_floor_beats_thin_atr(self):
        engine = load_engine()
        # AUD/USD M15 ATR is ~4 pips; 1.5*ATR alone would be 6 pips.
        pip = engine.pip_size('AUD/USD')
        entry, sl, tp = engine.stop_and_target('BUY', 0.69848, 4 * pip,
                                               'AUD/USD', 'M15')
        sl_pips = abs(entry - sl) / pip
        tp_pips = abs(tp - entry) / pip
        self.assertGreaterEqual(sl_pips, 11.99)
        self.assertAlmostEqual(tp_pips / sl_pips, 2.0, places=2)

    def test_m15_keeps_wide_gold_atr(self):
        engine = load_engine()
        # XAU/USD M15 ATR ~65 pips, well above the floor: ATR must win.
        pip = engine.pip_size('XAU/USD')
        entry, sl, tp = engine.stop_and_target('BUY', 4161.0, 65 * pip,
                                               'XAU/USD', 'M15')
        sl_pips = abs(entry - sl) / pip
        self.assertGreater(sl_pips, 90)

    def test_h1_risk_model_unchanged(self):
        engine = load_engine()
        pip = engine.pip_size('EUR/USD')
        entry, sl, tp = engine.stop_and_target('BUY', 1.12, 20 * pip,
                                               'EUR/USD', 'H1')
        self.assertAlmostEqual(abs(entry - sl) / pip, 30.0, places=1)
        self.assertAlmostEqual(abs(tp - entry) / pip, 60.0, places=1)

    def test_session_window_excludes_asia_hours(self):
        engine = load_engine()
        from datetime import datetime, timezone, timedelta
        kl = timezone(timedelta(hours=8))
        self.assertFalse(engine.in_session(datetime(2026, 10, 19, 10, 0, tzinfo=kl)))
        self.assertTrue(engine.in_session(datetime(2026, 10, 19, 16, 0, tzinfo=kl)))
        self.assertTrue(engine.in_session(datetime(2026, 10, 19, 0, 30, tzinfo=kl)))
        self.assertFalse(engine.in_session(datetime(2026, 10, 19, 3, 0, tzinfo=kl)))


def load_status():
    spec = importlib.util.spec_from_file_location('signal_status', ENGINE / 'signal-status.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == '__main__':
    unittest.main()
