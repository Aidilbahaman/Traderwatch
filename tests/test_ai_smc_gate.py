#!/usr/bin/env python3
"""Regression tests: SMC gate AI engine — scan hidup, entry struktur, dedupe.

Bug lama: SMC.detect(bars) guna bar terakhir sebagai sweep bar, sedangkan
FVG siap 2-5 bar SELEPAS sweep -> mustahil fire. smc_live_scan membetulkan
semantik: cari sweep bar yang FVG-nya baru siap dalam TTL entry, dan entry
belum disentuh harga selepas FVG (virgin retest).
"""
import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'engine'


def load_ai_engine():
    spec = importlib.util.spec_from_file_location(
        'ai_engine_smc', ENGINE / 'signal-engine-ai.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def mkbar(k, o, h, l, c):
    return (k * 900000, h, l, c)


def buy_bars(n=110):
    """Uptrend tenang, sweep BUY di bar n-3, FVG siap pada bar terakhir (n-1).

    Entry = high bar sweep; SL bawah wick sweep. Bar selepas FVG: tiada
    (FVG pada bar terakhir) -> entry belum disentuh.
    """
    bars = []
    for k in range(n - 3):
        c = 100.0 + 0.15 * k
        bars.append(mkbar(k, c, c + 0.3, c - 0.3, c))
    i = n - 3
    low_ext = min(b[2] for b in bars[i - 20:i])
    sweep_low = low_ext - 1.0
    sweep_close = low_ext + 0.5
    bars.append(mkbar(i, sweep_close, sweep_close + 0.3, sweep_low, sweep_close))
    entry = sweep_close + 0.3  # high bar sweep = tepi FVG (BUY)
    c1 = sweep_close + 2.0
    bars.append(mkbar(i + 1, c1, c1 + 0.3, sweep_close + 0.5, c1))
    f = n - 1
    fl = entry + 0.5           # gap atas high bar sweep
    fc = fl + 2.0              # displacement kuat
    bars.append(mkbar(f, fc, fc + 0.3, fl, fc))
    return bars, entry


def sell_bars(n=110):
    """Cermin SELL: downtrend, sweep high, FVG bearish pada bar terakhir."""
    bars = []
    for k in range(n - 3):
        c = 200.0 - 0.15 * k
        bars.append(mkbar(k, c, c + 0.3, c - 0.3, c))
    i = n - 3
    high_ext = max(b[1] for b in bars[i - 20:i])
    sweep_high = high_ext + 1.0
    sweep_close = high_ext - 0.5
    bars.append(mkbar(i, sweep_close, sweep_high, sweep_close - 0.3, sweep_close))
    entry = sweep_close - 0.3  # low bar sweep = tepi FVG (SELL)
    c1 = sweep_close - 2.0
    bars.append(mkbar(i + 1, c1, c1 - 0.3 + 0.6, c1 - 0.5, c1))
    f = n - 1
    fh = entry - 0.5
    fc = fh - 2.0
    bars.append(mkbar(f, fc, fh, fc - 0.3, fc))
    return bars, entry


class SmcGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ai = load_ai_engine()
        cls.smc = cls.ai.SMC

    def test_gate_off_by_default(self):
        # Owner 2026-11-20: SMC dimatikan semula — terlalu ketat, signal
        # terlalu sedikit. Boleh hidupkan semula via AI_SMC_GATE=1.
        self.assertFalse(self.ai.SMC_GATE)

    def test_legacy_last_bar_call_cannot_fire(self):
        # Dokumentasi bug lama: detect(bars) pada bar terakhir = None.
        bars, _ = buy_bars()
        self.assertIsNone(self.smc.detect(self.smc.to_tuple_bars(bars)))

    def test_live_scan_finds_buy_setup(self):
        bars, entry = buy_bars()
        s = self.ai.smc_live_scan(bars)
        self.assertIsNotNone(s)
        self.assertEqual(s['side'], 'BUY')
        self.assertAlmostEqual(s['entry'], entry, places=5)
        self.assertEqual(s['fvg_bar'], len(bars) - 1)
        self.assertLess(s['sl'], s['entry'])

    def test_live_scan_finds_sell_setup(self):
        bars, entry = sell_bars()
        s = self.ai.smc_live_scan(bars)
        self.assertIsNotNone(s)
        self.assertEqual(s['side'], 'SELL')
        self.assertAlmostEqual(s['entry'], entry, places=5)
        self.assertGreater(s['sl'], s['entry'])

    def test_expired_ttl_rejected(self):
        bars, entry = buy_bars()
        # 8 bar neutral selepas FVG (low kekal atas entry) -> TTL luput.
        last = bars[-1][3]
        for j in range(8):
            k = len(bars)
            c = last + 0.5 + 0.1 * j
            bars.append(mkbar(k, c, c + 0.3, entry + 0.6, c))
        self.assertIsNone(self.ai.smc_live_scan(bars))

    def test_touched_entry_rejected(self):
        bars, entry = buy_bars()
        # Harga sudah turun menyentuh entry selepas FVG -> bukan virgin retest.
        k = len(bars)
        c = entry + 0.2
        bars.append(mkbar(k, c, c + 0.3, entry - 0.5, c))
        self.assertIsNone(self.ai.smc_live_scan(bars))

    def test_short_history_rejected(self):
        self.assertIsNone(self.ai.smc_live_scan(buy_bars(70)[0]))

    def test_rr_default_consistent_with_ticket(self):
        # Ticket sistem RR 1:2 (TP1 1R + TP2 2R); SMC ikut default sama.
        self.assertEqual(self.ai.SMC_R_MULT,
                         float(os.environ.get('AI_SMC_R', '2.0')))


class SmcLevelsTests(unittest.TestCase):
    """Polisi akaun kecil pada level struktur: lantai spread, skip bila lebar."""

    @classmethod
    def setUpClass(cls):
        cls.ai = load_ai_engine()

    def mk(self, entry, risk, side="BUY"):
        sl = entry - risk if side == "BUY" else entry + risk
        return {"side": side, "entry": entry, "sl": sl, "risk": risk,
                "bar_ts": 1, "fvg_bar": 2}

    def test_tight_structure_keeps_sl_and_rr(self):
        s = self.mk(4000.0, 3.5)  # risiko $3.5 < cap $5
        out, mode = self.ai.smc_levels("XAU/USD", "BUY", s)
        self.assertIsNotNone(out)
        self.assertEqual(out["sl"], s["sl"])  # SL struktur tidak diusik
        self.assertAlmostEqual(out["tp"], 4000.0 + self.ai.SMC_R_MULT * 3.5)
        self.assertEqual(mode, "struktur")

    def test_wide_structure_skipped_not_cut(self):
        s = self.mk(4000.0, 27.0)  # risiko $27 > cap $5 -> skip, bukan potong
        out, why = self.ai.smc_levels("XAU/USD", "BUY", s)
        self.assertIsNone(out)
        self.assertIn("cap", why)

    def test_thin_structure_widened_to_spread_floor(self):
        s = self.mk(4000.0, 0.5)  # bawah lantai 10x spread XAU = $3
        out, mode = self.ai.smc_levels("XAU/USD", "BUY", s)
        self.assertIsNotNone(out)
        self.assertAlmostEqual(out["risk"], 3.0, places=6)
        self.assertAlmostEqual(out["tp"], out["entry"] + self.ai.SMC_R_MULT * 3.0)
        self.assertTrue(mode.startswith("diluaskan"))

    def test_sell_mirror(self):
        s = self.mk(4000.0, 3.5, side="SELL")
        out, _ = self.ai.smc_levels("XAU/USD", "SELL", s)
        self.assertIsNotNone(out)
        self.assertEqual(out["sl"], s["sl"])
        self.assertAlmostEqual(out["tp"], 4000.0 - self.ai.SMC_R_MULT * 3.5)
        wide, _ = self.ai.smc_levels("XAU/USD", "SELL", self.mk(4000.0, 27.0, "SELL"))
        self.assertIsNone(wide)


class SmcDedupeTests(unittest.TestCase):
    def setUp(self):
        self.ai = load_ai_engine()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig = self.ai.SMC_POSTED_FILE
        self.ai.SMC_POSTED_FILE = Path(self.tmp.name) / 'posted.json'

    def tearDown(self):
        self.ai.SMC_POSTED_FILE = self._orig

    def test_mark_then_blocks_same_setup(self):
        s = {'bar_ts': 1234567890, 'fvg_bar': 109}
        self.assertFalse(self.ai.smc_already_posted('XAU/USD', s))
        self.ai.smc_mark_posted('XAU/USD', s)
        self.assertTrue(self.ai.smc_already_posted('XAU/USD', s))

    def test_different_setup_or_pair_not_blocked(self):
        s = {'bar_ts': 1234567890, 'fvg_bar': 109}
        self.ai.smc_mark_posted('XAU/USD', s)
        self.assertFalse(self.ai.smc_already_posted('XAU/USD',
                                                    dict(s, fvg_bar=110)))
        self.assertFalse(self.ai.smc_already_posted('XAG/USD', s))

    def test_corrupt_registry_fails_closed(self):
        self.ai.SMC_POSTED_FILE.write_text('{rosak')
        self.assertTrue(self.ai.smc_already_posted(
            'XAU/USD', {'bar_ts': 1, 'fvg_bar': 2}))


if __name__ == '__main__':
    unittest.main()