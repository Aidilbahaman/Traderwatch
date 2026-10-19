#!/usr/bin/env python3
"""Regression tests for the AI-signal validator."""
import importlib.util
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / 'engine'


def load_importer():
    spec = importlib.util.spec_from_file_location('signal_import', ENGINE / 'signal-import.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SI = load_importer()


def h1(**kw):
    base = {'pair': 'XAU/USD', 'side': 'BUY', 'timeframe': 'H1',
            'entry': 4164.75, 'sl': 4149.20, 'tp': 4195.80}
    base.update(kw)
    return base


def m1(**kw):
    # XAU/USD pip = 0.1 -> 25 pip SL = 2.5, 50 pip TP = 5.0
    base = {'pair': 'XAU/USD', 'side': 'BUY', 'timeframe': 'M1',
            'entry': 4164.75, 'sl': 4162.25, 'tp': 4169.75}
    base.update(kw)
    return base


class ValidatorTests(unittest.TestCase):
    def test_valid_h1_passes(self):
        errors, m = SI.validate(h1(), set())
        self.assertEqual(errors, [])
        self.assertGreaterEqual(m['rr'], 1.5)

    def test_valid_m1_passes_with_1to2(self):
        errors, m = SI.validate(m1(), set())
        self.assertEqual(errors, [])
        self.assertEqual(m['sl_pips'], 25.0)
        self.assertEqual(m['rr'], 2.0)

    def test_buy_with_wrong_level_order_rejected(self):
        errors, _ = SI.validate(h1(sl=4180.0, tp=4140.0), set())
        self.assertTrue(any('sl < entry < tp' in e for e in errors))

    def test_m1_stop_too_tight_rejected(self):
        # 5 pips stop: 0.5 on XAU/USD
        errors, _ = SI.validate(m1(sl=4164.25, tp=4165.75), set())
        self.assertTrue(any('must be 20-40' in e for e in errors))

    def test_m1_stop_too_wide_rejected(self):
        # 60 pips stop: 6.0 on XAU/USD
        errors, _ = SI.validate(m1(sl=4158.75, tp=4176.75), set())
        self.assertTrue(any('must be 20-40' in e for e in errors))

    def test_m1_rr_out_of_band_rejected(self):
        # 25 pip stop, 12.5 pip TP -> R:R 0.5
        errors, _ = SI.validate(m1(tp=4166.00), set())
        self.assertTrue(any('reward:risk' in e for e in errors))

    def test_h1_rr_below_minimum_rejected(self):
        # 15.55 risk, 15.55 reward -> 1:1
        errors, _ = SI.validate(h1(tp=4180.30), set())
        self.assertTrue(any('at least 1.5' in e for e in errors))

    def test_active_pair_rejected(self):
        errors, _ = SI.validate(h1(), {'XAU/USD'})
        self.assertTrue(any('already has an active setup' in e for e in errors))

    def test_unknown_pair_rejected(self):
        errors, _ = SI.validate(h1(pair='BTC/USD'), set())
        self.assertTrue(any('not whitelisted' in e for e in errors))

    def test_bad_side_rejected(self):
        errors, _ = SI.validate(h1(side='LONG'), set())
        self.assertTrue(any('must be BUY or SELL' in e for e in errors))

    def test_backdated_rejected(self):
        errors, _ = SI.validate(h1(posted_at='2026-10-19T01:00:00Z'), set())
        self.assertTrue(any('no backdating' in e for e in errors))

    def test_sell_direction_valid(self):
        errors, m = SI.validate(
            {'pair': 'EUR/USD', 'side': 'SELL', 'timeframe': 'H1',
             'entry': 1.12248, 'sl': 1.12600, 'tp': 1.11500}, set())
        self.assertEqual(errors, [])
        self.assertGreaterEqual(m['rr'], 1.5)


if __name__ == '__main__':
    unittest.main()
