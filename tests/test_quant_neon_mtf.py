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
        for tf in ("M5", "M15", "H1", "H4", "D1"):
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
        for tf in ("M5", "M15", "H1", "H4", "D1"):
            ra = self.qe.scan_index(ind_full, idx2, tf, 0.1, 3.0)
            rb = self.qe.scan_index(ind_mut, idx2, tf, 0.1, 3.0)
            self.assertEqual(ra, rb, f"Look-ahead leak detected on {tf}!")
        # 2) Strict prefix truncation (n < 100 and n < 200) must produce identical
        #    EMA100/EMA200 and scan_index outputs (regression: n-dependent EMA clamping).
        for idx_short in (65, 120, 215):
            ind_pref = self.qe.compute_series(bars2[:idx_short + 1])
            self.assertAlmostEqual(ind_pref["e100"][idx_short], ind_full["e100"][idx_short], places=9)
            self.assertAlmostEqual(ind_pref["e200"][idx_short], ind_full["e200"][idx_short], places=9)
            for tf in ("M5", "M15", "H1", "H4", "D1"):
                r_pref = self.qe.scan_index(ind_pref, idx_short, tf, 0.1, 3.0)
                r_full = self.qe.scan_index(ind_full, idx_short, tf, 0.1, 3.0)
                self.assertEqual(r_pref, r_full, f"Prefix-truncation leak on {tf} @ {idx_short}!")

    def test_all_5_timeframes_rr_bounds_consistent(self):
        for tf in ("M5", "M15", "H1", "H4", "D1"):
            cfg = self.qe.TF_CONFIG[tf]
            prof = self.la.tf_profile(tf)
            self.assertLess(prof["rr1_min"], cfg["rr1"], f"{tf} rr1_min >= quant rr1")
            self.assertLess(cfg["rr1"], prof["rr1_max"], f"{tf} quant rr1 >= rr1_max")
            self.assertEqual(cfg["min_bars"], prof["min_bars"], f"{tf} min_bars mismatch")

    def test_pullback_and_breakout_generate_valid_levels(self):
        # M5 tiada STREAK_TREND/INSIDE_BAR (rujuk quant_engine scan_index) dan
        # tidak menapis RSI2_FLUSH, jadi ia guna fixture pullback berasingan.
        # M15 menapis RSI2_FLUSH/STOCH_TURN, jadi ia perlukan fixture yang
        # mencetuskan STREAK_TREND tanpa RSI2_FLUSH — iaitu drift turun
        # berperingkat (rsi2 kekal tinggi, rsi5 rendah).
        cases = [
            ("M5", make_uptrend_with_flush(460)),
            ("M15", make_drift_down_hold(460)),
            ("H4", make_uptrend_with_flush(460)),
        ]
        for tf, bars in cases:
            q = self.qe.scan(bars, "XAU/USD", tf, 0.1, 3.0)
            self.assertEqual(q["side"], "BUY", f"Expected BUY on {tf}, got {q}")
            self.assertLess(q["sl"], q["entry"])
            self.assertLess(q["entry"], q["tp1"])
            self.assertLess(q["tp1"], q["tp2"])
            prof = self.la.tf_profile(tf)
            v = self.la.validate_verdict(
                {"bias": q["side"], "sl": q["sl"], "tp1": q["tp1"], "tp2": q["tp2"],
                 "confidence": 7, "reason": "ok"},
                q["entry"], 0.1, 3.0, rr1_min=prof["rr1_min"], rr1_max=prof["rr1_max"],
            )
            self.assertEqual(v["side"], "BUY")

        bo_bars = make_breakout_bars(420)
        for tf in ("H1", "D1"):
            q = self.qe.scan(bo_bars, "XAU/USD", tf, 0.1, 3.0)
            self.assertEqual(q["side"], "BUY", f"Expected BUY breakout on {tf}, got {q}")
            prof = self.la.tf_profile(tf)
            v = self.la.validate_verdict(
                {"bias": q["side"], "sl": q["sl"], "tp1": q["tp1"], "tp2": q["tp2"],
                 "confidence": 7, "reason": "breakout"},
                q["entry"], 0.1, 3.0, rr1_min=prof["rr1_min"], rr1_max=prof["rr1_max"],
            )
            self.assertEqual(v["side"], "BUY")


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

    def test_d1_and_h4_rr1_bounds_not_contradictory(self):
        for tf in ("H4", "D1"):
            prof = self.la.tf_profile(tf)
            # 1.9R is valid on H4 (max 2.0) and D1 (max 2.2) — previously impossible on D1!
            out = self.la.validate_verdict(
                {"bias": "BUY", "sl": 3900.0, "tp1": 4090.0, "tp2": 4180.0, "confidence": 8},
                4000.0, 0.1, 3.0, rr1_min=prof["rr1_min"], rr1_max=prof["rr1_max"],
            )
            self.assertEqual(out["side"], "BUY")
            self.assertAlmostEqual(out["rr1"], 0.9, places=2)
            out_hi = self.la.validate_verdict(
                {"bias": "BUY", "sl": 3900.0, "tp1": 4190.0, "tp2": 4300.0, "confidence": 8},
                4000.0, 0.1, 3.0, rr1_min=prof["rr1_min"], rr1_max=prof["rr1_max"],
            )
            self.assertAlmostEqual(out_hi["rr1"], 1.9, places=2)

    def test_vision_chart_render_with_levels(self):
        bars = make_uptrend_with_flush(460)
        q = self.qe.scan(bars, "XAU/USD", "M15", 0.1, 3.0)
        b64 = self.vc.render(bars, pair="XAU/USD", tf="M15", bos="UP", choch=False, levels=q)
        raw = base64.b64decode(b64)
        self.assertTrue(raw.startswith(b"\x89PNG"))
        self.assertEqual(self.vc.render([]), "")

    def test_quant_gate_skips_vision_when_no_setup(self):
        # Steady drift with no pullback/breakout trigger on M5
        # 460 bar: lepas warmup (400) supaya yang menolak benar-benar ketiadaan setup.
        bars = [(i * 300000, 2000.0 + i * 0.2 + 0.5, 2000.0 + i * 0.2 - 0.5, 2000.0 + i * 0.2)
                for i in range(460)]
        with mock.patch.object(self.la, "_call_vision") as m_vis, \
             mock.patch.object(self.la, "MC", None):
            out = self.la.analyze("XAU/USD", bars, 0.1, 3.0, tf="M5")
            self.assertIsNotNone(out)
            self.assertEqual(out["side"], "HOLD")
            self.assertEqual(out["tf"], "M5")
            m_vis.assert_not_called()

    def test_quant_plus_vision_approval_veto_conflict_and_antihedge(self):
        bars = make_drift_down_hold(460)
        q = self.qe.scan(bars, "XAU/USD", "M15", 0.1, 3.0)
        self.assertEqual(q["side"], "BUY")

        # 1. Vision approves quant BUY
        reply_ok = json.dumps({
            "bias": "BUY", "sl": q["sl"], "tp1": q["tp1"], "tp2": q["tp2"],
            "confidence": 8, "reason": "clean pullback above EMA50",
        })
        with mock.patch.object(self.la, "_call_vision", return_value=reply_ok) as m_vis, \
             mock.patch.object(self.la, "MC", None):
            out = self.la.analyze("XAU/USD", bars, 0.1, 3.0, tf="M15")
            self.assertEqual(out["side"], "BUY")
            self.assertEqual(out["tf"], "M15")
            self.assertTrue(out["vision"])
            self.assertEqual(out["ai_meta"]["quant"]["side"], "BUY")
            self.assertEqual(m_vis.call_count, 1)

        # 2. Vision vetoes with HOLD
        reply_hold = json.dumps({"bias": "HOLD", "confidence": 4, "reason": "double top ahead"})
        with mock.patch.object(self.la, "_call_vision", return_value=reply_hold), \
             mock.patch.object(self.la, "MC", None):
            out = self.la.analyze("XAU/USD", bars, 0.1, 3.0, tf="M15")
            self.assertEqual(out["side"], "HOLD")

        # 3. Vision tries to flip opposite direction -> fail-safe HOLD
        reply_flip = json.dumps({
            "bias": "SELL", "sl": q["entry"] + 10, "tp1": q["entry"] - 10, "tp2": q["entry"] - 20,
            "confidence": 7, "reason": "flip",
        })
        with mock.patch.object(self.la, "_call_vision", return_value=reply_flip), \
             mock.patch.object(self.la, "MC", None):
            out = self.la.analyze("XAU/USD", bars, 0.1, 3.0, tf="M15")
            self.assertEqual(out["side"], "HOLD")
            self.assertIn("conflict", out["reason"].lower())

        # 4. Anti-hedge blocks quant BUY when SELL already open (without calling LLM)
        with mock.patch.object(self.la, "_call_vision") as m_vis, \
             mock.patch.object(self.la, "MC", None):
            out = self.la.analyze("XAU/USD", bars, 0.1, 3.0, tf="M15", held={"SELL"})
            self.assertEqual(out["side"], "HOLD")
            self.assertIn("Anti-hedge", out["reason"])
            m_vis.assert_not_called()

    def test_vision_fallback_prefers_neon_medium_and_text_fallback_has_ohlc(self):
        bars = make_drift_down_hold(460)
        q = self.qe.scan(bars, "XAU/USD", "M15", 0.1, 3.0)
        self.assertEqual(q["side"], "BUY")

        # 1. When gemini-4-neon-high times out, vision falls back to gemini-4-neon-medium first
        seen_v = []
        reply_ok = json.dumps({
            "bias": "BUY", "sl": q["sl"], "tp1": q["tp1"], "tp2": q["tp2"],
            "confidence": 8, "reason": "confirmed on neon medium",
        })
        def fake_vis(model, prompt, *_a, **_kw):
            seen_v.append(model)
            if model == "gemini-4-neon-high":
                raise RuntimeError("agy gagal: print timeout after 1m0s")
            return reply_ok

        with mock.patch.object(self.la, "_call_vision", side_effect=fake_vis), \
             mock.patch.object(self.la, "MC", None):
            out = self.la.analyze("XAU/USD", bars, 0.1, 3.0, tf="M15")
            self.assertEqual(seen_v, ["gemini-4-neon-high", "gemini-4-neon-medium"])
            self.assertEqual(out["side"], "BUY")
            self.assertEqual(out["model"], "gemini-4-neon-medium")
            self.assertTrue(out["vision"])

        # 2. When ALL vision models fail, text fallback receives OHLC text prompt (NOT image prompt)
        #    and attaches vision=False + ai_meta.
        captured_prompts = []
        def fake_text(model, prompt, timeout):
            captured_prompts.append((model, prompt))
            return reply_ok

        with mock.patch.object(self.la, "_call_vision", side_effect=RuntimeError("vision down")), \
             mock.patch.object(self.la, "_call_model", side_effect=fake_text), \
             mock.patch.object(self.la, "MC", None):
            out = self.la.analyze("XAU/USD", bars, 0.1, 3.0, tf="M15")
            self.assertEqual(out["side"], "BUY")
            self.assertFalse(out["vision"])
            self.assertIsNotNone(out.get("ai_meta"))
            self.assertEqual(out["ai_meta"]["quant"]["side"], "BUY")
            self.assertTrue(captured_prompts)
            _, sent_prompt = captured_prompts[0]
            self.assertIn("O H L C", sent_prompt)
            self.assertIn("QUANT CANDIDATE", sent_prompt)
            self.assertNotIn("Inspect the chart image", sent_prompt)

    def test_validate_verdict_handles_nan_and_inf(self):
        # NaN confidence should fall back to 0.5 rather than propagating NaN
        out = self.la.validate_verdict(
            {"bias": "HOLD", "confidence": "nan", "reason": "unclear"},
            3600.0, 0.1, 3.0,
        )
        self.assertEqual(out["side"], "HOLD")
        self.assertEqual(out["conf"], 0.5)
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

    def test_analyze_api_fetch_ohlc_uses_native_h4_d1(self):
        api = _load("analyze-api")
        fake_d1 = [
            {"t": f"2026-01-{(i % 28) + 1:02d}T00:00:00+00:00",
             "o": 100.0 + i, "h": 102.0 + i, "l": 99.0 + i, "c": 101.0 + i}
            for i in range(180)
        ]
        calls = []
        def fake_candles(pair, gran, count):
            calls.append((pair, gran, count))
            return fake_d1 if gran == "D1" else []
        with mock.patch.object(api.M5, "candles", side_effect=fake_candles):
            rows = api._fetch_ohlc_raw("BTCUSD", "D1", limit=150)
            self.assertEqual(len(rows), 150)
            self.assertEqual(calls[0][1], "D1")


if __name__ == "__main__":
    unittest.main()
