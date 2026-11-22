"""Ringkasan 'hot pair' dari paper_trades sebenar — untuk endpoint /api/league/hot."""
import json
import re
import urllib.request
from collections import defaultdict

ENV = '/home/ubuntu/.secrets/supabase.env'
SB = 'https://vicfiftvhxemuhxxmkxk.supabase.co'


def _key():
    env = open(ENV).read()
    return re.search(r'SUPABASE_SERVICE_KEY\s*=\s*["\']?([^"\'\s]+)', env).group(1)


def hot_pairs(season=1, limit=40):
    key = _key()
    req = urllib.request.Request(
        SB + f'/rest/v1/paper_trades?select=pair,status,r_result,user_id&season=eq.{season}&limit=2000',
        headers={'apikey': key, 'Authorization': 'Bearer ' + key})
    rows = json.load(urllib.request.urlopen(req, timeout=25)) or []

    agg = defaultdict(lambda: {'trades': 0, 'wins': 0, 'net_r': 0.0, 'members': set()})
    for r in rows:
        p = str(r.get('pair') or '').upper().replace('/', '')
        if not p:
            continue
        a = agg[p]
        a['trades'] += 1
        a['members'].add(r.get('user_id'))
        if r.get('status') == 'tp':
            a['wins'] += 1
        if r.get('r_result') is not None:
            a['net_r'] += float(r['r_result'])

    out = []
    for pair, a in agg.items():
        n = a['trades']
        wr = (100.0 * a['wins'] / n) if n else 0.0
        members = len(a['members'])
        # Heat: usage 40% + winrate 40% + net R 20%. Usage dinormalisasi
        # terhadap max members, R dikelipat 10 (R tipikal -1..+3).
        out.append({'pair': pair, 'trades': n, 'wins': a['wins'],
                    'win_rate': round(wr, 1), 'net_r': round(a['net_r'], 2),
                    'members': members, '_raw': (members, wr, a['net_r'])})

    if not out:
        return []
    max_members = max(x['_raw'][0] for x in out) or 1
    for x in out:
        members, wr, net_r = x['_raw']
        heat = (0.40 * (members / max_members)
                + 0.40 * min(1.0, wr / 100.0)
                + 0.20 * min(1.0, max(0.0, net_r) / 10.0))
        x['heat'] = round(heat * 100, 1)
        x['new'] = x['trades'] < 3
        del x['_raw']

    out.sort(key=lambda x: (-x['heat'], -x['trades']))
    return out[:limit]


if __name__ == '__main__':
    print(json.dumps(hot_pairs(), indent=1))
