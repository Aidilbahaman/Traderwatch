# Signal spec — for AI-assisted signal producers

This is the contract for any signal that enters TraderWatch, whether it comes
from the rule engine (`signal-engine.py`) or from an AI-assisted producer.
Follow it exactly and the signal imports cleanly on the first try.

## Where signals live

Table `signals` in Supabase. Only rows with `verified = true` are shown to
members. Never insert with `verified = false` and expect it to appear.

## Fields

| Field | Type | Required | Notes |
|---|---|---|---|
| `pair` | string | yes | One of the six whitelisted pairs below, formatted `XXX/YYY` |
| `side` | string | yes | `BUY` or `SELL` (uppercase) |
| `timeframe` | string | yes | `H1` or `M1` |
| `entry` | number | yes | Current market price at time of posting |
| `sl` | number | yes | Stop loss |
| `tp` | number | yes | Take profit |
| `verified` | boolean | yes | Must be `true` |
| `posted_at` | timestamp | no | Defaults to now (UTC). Do not backdate. |

### Whitelisted pairs

```text
XAU/USD   EUR/USD   GBP/USD   USD/JPY   AUD/USD   USD/CAD
```

### Pip size per pair

| Pair | 1 pip |
|---|---|
| `XAU/USD` | 0.1 |
| `USD/JPY` | 0.01 |
| all others | 0.0001 |

## Hard rules — an import is rejected if any fail

1. **Direction sanity**
   - `BUY`: `sl < entry < tp`
   - `SELL`: `tp < entry < sl`
2. **M1 (scalping) risk band**
   - Stop loss must be **20–40 pips** away from entry.
   - Take profit must be **~2× the stop** (ratio 1.8–2.2).
   - Reason: M1 ATR is 0.5–2 pips, so tighter stops die on spread and noise.
3. **H1 minimum reward**
   - Reward-to-risk must be **at least 1.5**.
4. **One active setup per pair**
   - While any timeframe for a pair is `active`, a new signal for that pair is
     rejected — including the opposite side. Two conflicting AUD/USD setups at
     08:00 and 08:30 is exactly the confusion this rule prevents.
5. **No backdating.** `posted_at` must be within the last 10 minutes.

## Lifecycle

| Timeframe | Closes when |
|---|---|
| `M1` | TP hits, SL hits, or an operator cancels it. **No time expiry.** |
| `H1` | TP hits, SL hits, or 48 hours pass without either. |

## Workflow for an AI-assisted producer

1. Analyse and produce a JSON array of candidate signals.
2. Run the validator — it never writes anything:

   ```bash
   python3 engine/signal-import.py --file candidates.json
   ```

3. Read the report. Fix every `REJECT`. Re-run until all rows are `OK`.
4. Import for real:

   ```bash
   python3 engine/signal-import.py --file candidates.json --commit
   ```

5. Tell the operator what was posted. Members are notified by
   `signal-telegram-sender.py` on its next cron tick.

## Candidate file format

```json
[
  {
    "pair": "XAU/USD",
    "side": "BUY",
    "timeframe": "H1",
    "entry": 4164.75,
    "sl": 4149.20,
    "tp": 4195.80
  }
]
```

## What to check before submitting

- Is the pair already active? The validator tells you.
- Are the levels from a real quote, not invented? A quote-derived guess is not
  a setup. If there is no valid setup, submit nothing — an empty array is a
  correct answer.
- Does the stop sit outside normal noise for that timeframe?
- Is the R:R honest, or has the TP been stretched to look attractive?

## Never do

- Insert rows directly into Supabase, bypassing the validator.
- Mark `verified = true` for a signal you have not checked.
- Post a second signal for a pair that is still active.
- Present an AI-generated setup as guaranteed or as financial advice.
