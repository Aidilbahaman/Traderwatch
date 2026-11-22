#!/usr/bin/env python3
"""Regression tests: AI engine (M15) SL/TP mesti ketat untuk akaun kecil.

SL = SL_ATR_MULT x ATR M15, lantai 3x spread, dipagari cap harga per pair.
TP kekal RR 1:2 supaya lifecycle TP1/TP2 dan signal-import tidak berubah.
"""
import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'engine'


def load_ai_engine():
    spec = importlib.util.spec_from_file_location(
        'ai_engine_levels', ENGINE / 'signal-engine-ai.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class AiSmallAccountLevelsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = load_ai_engine()

    def test_timeframe_is_m15(self):
        self.assertEqual(self.ai.TIMEFRAME, 'M15')
        self.assertEqual(self.ai.TD_INTERVAL, '15min')

    def test_gold_sl_capped_when_atr_high(self):
        # ATR M15 tinggi (8.0): SL mesti ikut cap, bukan 2.5xATR (~$20).
        cap = self.ai.MAX_SL_PRICE['XAU/USD']
        sl, tp = self.ai.build_levels('XAU/USD', 'BUY', 4000.0, 8.0)
        self.assertAlmostEqual(4000.0 - sl, cap, places=6)
        self.assertAlmostEqual(tp - 4000.0, 2 * cap, places=6)

    def test_sell_direction_mirrored(self):
        cap = self.ai.MAX_SL_PRICE['XAU/USD']
        sl, tp = self.ai.build_levels('XAU/USD', 'SELL', 4000.0, 8.0)
        self.assertAlmostEqual(sl - 4000.0, cap, places=6)
        self.assertAlmostEqual(4000.0 - tp, 2 * cap, places=6)

    def test_atr_mult_used_below_cap(self):
        want = self.ai.SL_ATR_MULT * 2.0
        self.assertLess(want, self.ai.MAX_SL_PRICE['XAU/USD'])
        sl, tp = self.ai.build_levels('XAU/USD', 'BUY', 4000.0, 2.0)
        self.assertAlmostEqual(4000.0 - sl, want, places=6)
        self.assertAlmostEqual(tp - 4000.0, 2 * want, places=6)

    def test_spread_floor_beats_thin_atr(self):
        # ATR terlalu kecil: lantai min(8 pip, 3x spread) mesti menang.
        # XAU spread 3 pip -> lantai 8 pip = 0.8 harga.
        sl, _ = self.ai.build_levels('XAU/USD', 'BUY', 4000.0, 0.01)
        self.assertGreaterEqual(4000.0 - sl, 0.8 - 1e-9)

    def test_all_pairs_capped_and_rr_two(self):
        cases = [('XAU/USD', 4000.0, 8.0), ('XAG/USD', 44.0, 0.5),
                 ('BTCUSD', 62000.0, 600.0)]
        for pair, price, atr in cases:
            cap = self.ai.MAX_SL_PRICE[pair]
            sl, tp = self.ai.build_levels(pair, 'BUY', price, atr)
            risk = price - sl
            self.assertLessEqual(risk, cap + 1e-9, pair)
            self.assertAlmostEqual((tp - price) / risk, 2.0, places=6)

    def test_cap_never_below_spread_floor(self):
        # Cap tidak boleh menekan SL bawah lantai spread (drag spread > SL).
        for pair in self.ai.PAIRS:
            cap = self.ai.MAX_SL_PRICE[pair]
            sl, _ = self.ai.build_levels(pair, 'BUY', 1000.0, 0.0)
            self.assertGreater(1000.0 - sl, 0.0, pair)
            self.assertLessEqual(1000.0 - sl, max(cap, 1e-9) + 1e-9, pair)


if __name__ == '__main__':
    unittest.main()