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

    def test_m1_label_remains_m1(self):
        engine = load_engine()
        self.assertEqual(engine.public_timeframe('M1'), 'M1')
        self.assertEqual(engine.public_timeframe('H1'), 'H1')
    def test_scalping_has_no_time_expiry(self):
        status = load_status()
        self.assertIsNone(status.EXPIRY_SCALP)
        self.assertIsNotNone(status.EXPIRY_H1)


def load_status():
    spec = importlib.util.spec_from_file_location('signal_status', ENGINE / 'signal-status.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


if __name__ == '__main__':
    unittest.main()
