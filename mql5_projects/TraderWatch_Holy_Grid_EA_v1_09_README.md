# TraderWatch Holy Grid EA v1.09

- Backed up from live MT5 EA on 2026-11-15.
- Source: MQL5/Experts/TraderWatch_Holy_Grid_EA.mq5
- Binary: MQL5/Experts/TraderWatch_Holy_Grid_EA.ex5
- Live chart: BTCUSD (chart02) via MT5 on VPS.
- Current feature set: no SL/TP/trailing, profit-layer only.
- Layer: add same-lot layer after favourable price movement of $0.10; lot same as start lot (0.01); max total positions 10.
- Exit: EMA trend guard closes EA positions on trend flip.
- Protection: drawdown guard $50, daily limit disabled, no basket TP/SL.

