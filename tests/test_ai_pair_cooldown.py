#!/usr/bin/env python3
"""Regression: cooldown per pair enjin AI (tanpa gate SMC).

Tanpa SMC, model boleh fire setiap tick (5 min) bila conf kekal atas gate.
Cooldown AI_PAIR_COOLDOWN_MIN (default 30) hadkan spam per pair; 0 = lumpuh.
"""
import importlib.util
import json
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENGINE = ROOT / 'engine'


def load_ai_engine():
    spec = importlib.util.spec_from_file_location(
        'ai_engine_cooldown', ENGINE / 'signal-engine-ai.py')
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class PairCooldownTests(unittest.TestCase):
    def setUp(self):
        self.ai = load_ai_engine()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._orig_file = self.ai.COOLDOWN_FILE
        self._orig_min = self.ai.PAIR_COOLDOWN_MIN
        self.ai.COOLDOWN_FILE = Path(self.tmp.name) / 'cooldown.json'
        self.ai.PAIR_COOLDOWN_MIN = 30.0

    def tearDown(self):
        self.ai.COOLDOWN_FILE = self._orig_file
        self.ai.PAIR_COOLDOWN_MIN = self._orig_min

    def test_fresh_pair_not_on_cooldown(self):
        self.assertFalse(self.ai.pair_on_cooldown('XAU/USD'))

    def test_mark_then_blocks(self):
        self.ai.mark_pair_fired('XAU/USD')
        self.assertTrue(self.ai.pair_on_cooldown('XAU/USD'))
        self.assertFalse(self.ai.pair_on_cooldown('XAG/USD'))

    def test_expires_after_window(self):
        self.ai.COOLDOWN_FILE.write_text(json.dumps({'XAU/USD': time.time() - 31 * 60}))
        self.assertFalse(self.ai.pair_on_cooldown('XAU/USD'))

    def test_zero_disables(self):
        self.ai.PAIR_COOLDOWN_MIN = 0.0
        self.ai.mark_pair_fired('XAU/USD')
        self.assertFalse(self.ai.pair_on_cooldown('XAU/USD'))

    def test_corrupt_file_fails_open(self):
        self.ai.COOLDOWN_FILE.write_text('{rosak')
        self.assertFalse(self.ai.pair_on_cooldown('XAU/USD'))


if __name__ == '__main__':
    unittest.main()