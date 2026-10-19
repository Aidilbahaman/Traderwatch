#!/usr/bin/env python3
"""Shared M15 feature + logistic-model code for the TraderWatch AI engine.

Kept separate from the research script so training and live inference use
exactly the same feature definitions. Any change here changes both sides.
"""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

PIP = {"XAU/USD": 0.1, "USD/JPY": 0.01}
DEFAULT_PIP = 0.0001
BAR_MIN = 15
FEATURE_VERSION = 1


def pip_of(pair):
    return PIP.get(pair, DEFAULT_PIP)


def ema(v, n):
    k = 2.0 / (n + 1)
    e = v[0]
    out = [e]
    for x in v[1:]:
        e = x * k + e * (1 - k)
        out.append(e)
    return out


def rsi_s(v, n=14):
    if len(v) < n + 2:
        return [50.0] * len(v)
    gains, losses = [0.0], [0.0]
    for i in range(1, len(v)):
        d = v[i] - v[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    ag = sum(gains[1:n + 1]) / n
    al = sum(losses[1:n + 1]) / n
    out = [50.0] * (n + 1)
    for i in range(n + 1, len(v)):
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out.append(100.0 if al == 0 else 100.0 - 100.0 / (1 + ag / al))
    return out


def atr_s(bars, n=14):
    tr = []
    for i, (ts, h, l, c) in enumerate(bars):
        pc = bars[i - 1][3] if i else c
        tr.append(max(h - l, abs(h - pc), abs(l - pc)))
    if len(tr) < n + 1:
        return [0.0] * len(bars)
    a = sum(tr[1:n + 1]) / n
    out = [a] * (n + 1)
    for x in tr[n + 1:]:
        a = (a * (n - 1) + x) / n
        out.append(a)
    return out


def feature_row(pair, bars, e20, e50, rsi, atr, i):
    """Feature vector at bar i. Must stay in sync with train-ai-model.py."""
    a = atr[i]
    if a <= 0:
        return None
    hour = datetime.fromtimestamp(bars[i][0] / 1000, tz=timezone.utc).hour
    return [
        (e20[i] - e50[i]) / a,
        (bars[i][3] - e20[i]) / a,
        (rsi[i] - 50) / 25,
        (rsi[i] - rsi[i - 1]) / 5,
        a / pip_of(pair) / 100,
        1.0 if 7 <= hour < 16 else 0.0,
        1.0 if 12 <= hour < 21 else 0.0,
        1.0,
    ]


def sigmoid(z):
    if z > 30:
        return 1.0
    if z < -30:
        return 0.0
    return 1 / (1 + math.exp(-z))


def fit(rows, key, epochs=250, lr=0.06, l2=0.02):
    n = len(rows[0]["f"])
    mu, sd = [0.0] * n, [1.0] * n
    for j in range(n):
        vals = [r["f"][j] for r in rows]
        m = sum(vals) / len(vals)
        s = (sum((v - m) ** 2 for v in vals) / len(vals)) ** 0.5 or 1.0
        mu[j], sd[j] = m, s
    Z = [[(r["f"][j] - mu[j]) / sd[j] for j in range(n)] for r in rows]
    w = [0.0] * (n + 1)
    N = len(rows)
    for _ in range(epochs):
        g = [0.0] * (n + 1)
        for r, z in zip(rows, Z):
            p = sigmoid(w[0] + sum(w[j + 1] * z[j] for j in range(n)))
            d = p - r[key]
            g[0] += d
            for j in range(n):
                g[j + 1] += d * z[j]
        w[0] -= lr * g[0] / N
        for j in range(1, n + 1):
            w[j] -= lr * (g[j] / N + l2 * w[j])
    return w, mu, sd


def predict(model, f):
    w, mu, sd = model["w"], model["mu"], model["sd"]
    z = [(f[j] - mu[j]) / sd[j] for j in range(len(f))]
    return sigmoid(w[0] + sum(w[j + 1] * z[j] for j in range(len(z))))


def save_model(path, payload):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(payload, indent=1))


def load_model(path):
    return json.loads(Path(path).read_text())
