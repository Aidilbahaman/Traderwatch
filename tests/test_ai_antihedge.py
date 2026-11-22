#!/usr/bin/env python3
"""Regression: anti-hedging enjin AI — open_sides_by_pair memetakan arah
signal masih terbuka per pair, supaya signal baru tidak bertentangan arah
(layering searah dibenarkan, hedging tidak). Fail-open bila query gagal.
"""
import importlib.util
import json
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1] / 'engine'


def load_engine():
    spec = importlib.util.spec_from_file_location(
        'ai_antihedge', ENGINE / 'signal-engine-ai.py')
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class AntiHedgeTests(unittest.TestCase):
    def setUp(self):
        self.ai = load_engine()
        self._sb = self.ai.sb

    def tearDown(self):
        self.ai.sb = self._sb

    def test_open_sides_maps_open_signals(self):
        ts = "2026-11-20T05:00:00"
        rows = [
            {"pair": "XAU/USD", "side": "SELL", "posted_at": ts},
            {"pair": "XAG/USD", "side": "BUY", "posted_at": ts},
            {"pair": "BTCUSD", "side": "SELL", "posted_at": ts},
        ]
        state = {"signals": {
            self.ai.key_for("XAU/USD", ts): {"status": "active"},
            self.ai.key_for("XAG/USD", ts): {"status": "pending"},
            self.ai.key_for("BTCUSD", ts): {"status": "sl"},
        }}
        self.ai.sb = lambda *a, **k: (200, json.dumps(rows))
        out = self.ai.open_sides_by_pair(state)
        self.assertEqual(out.get("XAUUSD"), {"SELL"})
        self.assertEqual(out.get("XAGUSD"), {"BUY"})
        self.assertNotIn("BTCUSD", out)  # sudah closed: bukan posisi terbuka

    def test_same_direction_layering_allowed(self):
        # Dua signal SELL terbuka -> set {SELL}; signal SELL baru dibenarkan.
        ts = "2026-11-20T05:00:00"
        rows = [
            {"pair": "XAU/USD", "side": "SELL", "posted_at": ts},
            {"pair": "XAU/USD", "side": "SELL", "posted_at": "2026-11-20T05:30:00"},
        ]
        state = {"signals": {
            self.ai.key_for("XAU/USD", ts): {"status": "active"},
            self.ai.key_for("XAU/USD", "2026-11-20T05:30:00"): {"status": "active"},
        }}
        self.ai.sb = lambda *a, **k: (200, json.dumps(rows))
        out = self.ai.open_sides_by_pair(state)
        self.assertEqual(out.get("XAUUSD"), {"SELL"})
        held = out["XAUUSD"]
        self.assertTrue("SELL" in held)        # layering searah: lepas
        self.assertFalse("BUY" in held)        # hedging BUY: akan disekat

    def test_fail_open_on_query_error(self):
        self.ai.sb = lambda *a, **k: (500, "err")
        self.assertEqual(self.ai.open_sides_by_pair({}), {})


if __name__ == '__main__':
    unittest.main()