#!/usr/bin/env python3
"""Build a local, authenticated-like members.html QA harness.

This copies the real members.html and replaces only the external auth/config
scripts with safe in-page stubs. The real page markup, CSS, inline dashboard
logic, members-tools.js and members-tools-2.js remain in use.

Usage:
  python3 scripts/build-members-harness.py
  python3 scripts/build-members-harness.py --output /tmp/tw-members-qc.html

Serve the repo, then open the printed URL with browser_exec:
  python3 -m http.server 8922
  http://127.0.0.1:8922/_members-mobile-qc.html

The harness must never be published or committed. It uses a fake QA member and
empty read-only signal responses; it does not write to Supabase.
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "_members-mobile-qc.html"

SUPABASE_STUB = '''<script>
window.supabase = {};
</script>'''

CONFIG_STUB = '''<script>
window.sb = {
  rpc: async () => ({ data: [], error: null }),
  from: () => ({
    select: () => ({
      eq: () => ({
        single: async () => ({ data: { telegram_chat_id: null }, error: null })
      })
    })
  })
};
window.CONFIG = {
  pairs: [
    {label: "EUR/USD", symbol: "FX:EURUSD"},
    {label: "GBP/USD", symbol: "FX:GBPUSD"},
    {label: "USD/JPY", symbol: "FX:USDJPY"},
    {label: "XAU/USD", symbol: "OANDA:XAUUSD"},
    {label: "AUD/USD", symbol: "FX:AUDUSD"},
    {label: "USD/CAD", symbol: "FX:USDCAD"}
  ]
};
</script>'''

COMMON_STUB = '''<script>
window.requireMember = async () => ({
  id: "qa-harness-user",
  email: "qa-harness@example.invalid",
  name: "Aidil Bahaman",
  plan: "max",
  telegram_chat_id: null
});
window.previewBanner = () => {};
window.logOut = () => {};
</script>'''


def build(source: Path, output: Path) -> None:
    html = source.read_text(encoding="utf-8")
    replacements = {
        '<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.45.4/dist/umd/supabase.min.js"></script>': SUPABASE_STUB,
        '<script src="config.js?v=202610182133"></script>': CONFIG_STUB,
        '<script src="common.js?v=202610182133"></script>': COMMON_STUB,
    }
    missing = [needle for needle in replacements if needle not in html]
    if missing:
        raise SystemExit("members.html changed; expected script tag(s) missing: " + ", ".join(missing))
    for needle, replacement in replacements.items():
        html = html.replace(needle, replacement, 1)

    # Make accidental publication obvious in the browser tab.
    html = html.replace("<title>Your dashboard – TraderWatch</title>",
                        "<title>QA harness – TraderWatch members</title>", 1)
    output.write_text(html, encoding="utf-8")
    output.chmod(0o600)
    print(f"wrote: {output}")
    print("fake member: Aidil Bahaman / Max")
    print("Supabase writes: disabled")
    print("DO NOT COMMIT OR PUBLISH THIS FILE")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "members.html")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if not args.source.exists():
        raise SystemExit(f"source not found: {args.source}")
    build(args.source, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
