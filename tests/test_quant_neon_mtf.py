#!/usr/bin/env python3
"""Unit & regression tests for multi-TF quant_engine + Gemini 4 Neon vision integration."""
import base64
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / "engine"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, ENGINE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_uptrend_with_flush(n=460, base=2000.0, step=1.5):
    """Deterministic uptrend ending in a sharp pullback.

    n defaults to 460: quant_engine.WARMUP_BARS requires ~400 M15 bars before
    EMA200 is trustworthy, and scan() fails closed below that.
    """
    bars = []
    p = base
    for i in range(n - 4):
        p += step
        bars.append((i * 900000, p + 1.8, p - 1.2, p))
    # Sharp 4-bar pullback inside uptrend above EMA200 (keeps EMA20 > EMA50 and EMA50 rising)
    for k, drop in enumerate((2.0, 2.5, 3.0, 3.5)):
        p -= drop
        bars.append(((n - 4 + k) * 900000, p + 1.0, p - 1.5, p))
    return bars


def make_breakout_bars(n=420, base=2000.0):
    """Build realistic uptrend + 20-bar consolidation ending with a clean Donchian breakout (RSI14 ~60-72)."""
    bars = []
    p = base
    for i in range(n - 20):
        # Realistic uptrend with pullbacks so RSI14 stays moderate
        delta = 3.0 if (i % 3 != 0) else -2.5
        p += delta
        bars.append((i * 3600000, p + 2.0, p - 2.0, p))
    # 19-bar sideways consolidation near top of uptrend
    base_top = p
    for k in range(19):
        p = base_top + (2.0 if k % 2 == 0 else -2.5)
        bars.append(((n - 20 + k) * 3600000, p + 2.0, p - 2.0, p))
    # Clean breakout bar above 20-bar high
    p = base_top + 7.5
    bars.append(((n - 1) * 3600000, p + 2.0, p - 1.5, p))
    return bars


def make_drift_down_hold(n=460, base=2000.0, step=1.5, ndn=4, dstep=1.2):
    """Uptrend then four small stair-step down bars.

    Triggers STREAK_TREND on M15 without tripping the weak-tag filter
    (RSI2_FLUSH / STOCH_TURN): dn_st reaches 3 while RSI2 stays moderate.
    Verified: returns tags ['STREAK_TREND'] on M15 at ndn=4, dstep=1.2.
    """
    bars = []
    p = base
    for i in range(n - ndn):
        p += step
        bars.append((i * 900000, p + 1.8, p - 1.2, p))
    for k in range(ndn):
        p -= dstep
        bars.append(((n - ndn + k) * 900000, p + 0.8, p - 1.0, p))
    return bars


class QuantEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qe = _load("quant_engine")
        cls.la = _load("llm_analyst")

    def test_empty_and_short_bars_hold(self):
        for tf in ("M1", "M5", "M15", "H1"):
            r0 = self.qe.scan([], "XAU/USD", tf, 0.1, 3.0)
            self.assertIsNone(r0["side"])
            short = [(i * 60000, 101.0, 99.0, 100.0) for i in range(10)]
            r1 = self.qe.scan(short, "XAU/USD", tf, 0.1, 3.0)
            self.assertIsNone(r1["side"])

    def test_flat_low_atr_filtered_out(self):
        # Zero volatility bars -> ATR=0 -> skipped
        # 420 bar: cukup untuk lepas warmup, jadi yang menolak benar-benar ATR=0.
        flat = [(i * 900000, 1.1000, 1.1000, 1.1000) for i in range(420)]
        r = self.qe.scan(flat, "EUR/USD", "M15", 0.0001, 1.0)
        self.assertIsNone(r["side"])
        self.assertIn("Low volatility", r["hold_reason"])

    def test_strictly_causal_zero_lookahead(self):
        bars2 = make_uptrend_with_flush(460)
        ind_full = self.qe.compute_series(bars2)
        # 1) Mutating future bars (same length) must not change bar `idx2`
        idx2 = 215
        bars2_mut = list(bars2[:idx2 + 1]) + [
            ((idx2 + 1 + k) * 900000, 9999.0, 1.0, 5000.0) for k in range(len(bars2) - idx2 - 1)
        ]
        ind_mut = self.qe.compute_series(bars2_mut)
        for tf in ("M1", "M5", "M15", "H1"):
            ra = self.qe.scan_index(ind_full, idx2, tf, 0.1, 3.0)
            rb = self.qe.scan_index(ind_mut, idx2, tf, 0.1, 3.0)
            self.assertEqual(ra, rb, f"Look-ahead leak detected on {tf}!")
        # 2) Strict prefix truncation (n < 100 and n < 200) must produce identical
        #    EMA100/EMA200 and scan_index outputs (regression: n-dependent EMA clamping).
        for idx_short in (65, 120, 215):
            ind_pref = self.qe.compute_series(bars2[:idx_short + 1])
            self.assertAlmostEqual(ind_pref["e100"][idx_short], ind_full["e100"][idx_short], places=9)
            self.assertAlmostEqual(ind_pref["e200"][idx_short], ind_full["e200"][idx_short], places=9)
            for tf in ("M1", "M5", "M15", "H1"):
                r_pref = self.qe.scan_index(ind_pref, idx_short, tf, 0.1, 3.0)
                r_full = self.qe.scan_index(ind_full, idx_short, tf, 0.1, 3.0)
                self.assertEqual(r_pref, r_full, f"Prefix-truncation leak on {tf} @ {idx_short}!")

class ValidationAndVisionIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.la = _load("llm_analyst")
        self.qe = _load("quant_engine")
        self.vc = _load("vision_chart")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_audit = self.la.AUDIT_FILE
        self.la.AUDIT_FILE = Path(self.tmp.name) / "audit.jsonl"

    def tearDown(self):
        self.la.AUDIT_FILE = self._orig_audit

    def test_rr1_float_rounding_tolerance(self):
        # Previously rejected as "RR1 1.00 below 1.0" when rr1 = 0.9985
        price = 4100.0
        sl = 4090.0
        tp1 = 4109.985  # rr1 = 0.9985
        tp2 = 4115.0
        out = self.la.validate_verdict(
            {"bias": "BUY", "sl": sl, "tp1": tp1, "tp2": tp2, "confidence": 7},
            price, 0.1, 3.0, rr1_min=1.0, rr1_max=1.6,
        )
        self.assertEqual(out["side"], "BUY")
        self.assertAlmostEqual(out["rr1"], 1.0, places=2)
        # Truly below rr1_min must still fail
        with self.assertRaises(ValueError):
            self.la.validate_verdict(
                {"bias": "BUY", "sl": sl, "tp1": 4109.5, "tp2": tp2, "confidence": 7},
                price, 0.1, 3.0, rr1_min=1.0, rr1_max=1.6,
            )

    def test_vision_chart_render_with_levels(self):
        bars = make_uptrend_with_flush(460)
        q = self.qe.scan(bars, "XAU/USD", "M15", 0.1, 3.0)
        b64 = self.vc.render(bars, pair="XAU/USD", tf="M15", bos="UP", choch=False, levels=q)
        raw = base64.b64decode(b64)
        self.assertTrue(raw.startswith(b"\x89PNG"))
        self.assertEqual(self.vc.render([]), "")

    def test_validate_verdict_handles_nan_and_inf(self):
        # NaN confidence must not propagate; HOLD is capped at 0.35 by design
        out = self.la.validate_verdict(
            {"bias": "HOLD", "confidence": "nan", "reason": "unclear"},
            3600.0, 0.1, 3.0,
        )
        self.assertEqual(out["side"], "HOLD")
        self.assertTrue(0.0 < out["conf"] <= 0.35, f"HOLD conf out of range: {out['conf']}")
        # Inf SL/TP must be rejected
        with self.assertRaises(ValueError):
            self.la.validate_verdict(
                {"bias": "BUY", "sl": 3590.0, "tp1": float("inf"), "tp2": float("inf"), "confidence": 7},
                3600.0, 0.1, 3.0, rr1_min=0.75, rr1_max=1.6,
            )

    def test_vision_chart_xag_silver_consistent_decimals(self):
        # XAGUSD below and above $50 should render cleanly without error
        bars_41 = [(i * 900000, 41.25, 41.10, 41.18) for i in range(60)]
        b64 = self.vc.render(bars_41, pair="XAG/USD", tf="M15", bos="UP",
                             levels={"side": "BUY", "entry": 41.18, "sl": 40.90, "tp1": 41.40, "tp2": 41.62})
        self.assertTrue(base64.b64decode(b64).startswith(b"\x89PNG"))

if __name__ == "__main__":
    unittest.main()
