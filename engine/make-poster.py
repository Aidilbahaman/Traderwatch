#!/usr/bin/env python3
"""Render a distinct TraderWatch promo poster for every marketing angle.

Uses the repo-local CSS/fonts in assets/marketing so renders are reproducible.
Renders via headless Chrome, checks DOM overflow, then writes poster-N.png.
Run: python3 engine/make-poster.py <n>   (n = 1..12, matching channel-update.PROMOS)
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MKT = ROOT / "assets/marketing"
TMP = Path("/tmp/tw-poster-gen")
TMP.mkdir(exist_ok=True)

BRAND = "#b7f36b"
INK = "#eef3ee"
MUTED = "#8a978c"


# n: (badge, headline1, headline2, lead, accent, art-kind, footer-note)
P = {
  1: ("AUTOMATED AI SIGNALS", "Signals,", "annotated.",
      "XAU/USD, XAG/USD & BTC — Entry, SL and TP drawn right on the chart, with the reason behind every signal.",
      BRAND, "chart", "Real signal record"),
  2: ("INSTALLABLE APP", "On your", "home screen.",
      "One tap to open, just like any app — no app store needed. Annotated AI signals for Gold, Silver & Bitcoin.",
      BRAND, "phone", "Install from your browser"),
  3: ("3 MARKETS · ONE APP", "CHOOSE YOUR", "EDGE.",
      "Trade Gold, Silver and Bitcoin with annotated AI signals — one app, one clear view.",
      BRAND, "bars", "XAU/USD · XAG/USD · BTC"),
  4: ("FREE FOR EVERYONE", "FULL ACCESS.", "NO PAYWALL.",
      "One tier for everyone. Create a free account and read annotated signals today.",
      "#ffc16b", "tier", "No subscription, ever"),
  5: ("WORKS OFFLINE", "NO SIGNAL.", "NO INTERNET.",
      "Bar data is cached, so your charts render even without a connection. Read the market anywhere.",
      "#8ab4ff", "offline", "Cached bar data"),
  6: ("TRANSPARENT RESULTS", "RESULTS,", "NOT CLAIMS.",
      "Every signal is recorded and its outcome published — wins and losses, transparently.",
      "#ff817d", "ledger", "Available in the app"),
  7: ("RISK FIRST", "PROTECT", "YOUR CAPITAL.",
      "Every signal defines its Stop Loss before its target. Trade the plan, not the emotion.",
      "#8ab4ff", "shield", "SL before TP"),
  8: ("EDUCATION BUILT IN", "LEARN AS", "YOU TRADE.",
      "Short, plain-English lessons on markets, charts and risk — sized for a coffee break.",
      BRAND, "book", "For members"),
  9: ("READ THE MARKET", "CLEARLY.", "CONFIDENTLY.",
      "Annotated AI signals, Entry/SL/TP and the reason — right on your home screen.",
      BRAND, "eye", "Free to join"),
 10: ("GLOBAL COMMUNITY", "JOIN THE", "TRADERS.",
      "A free, installable app for annotated AI signals on Gold, Silver and Bitcoin. Read the market with us.",
      BRAND, "globe", "traderwatch.org"),
 11: ("GET STARTED", "READY IN", "A MINUTE.",
      "Create a free account, install to your home screen, and see annotated signals today.",
      BRAND, "bolt", "No subscription, ever"),
 12: ("SIGNALS + REASON", "KNOW THE", "WHY.",
      "Each signal comes with an entry reason and a confluence checklist — not just an alert.",
      BRAND, "checklist", "Understand before you decide"),
}


def art(kind, accent):
    if kind == "chart":
        candles = "".join(
            f'<div class="c" style="left:{40+i*74}px;top:{30+((i*37)%120)}px;height:{90+(i%3)*30}px;background:{"#ff817d" if i%4 else accent}"></div>'
            for i in range(11))
        return f'<div class="art chart"><div class="plot">{candles}<div class="trend"></div><div class="entryline"></div></div></div>'
    if kind == "phone":
        rows = "".join(
            f'<div class="prow"><span>{p}</span><b>{v}</b></div>'
            for p, v in [("XAU/USD", "SELL 3554.01"), ("XAG/USD", "BUY 41.19"), ("BTC/USD", "BUY 60,350")])
        return f'<div class="art phone"><div class="phone2"><div class="pn">T &nbsp; TRADERWATCH</div>{rows}<div class="pcta">Read the market. Clearly.</div></div></div>'
    if kind == "bars":
        b = "".join(f'<div class="bar" style="height:{70+i*32}px;background:{accent};opacity:{.35+i*.09}"></div>' for i in range(7))
        return f'<div class="art bars"><div class="bars-row">{b}</div><div class="bars-label">XAU/USD &nbsp;·&nbsp; XAG/USD &nbsp;·&nbsp; BTC</div></div>'
    if kind == "tier":
        return '<div class="art tier"><div class="tier-card"><small>ONE TIER</small><strong>FREE</strong><span>full access · no subscription</span></div></div>'
    if kind == "offline":
        return '<div class="art offline"><div class="wifi">⌁</div><div class="offline-txt">CHARTS RENDER WITHOUT INTERNET</div></div>'
    if kind == "ledger":
        rows = "".join(f'<div class="lrow"><i class="circle" style="background:{BRAND if i%3 else "#ff817d"}"></i><span style="width:{180+i*30}px"></span></div>' for i in range(4))
        return f'<div class="art ledger">{rows}</div>'
    if kind == "shield":
        return '<div class="art shield"><div class="shield-shape">✓</div><div class="shield-note">SL defined before TP</div></div>'
    if kind == "book":
        return '<div class="art book"><div class="bcard">01</div><div class="bcard hi">02</div><div class="bcard">03</div></div>'
    if kind == "eye":
        return '<div class="art eye"><div class="eye-shape"><div class="pupil"></div></div></div>'
    if kind == "globe":
        return '<div class="art globe"><div class="globe-shape">◎</div></div>'
    if kind == "bolt":
        return '<div class="art bolt"><div class="bolt-shape">⚡</div></div>'
    if kind == "checklist":
        rows = "".join(f'<div class="clrow"><span>✓</span><i style="width:{240-i*20}px"></i></div>' for i in range(4))
        return f'<div class="art checklist">{rows}</div>'
    return ""


CSS_EXTRA = """
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:1080px;height:1350px;background:#050805}
body{font-family:'Inter',Arial,sans-serif;color:#eef3ee;position:relative;overflow:hidden;
 background:radial-gradient(820px 520px at 85% -6%,var(--accent-a),transparent 60%),
 #050805}
.page{position:relative;width:1080px;height:1350px;padding:62px 68px 50px;display:flex;flex-direction:column}
.top{display:flex;align-items:center;justify-content:space-between}
.brand{display:flex;align-items:center;gap:18px}.brand img{width:60px;height:60px}
.bn{font-size:25px;font-weight:800;letter-spacing:.06em}.bn span{color:#b7f36b}
.badge{border:1px solid var(--accent);border-radius:999px;padding:10px 20px;font-size:14px;font-weight:800;
 letter-spacing:.14em;color:var(--accent);background:var(--accent-a)}
.hero{margin-top:56px}
.eyebrow{color:var(--accent);font-size:17px;font-weight:800;letter-spacing:.18em}
h1{font-size:100px;line-height:1.0;letter-spacing:-.055em;font-weight:900;margin-top:18px}
h1 .ac{color:var(--accent)}
.lead{font-size:25px;line-height:1.45;color:#c3cec3;margin-top:22px;max-width:850px}
.art{position:relative;height:430px;margin-top:36px;display:flex;align-items:center;justify-content:center}
.art.chart .plot{position:relative;width:880px;height:340px;border:1px solid #26332a;border-radius:18px;background:#0d120e;overflow:hidden}
.art.chart .c{position:absolute;width:26px;border-radius:4px}
.art.chart .trend{position:absolute;left:60px;right:60px;top:190px;height:4px;background:var(--accent);opacity:.7;transform:rotate(-8deg)}
.art.chart .entryline{position:absolute;left:520px;top:0;bottom:0;width:2px;background:#eef3ee;opacity:.6}
.phone2{width:300px;background:#121813;border:2px solid #2f3d30;border-radius:34px;padding:24px 20px;box-shadow:0 24px 60px rgba(0,0,0,.5)}
.pn{font-size:13px;font-weight:800;letter-spacing:.1em;margin-bottom:18px;color:var(--accent)}
.prow{display:flex;justify-content:space-between;padding:12px 0;border-bottom:1px solid #26332a;font-size:14px;color:#8a978c}
.prow b{color:#eef3ee;font-family:'JetBrains Mono',monospace}
.pcta{margin-top:18px;background:var(--accent);color:#10170b;text-align:center;padding:10px;border-radius:9px;font-size:13px;font-weight:900}
.bars-row{display:flex;align-items:flex-end;gap:26px;height:280px}
.bar{width:70px;border-radius:10px 10px 0 0}
.bars-label{position:absolute;bottom:40px;color:#8a978c;font-size:18px;letter-spacing:.1em}
.tier-card{width:420px;background:#121813;border:2px solid var(--accent);border-radius:24px;padding:40px;text-align:center}
.tier-card small{color:var(--accent);font-size:18px;font-weight:800;letter-spacing:.12em}
.tier-card strong{display:block;font-size:96px;letter-spacing:-.05em;margin:10px 0}
.tier-card span{color:#8a978c;font-size:17px}
.wifi{font-size:180px;color:var(--accent);line-height:1}
.offline-txt{position:absolute;bottom:40px;color:#8a978c;font-size:20px;letter-spacing:.12em}
.lrow{display:flex;align-items:center;gap:18px;margin-bottom:12px}
.lrow i{height:14px;border-radius:7px;background:#3a4a3b;display:block}
.lrow i.circle{width:18px;height:18px;border-radius:50%}
.shield-shape{width:230px;height:260px;background:#121813;border:3px solid var(--accent);border-radius:110px 110px 24px 24px;display:grid;place-items:center;font-size:110px;color:var(--accent)}
.shield-note{position:absolute;bottom:40px;color:#8a978c;font-size:20px;letter-spacing:.12em}
.book{display:flex;gap:24px}.bcard{width:190px;height:250px;background:#121813;border:1px solid #26332a;border-radius:18px;display:grid;place-items:center;font-size:64px;font-weight:900;color:#8a978c}
.bcard.hi{border:2px solid var(--accent);color:var(--accent)}
.eye-shape{width:520px;height:260px;border:3px solid var(--accent);border-radius:260px;display:grid;place-items:center;background:#121813}
.pupil{width:110px;height:110px;border-radius:50%;background:var(--accent)}
.globe-shape,.bolt-shape{font-size:230px;color:var(--accent);line-height:1}
.clrow{display:flex;align-items:center;gap:18px;margin-bottom:20px}.clrow span{color:var(--accent);font-size:30px;font-weight:900}.clrow i{height:14px;border-radius:7px;background:#3a4a3b}
.footer{margin-top:auto;padding-top:24px;border-top:1px solid #26332a}
.cta-row{display:flex;align-items:center;justify-content:space-between}
.cta-main{font-size:42px;font-weight:900;letter-spacing:-.04em}.cta-main span{color:var(--accent)}
.cta-sub{font-size:15px;color:#8a978c;margin-top:6px}
.url{background:var(--accent);color:#10170b;border-radius:14px;padding:18px 26px;font-size:25px;font-weight:900;white-space:nowrap}
.note{margin-top:18px;font-size:14px;color:var(--accent);font-weight:700;letter-spacing:.04em}
.disc{margin-top:10px;font-size:12px;color:#6d7a6f;line-height:1.5}
"""


def render(n):
    badge, h1, h2, lead, accent, kind, note = P[n]
    solid = accent.lstrip("#")
    ar = int(solid[0:2], 16); ag = int(solid[2:4], 16); ab = int(solid[4:6], 16)
    html = f'''<!DOCTYPE html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="file://{MKT}/local.css"><style>
:root{{--accent:{accent};--accent-a:rgba({ar},{ag},{ab},.10)}}
{CSS_EXTRA}</style></head><body><div class="page">
<div class="top"><div class="brand"><img src="file://{ROOT}/assets/traderwatch-logo.svg"><div class="bn">TRADER<span>WATCH</span></div></div><div class="badge">{badge}</div></div>
<div class="hero"><div class="eyebrow">AUTOMATED AI SIGNALS · TRADERWATCH</div>
<h1>{h1}<br><span class="ac">{h2}</span></h1><div class="lead">{lead}</div></div>
{art(kind, accent)}
<div class="footer"><div class="cta-row"><div><div class="cta-main">Read the market. <span>Clearly.</span></div><div class="cta-sub">Free · Installable · Works offline</div></div><div class="url">traderwatch.org</div></div>
<div class="note">{note}</div><div class="disc">Risk disclosure: Trading forex, metals and crypto involves substantial risk of loss. Past performance does not guarantee future results. Educational tool, not financial advice.</div></div>
</div><script>window.addEventListener('load',()=>{{const bad=[];document.querySelectorAll('.page *').forEach(el=>{{const r=el.getBoundingClientRect();if(r.width===0&&r.height===0)return;if(r.right>1081||r.bottom>1351||r.left<-1||r.top<-1)bad.push(el.className||el.tagName)}});document.title=JSON.stringify({{bad:bad.slice(0,8)}})}})</script></body></html>'''
    f = TMP / f"p{n}.html"
    f.write_text(html)
    url = f"file://{f}"
    dom = subprocess.run(["google-chrome", "--headless", "--no-sandbox", "--disable-gpu",
                          "--hide-scrollbars", "--window-size=1080,1350",
                          "--virtual-time-budget=8000", "--dump-dom", url],
                         capture_output=True, text=True).stdout
    m = re.search(r"<title>(\{.*?\})</title>", dom, re.S)
    info = json.loads(m.group(1)) if m else {"bad": ["no-title"]}
    if info.get("bad"):
        print(f"poster {n}: OVERFLOW {info['bad']}")
        return False
    out = MKT / f"poster-{n}.png"
    subprocess.run(["google-chrome", "--headless", "--no-sandbox", "--disable-gpu",
                    "--hide-scrollbars", "--force-device-scale-factor=2",
                    "--window-size=1080,1350", "--virtual-time-budget=8000",
                    f"--screenshot={out}", url], check=True, capture_output=True)
    print(f"poster {n}: OK -> {out.name}")
    return True


def main():
    ns = [int(x) for x in sys.argv[1:]] or list(range(1, 13))
    ok = all(render(n) for n in ns)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
