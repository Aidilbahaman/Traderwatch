#!/usr/bin/env python3
"""Regression: LLM analyst (enjin AI) — prompt, parse, validasi, fail-closed.

LLM buat keputusan muktamad (owner 2026-11-20). Output mesti JSON ketat;
parser extract JSON dari prose (model thinking macam GLM tulis reasoning
dahulu). Jarak SL/TP = keputusan LLM, TIADA cap. Validasi sanity: susunan
aras, RR1 >= 1.5, lantai spread.
"""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'engine'


def load_analyst():
    spec = importlib.util.spec_from_file_location(
        'llm_analyst', ENGINE / 'llm_analyst.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def bars_uptrend(n=120, start=3540.5):
    """120 bar uptrend; close terakhir = 3600.0 (start + 0.5*119)."""
    out = []
    for k in range(n):
        c = start + 0.5 * k
        out.append((k * 900000, c + 0.8, c - 0.8, c))
    return out


class PromptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        la = load_analyst()
        cls.la = la
        cls.bars = bars_uptrend()

    def test_resample_h1(self):
        h1 = self.la.resample_h1(self.bars)
        self.assertEqual(len(h1), len(self.bars) // 4)
        g = self.bars[:4]
        self.assertEqual(h1[0][2], max(b[1] for b in g))  # high
        self.assertEqual(h1[0][3], min(b[2] for b in g))  # low
        self.assertEqual(h1[0][4], g[-1][3])              # close

    def test_prompt_contains_context(self):
        price = self.bars[-1][3]
        h1 = self.la.resample_h1(self.bars)
        m15 = self.la.with_opens(self.bars)
        p = self.la.build_prompt('XAU/USD', price, h1[-24:], m15[-48:],
                                 atr=2.0, trend='UP', hh=3700.0, ll=3500.0,
                                 spread_pips=3.0)
        for token in ('XAU/USD', str(price), 'HOLD', 'You decide', 'H1', 'M15'):
            self.assertIn(token, p)
        self.assertNotIn('distance MAX', p)  # tiada cap SL dalam prompt
        self.assertLess(len(p), 6000)  # prompt ringkas — panjang gagal parse

    def test_prompt_held_blocks_opposite(self):
        price = self.bars[-1][3]
        h1 = self.la.resample_h1(self.bars)
        m15 = self.la.with_opens(self.bars)
        p = self.la.build_prompt('XAU/USD', price, h1[-24:], m15[-48:],
                                 atr=2.0, trend='DOWN', hh=3700.0, ll=3500.0,
                                 spread_pips=3.0, held={'SELL'})
        self.assertIn('no hedging', p)
        self.assertIn('Do NOT issue BUY', p)

    def test_prompt_no_held_no_hedge_line(self):
        price = self.bars[-1][3]
        h1 = self.la.resample_h1(self.bars)
        m15 = self.la.with_opens(self.bars)
        p = self.la.build_prompt('XAU/USD', price, h1[-24:], m15[-48:],
                                 atr=2.0, trend='UP', hh=3700.0, ll=3500.0,
                                 spread_pips=3.0, held=None)
        self.assertNotIn('no hedging', p)

    def test_prompt_both_held_prefers_hold(self):
        price = self.bars[-1][3]
        h1 = self.la.resample_h1(self.bars)
        m15 = self.la.with_opens(self.bars)
        p = self.la.build_prompt('XAU/USD', price, h1[-24:], m15[-48:],
                                 atr=2.0, trend='UP', hh=3700.0, ll=3500.0,
                                 spread_pips=3.0, held={'BUY', 'SELL'})
        self.assertIn('prefer HOLD', p)


class ParseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.la = load_analyst()

    def test_plain_json(self):
        j = self.la.parse_response('{"bias":"BUY","sl":3590,"tp1":3620,"tp2":3630,"confidence":7}')
        self.assertEqual(j['bias'], 'BUY')

    def test_json_wrapped_in_prose(self):
        raw = ('User wants analysis. Let me think.\nH1 downtrend...\n'
               '{"bias":"SELL","sl":3650,"tp1":3600,"tp2":3590,"confidence":8,"reason":"sweep high"}\n'
               'Done.')
        j = self.la.parse_response(raw)
        self.assertEqual(j['bias'], 'SELL')

    def test_code_fence(self):
        raw = '```json\n{"bias":"HOLD","confidence":3}\n```'
        self.assertEqual(self.la.parse_response(raw)['bias'], 'HOLD')

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            self.la.parse_response('I cannot provide financial advice.')


class ValidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.la = load_analyst()
        cls.price = 3600.0
        cls.pip = 0.1
        cls.spread = 3.0

    def v(self, j):
        return self.la.validate_verdict(j, self.price, self.pip, self.spread)

    def test_buy_valid(self):
        out = self.v({'bias': 'BUY', 'sl': 3596.0, 'tp1': 3606.0, 'tp2': 3608.0,
                      'confidence': 7, 'reason': 'demand sweep'})
        self.assertEqual(out['side'], 'BUY')
        self.assertAlmostEqual(out['conf'], 0.7)
        self.assertAlmostEqual(out['rr1'], 1.5)
        self.assertAlmostEqual(out['rr2'], 2.0)

    def test_sell_valid(self):
        out = self.v({'bias': 'SELL', 'sl': 3604.0, 'tp1': 3594.0, 'tp2': 3592.0,
                      'confidence': 8})
        self.assertEqual(out['side'], 'SELL')
        self.assertAlmostEqual(out['conf'], 0.8)

    def test_hold(self):
        out = self.v({'bias': 'HOLD', 'confidence': 2, 'reason': 'no setup'})
        self.assertEqual(out['side'], 'HOLD')

    def test_wrong_order_rejected(self):
        with self.assertRaises(ValueError):
            self.v({'bias': 'BUY', 'sl': 3604.0, 'tp1': 3606.0, 'tp2': 3608.0, 'confidence': 7})

    def test_wide_sl_allowed_llm_decides(self):
        # Tiada cap: SL $10 (struktur lebar) diterima jika RR/susunan sah.
        out = self.v({'bias': 'BUY', 'sl': 3590.0, 'tp1': 3615.0, 'tp2': 3620.0, 'confidence': 9})
        self.assertAlmostEqual(self.price - out['sl'], 10.0, places=4)
        self.assertAlmostEqual(out['rr1'], 1.5)

    def test_no_clamping(self):
        # Risiko $5.50 kekal $5.50 — LLM punya keputusan, tidak diskala.
        out = self.v({'bias': 'BUY', 'sl': 3594.5, 'tp1': 3608.25, 'tp2': 3611.0,
                      'confidence': 7})
        self.assertAlmostEqual(self.price - out['sl'], 5.5, places=4)
        self.assertAlmostEqual(out['rr2'], 2.0, places=2)

    def test_rr2_large_allowed(self):
        # TP jauh (RR2 5) dibenarkan — sasaran liquidity keputusan LLM.
        out = self.v({'bias': 'BUY', 'sl': 3596.0, 'tp1': 3606.0, 'tp2': 3620.0,
                      'confidence': 7})
        self.assertAlmostEqual(out['rr2'], 5.0)

    def test_sl_under_spread_floor_rejected(self):
        # lantai 3x spread = 9 pip = $0.9; SL $0.3 terlalu rapat
        with self.assertRaises(ValueError):
            self.v({'bias': 'BUY', 'sl': 3599.7, 'tp1': 3600.5, 'tp2': 3600.6, 'confidence': 7})

    def test_rr1_below_15_rejected(self):
        with self.assertRaises(ValueError):
            self.v({'bias': 'BUY', 'sl': 3596.0, 'tp1': 3604.0, 'tp2': 3608.0, 'confidence': 7})

    def test_missing_fields_rejected(self):
        with self.assertRaises(ValueError):
            self.v({'bias': 'BUY', 'sl': 3596.0, 'confidence': 7})

    def test_bad_bias_rejected(self):
        with self.assertRaises(ValueError):
            self.v({'bias': 'MAYBE', 'sl': 3596.0, 'tp1': 3606.0, 'tp2': 3608.0, 'confidence': 7})


class AnalyzeChainTests(unittest.TestCase):
    """analyze() dengan call disuntik — tiada network dalam unit test."""

    def setUp(self):
        self.la = load_analyst()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig = self.la.AUDIT_FILE
        self.la.AUDIT_FILE = Path(self.tmp.name) / 'audit.jsonl'
        self.bars = bars_uptrend()

    def tearDown(self):
        self.la.AUDIT_FILE = self._orig

    def test_valid_response_returns_verdict(self):
        def fake(model, prompt, timeout):
            return '{"bias":"BUY","sl":3596,"tp1":3606,"tp2":3608,"confidence":7,"reason":"ok"}'
        out = self.la.analyze('XAU/USD', self.bars, 0.1, 3.0, call=fake)
        self.assertIsNotNone(out)
        self.assertEqual(out['side'], 'BUY')
        self.assertTrue(self.la.AUDIT_FILE.exists())

    def test_prose_json_parsed(self):
        def fake(model, prompt, timeout):
            return ('Let me analyze the H1 trend first...\n'
                    '{"bias":"SELL","sl":3604,"tp1":3594,"tp2":3592,"confidence":8}')
        out = self.la.analyze('XAU/USD', self.bars, 0.1, 3.0, call=fake)
        self.assertIsNotNone(out)
        self.assertEqual(out['side'], 'SELL')

    def test_hold_returned(self):
        def fake(model, prompt, timeout):
            return '{"bias":"HOLD","confidence":2,"reason":"choppy"}'
        out = self.la.analyze('XAU/USD', self.bars, 0.1, 3.0, call=fake)
        self.assertEqual(out['side'], 'HOLD')

    def test_all_models_fail_returns_none(self):
        def fake(model, prompt, timeout):
            raise RuntimeError('502 Bad Gateway')
        self.assertIsNone(self.la.analyze('XAU/USD', self.bars, 0.1, 3.0, call=fake))

    def test_fallback_after_parse_failure(self):
        calls = []
        def fake(model, prompt, timeout):
            calls.append(model)
            if len(calls) == 1:
                return 'no json here'
            return '{"bias":"BUY","sl":3596,"tp1":3606,"tp2":3608,"confidence":7}'
        out = self.la.analyze('XAU/USD', self.bars, 0.1, 3.0, call=fake)
        self.assertIsNotNone(out)
        self.assertGreaterEqual(len(calls), 2)

    def test_invalid_levels_not_shopped(self):
        # Aras tidak sah (SL atas entry untuk BUY) = penolakan muktamad,
        # bukan cuba model lain sampai dapat jawapan yang lepas (fail-closed).
        calls = []
        def fake(model, prompt, timeout):
            calls.append(model)
            return '{"bias":"BUY","sl":3610,"tp1":3615,"tp2":3620,"confidence":9}'
        out = self.la.analyze('XAU/USD', self.bars, 0.1, 3.0, call=fake)
        self.assertIsNone(out)
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()