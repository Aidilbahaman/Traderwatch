# Trader Watch AI Confluence Engine

Implementasi spec `trader_watch_ai_handoff` (v1.0). **Signal-only** — tidak
pernah hantar order ke broker.

## Prinsip wajib (dari spec)

- Tiada data masa depan / pivot belum confirm.
- Semua timestamp UTC.
- Data hilang = `UNAVAILABLE`, bukan neutral.
- Confluence score ≠ kebarangkalian untung.
- Guna candle tertutup untuk signal.
- Digit/pip ikut instrumen, jangan andaikan.

## Struktur

| Modul | Fasa | Peranan |
|---|---|---|
| `instruments.py` | 1 | Metadata: digit, pip, asset class |
| `market_data.py` | 1 | Adapter MT5 read-only, dedup, gap, staleness, health |
| `data_health.py` | 1 | Endpoint health data (akan datang) |
| `features/` | 2 | Structure, liquidity, ICT, quant, MTF, session |
| `scoring.py` | 3 | Kumpulan skor, coverage, conflict |
| `decision.py` | 3 | BUY/SELL/WAIT/NO_TRADE + reason codes |
| `lifecycle.py` | 4 | Analysis run, audit, publish |
| `backtest.py` | 5 | Walk-forward, spread, metrik |

## Data UNAVAILABLE (jangan reka)

COT · DXY · bond yields · futures volume · CVD · bid/ask imbalance ·
footprint · open interest

## Ujian

```bash
/usr/bin/python3.12 tests/confluence/test_phase1_data.py
```

Guna `/usr/bin/python3.12` (matplotlib/numpy ada di situ).
