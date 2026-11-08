#!/usr/bin/env python3
"""Fetch real traffic data from Cloudflare analytics -> traffic-30d.json

Fills the landing page "Global Reach" globe with live numbers so the section
never goes stale.

WHY THIS IS NOT A SIMPLE httpRequestsAdaptiveGroups COUNT
-----------------------------------------------------------
The raw request count on this zone is dominated by scraper traffic. Measured
over 28 days on traderwatch.org:

    total requests      86,640
    scanner probes      23,610   (.git dumps, .env hunting)
    crawler traffic     60,160   (gitdump/1.0, git/2.34.1)
    real page requests   3,020   (~3.5%)

So a naive request count would report ~68x the real audience and would show
Netherlands/Poland/UK as top "countries" purely because the dump bots are
hosted there. That is worse than useless for a marketing section.

Instead we only count requests that look like a real visitor loading a page:

  1. the path is an HTML page (not an asset, not a scanner target), and
  2. the user agent is a current browser engine.

Both filters must pass. Whatever is left is a real visitor session.

Credentials live in /home/ubuntu/.secrets/cloudflare.env (never in this file):

    CF_API_TOKEN=...      # token with Zone -> Analytics -> Read
    CF_ZONE_ID=...        # zone id for traderwatch.org

If credentials are missing the script exits 0 without touching the existing
file, so a cron job never wipes good data just because a token expired.
"""
import json
import pathlib
import re
import sys
import urllib.error
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone

ENV = pathlib.Path("/home/ubuntu/.secrets/cloudflare.env")
OUT = pathlib.Path("/home/ubuntu/web/Traderwatch-repo/traffic-30d.json")
# The landing page inlines the same numbers; keep it in sync with OUT.
LANDING = pathlib.Path("/home/ubuntu/web/Traderwatch-repo/index.html")

# Cloudflare's free analytics dataset keeps 28 days; asking for 30 is rejected.
DAYS = 28

# Only the apex host. member.traderwatch.org is behind login and is mostly
# bots hitting the door, which would skew the country mix.
HOST = "traderwatch.org"

# A row counts as a page view only if it fetched a real page.
PAGE_PATHS = re.compile(
    r"^/(?:index\.html|members\.html|login\.html|member/?|pricing|about|blog|guide|faq)?$",
    re.I)

# Scanner bait. Any of these means the request is not a reader.
SCANNER_PATHS = re.compile(
    r"(?:\.git|\.env|\.svn|\.hg|\.php|wp-|wordpress|xmlrpc|adminer|phpmyadmin|"
    r"vendor/|composer\.|\.sql|\.db|\.log|\.bak|\.pem|\.key|\.ini|\.conf|"
    r"\.ya?ml|\.toml|backup|dump|\.aws|\.ssh|\.DS_Store|ioxi)",
    re.I)

# Browser user agents that are plausibly a person on a current device.
BROWSER_UA = re.compile(
    r"^Mozilla/5\.0 \((?:"
    r"Windows NT 1[01]\.\d|"
    r"Macintosh; Intel Mac OS X 1[0-9]_|"
    r"iPhone; CPU iPhone OS 1[5-9]_|"
    r"iPad; CPU OS 1[5-9]_|"
    r"Linux; Android 1[0-9]|"
    r"Linux x86_64\) AppleWebKit"
    r")",
    re.I)

# Aggregated in the query: country x user agent x path.
QUERY = """
query($zone: String!, $from: Time!, $to: Time!) {
  viewer {
    zones(filter: {zoneTag: $zone}) {
      httpRequestsAdaptiveGroups(
        limit: 10000
        filter: {
          datetime_geq: $from
          datetime_leq: $to
          clientRequestHTTPHost: HOST_PLACEHOLDER
        }
        orderBy: [count_DESC]
      ) {
        count
        dimensions { clientCountryName userAgent clientRequestPath }
      }
    }
  }
}
""".replace("HOST_PLACEHOLDER", json.dumps(HOST))

# country code -> (name, lat, lon) of a representative city.
GEO = {
    "MY": ("Malaysia", 3.14, 101.69),
    "US": ("United States", 38.90, -77.04),
    "SG": ("Singapore", 1.35, 103.82),
    "TW": ("Taiwan", 25.03, 121.56),
    "CH": ("Switzerland", 46.95, 7.45),
    "KR": ("South Korea", 37.57, 126.98),
    "ID": ("Indonesia", -6.21, 106.85),
    "AU": ("Australia", -33.87, 151.21),
    "GB": ("United Kingdom", 51.51, -0.13),
    "CA": ("Canada", 45.42, -75.70),
    "DE": ("Germany", 52.52, 13.40),
    "NL": ("Netherlands", 52.37, 4.90),
    "FR": ("France", 48.86, 2.35),
    "IN": ("India", 28.61, 77.21),
    "JP": ("Japan", 35.68, 139.69),
    "AE": ("United Arab Emirates", 25.20, 55.27),
    "SA": ("Saudi Arabia", 24.71, 46.68),
    "TH": ("Thailand", 13.76, 100.50),
    "VN": ("Vietnam", 21.03, 105.85),
    "PH": ("Philippines", 14.60, 120.98),
    "PK": ("Pakistan", 33.68, 73.05),
    "BD": ("Bangladesh", 23.81, 90.41),
    "ZA": ("South Africa", -25.75, 28.19),
    "NG": ("Nigeria", 9.06, 7.49),
    "TR": ("Turkey", 39.93, 32.86),
    "RU": ("Russia", 55.75, 37.62),
    "NZ": ("New Zealand", -41.29, 174.78),
    "BR": ("Brazil", -15.79, -47.88),
    "ES": ("Spain", 40.42, -3.70),
    "CN": ("China", 39.90, 116.40),
    "HK": ("Hong Kong", 22.32, 114.17),
    "IT": ("Italy", 41.90, 12.50),
    "AR": ("Argentina", -34.60, -58.38),
    "BE": ("Belgium", 50.85, 4.35),
    "IL": ("Israel", 31.78, 35.22),
    "FI": ("Finland", 60.17, 24.94),
    "LT": ("Lithuania", 54.69, 25.28),
    "DK": ("Denmark", 55.68, 12.57),
    "NO": ("Norway", 59.91, 10.75),
    "SE": ("Sweden", 59.33, 18.07),
    "PL": ("Poland", 52.23, 21.01),
    "PT": ("Portugal", 38.72, -9.14),
    "IE": ("Ireland", 53.35, -6.26),
    "AT": ("Austria", 48.21, 16.37),
    "MX": ("Mexico", 19.43, -99.13),
    "CL": ("Chile", -33.45, -70.67),
    "CO": ("Colombia", 4.71, -74.07),
    "PE": ("Peru", -12.05, -77.04),
    "EG": ("Egypt", 30.04, 31.24),
    "KE": ("Kenya", -1.29, 36.82),
    "GH": ("Ghana", 5.60, -0.19),
    "QA": ("Qatar", 25.29, 51.53),
    "KW": ("Kuwait", 29.38, 47.99),
    "BH": ("Bahrain", 26.23, 50.59),
    "OM": ("Oman", 23.59, 58.41),
    "BE": ("Belgium", 50.85, 4.35),
    "IL": ("Israel", 31.78, 35.22),
    "FI": ("Finland", 60.17, 24.94),
    "LT": ("Lithuania", 54.69, 25.28),
}

# A country needs at least this many visitor sessions to be shown, so one
# stray hit from an odd location does not become a "country" on the globe.
MIN_VISITS = 30


def load_env():
    if not ENV.exists():
        return None
    sec = {}
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if "=" in line and not line.startswith("#"):
            k, v = line.split("=", 1)
            sec[k.strip()] = v.strip().strip('"').strip("'")
    if sec.get("CF_API_TOKEN") and sec.get("CF_ZONE_ID"):
        return sec
    return None


def graphql(token, query, variables):
    req = urllib.request.Request(
        "https://api.cloudflare.com/client/v4/graphql",
        data=json.dumps({"query": query, "variables": variables}).encode(),
        method="POST")
    req.add_header("Authorization", "Bearer " + token)
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "TraderWatch-traffic/2.0")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError("cloudflare %s: %s" % (e.code, e.read().decode()[:400])) from None


def main():
    sec = load_env()
    if not sec:
        print("no credentials at %s - leaving %s untouched" % (ENV, OUT.name))
        return 0

    to = datetime.now(timezone.utc)
    frm = to - timedelta(days=DAYS)
    data = graphql(sec["CF_API_TOKEN"], QUERY, {
        "zone": sec["CF_ZONE_ID"],
        "from": frm.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": to.strftime("%Y-%m-%dT%H:%M:%SZ"),
    })

    if data.get("errors"):
        print("cloudflare reported errors:", json.dumps(data["errors"])[:400])
        return 0

    try:
        groups = data["data"]["viewer"]["zones"][0]["httpRequestsAdaptiveGroups"]
    except (KeyError, IndexError, TypeError):
        print("unexpected response shape - leaving file untouched")
        return 0

    tally = Counter()
    dropped_scan = 0
    dropped_bot = 0
    for g in groups:
        dim = g.get("dimensions") or {}
        n = int(g.get("count") or 0)
        path = (dim.get("clientRequestPath") or "").split("?")[0]
        ua = dim.get("userAgent") or ""

        if SCANNER_PATHS.search(path):
            dropped_scan += n
            continue
        if not PAGE_PATHS.match(path):
            continue
        if not BROWSER_UA.match(ua):
            dropped_bot += n
            continue

        tally[dim.get("clientCountryName") or "??"] += n

    countries = []
    for code, n in tally.most_common():
        if n < MIN_VISITS:
            continue
        if code not in GEO:
            # Unknown country: keep the number, plot at 0,0 off-globe. Honest
            # rather than silently discarded.
            name, lat, lon = code, 0.0, 0.0
        else:
            name, lat, lon = GEO[code]
        countries.append({"c": name, "code": code, "v": n,
                          "lat": lat, "lon": lon, "flag": code})

    if not countries:
        print("no visitor rows survived filtering - leaving file untouched")
        return 0

    total = sum(c["v"] for c in countries)
    payload = {
        "period": "last_%d_days" % DAYS,
        "period_label": "last %d days" % DAYS,
        "as_of": to.strftime("%Y-%m-%d"),
        "source": ("Cloudflare analytics - real visitor page requests "
                   "(browser user agents only; scanner and crawler traffic excluded)"),
        "fetched_at": to.isoformat(),
        "total_visits": total,
        "country_count": len(countries),
        "excluded": {"scanner_requests": dropped_scan, "crawler_requests": dropped_bot},
        "countries": countries,
        "sampled": True,
        "note": ("Real visitor sessions (browser page requests, %d days). "
                 "Bot and scanner traffic excluded. Counts are a Cloudflare "
                 "analytics sample, so treat them as approximate. "
                 "Not registered traders - accounts are tracked separately." % DAYS),
    }

    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=1))
    tmp.replace(OUT)

    # The landing page inlines the same numbers (var D / var TOTAL) so the
    # globe renders without an extra request. Keep the copy in sync, otherwise
    # the cron job would refresh a file nobody reads.
    html_note = sync_landing(LANDING, payload)

    top = " ".join("%s=%d" % (c["code"], c["v"]) for c in countries[:5])
    print("%s updated | visitors=%d countries=%d | %s | excluded: scan=%d crawl=%d"
          % (OUT.name, total, len(countries), top, dropped_scan, dropped_bot))
    if html_note:
        print(html_note)
    return 0


def sync_landing(target, payload):
    """Rewrite the inlined globe data in index.html to match the JSON payload.

    Returns a short status string, or None when nothing needed changing.
    The edit is a no-op when the numbers are already in place, so the file's
    mtime only moves when the data actually changes.
    """
    if not target.exists():
        return "landing page not found at %s" % target

    html = target.read_text()
    original = html
    countries = payload["countries"]

    # 1. country list
    cards = "".join(
        '<div class="gc"><div class="n">%s</div><div class="v">%d</div>'
        '<div class="gbar"><i style="--w:%d%%"></i></div></div>'
        % (c["c"], c["v"], round(100.0 * c["v"] / max(x["v"] for x in countries)))
        for c in countries)

    try:
        a = html.index('<div class="glist">') + len('<div class="glist">')
        b = html.index('</div><p class="gfoot">', a)
    except ValueError:
        return "landing page shaped differently - globals not updated"
    html = html[:a] + cards + html[b:]

    # 2. heading count
    html = re.sub(r'(Traders from <span style="color:var\(--lime\)">)\d+( countries</span>)',
                  lambda m: m.group(1) + str(len(countries)) + m.group(2),
                  html, count=1)

    # 3. inlined JS array + total
    js_rows = [{"c": c["c"], "v": c["v"], "lat": c["lat"], "lon": c["lon"],
                "flag": c.get("flag") or c.get("code")} for c in countries]
    html = re.sub(r"var D=\[.*?\];",
                  "var D=" + json.dumps(js_rows, separators=(", ", ": ")) + ";",
                  html, count=1, flags=re.S)
    html = re.sub(r"var TOTAL=\d+;", "var TOTAL=%d;" % payload["total_visits"],
                  html, count=1)

    if html == original:
        return None
    tmp = target.with_suffix(".html.tmp")
    tmp.write_text(html)
    tmp.replace(target)
    return "landing page synced | countries=%d total=%d" % (len(countries), payload["total_visits"])


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        # never fail loudly in cron; keep the previous good file
        print("traffic fetch failed:", e)
        sys.exit(0)
