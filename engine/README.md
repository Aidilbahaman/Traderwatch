# TraderWatch engine

Server-side workers for signals, notifications and Telegram delivery.
These run from cron on the VPS; they are **not** part of the static site.

## Secrets

Never committed. Each script reads from `~/.secrets/`:

| File | Keys |
|---|---|
| `supabase.env` | `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` |
| `twelve.env` | `TWELVEDATA_API_KEY` |
| `telegram.env` | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_SIGNALS_BOT_TOKEN`, `TELEGRAM_ADMIN_CHAT_ID` |
| `smtp.env` | `BREVO_SMTP_*` |

All files must be `chmod 600`. `.gitignore` blocks `*.env` and `state/`.

## Scripts

| Script | Schedule | Purpose |
|---|---|---|
| `signal-engine.py` | `*/30 * * * *` | Generates verified H1/M1 setups from Twelve Data candles |
| `signal-status.py` | `*/5 * * * *` | Evaluates open setups against M1 candles → TP/SL/expired |
| `signal-telegram-sender.py` | `5,35 * * * *` | Pushes new signals to linked Pro/Max members |
| `signal-close-alert.py` | `*/5 * * * *` | Admin-only TP/SL closure alerts (@Twreg_bot) |
| `signal-tg-bot.py` | systemd | Telegram linking bot (@Traderwatchmembershipbot) |
| `payment-notifier.py` | `* * * * *` | Pending/approved payment alerts |
| `registration-notifier.py` | `* * * * *` | New registration alerts |
| `plan-notify-worker.py` | `*/5 * * * *` | Member-facing plan upgrade messages |
| `signal-import.py` | manual | Validate + import AI-assisted signals (dry-run by default) |

## Producing signals with AI

Read `signal-spec.md` before generating anything. Validate every candidate
before it reaches the database:

```bash
python3 engine/signal-import.py --status                      # active pairs
python3 engine/signal-import.py --file candidates.json         # dry run
python3 engine/signal-import.py --file candidates.json --commit
```

`candidates.example.json` shows the expected shape.

## Signal lifecycle rules

- **One active setup per pair.** While any timeframe for a pair is `active`,
  the engine emits nothing new for that pair (H1 and M1 included).
- **M1 / scalping never auto-expires.** It stays `active` until TP hits, SL
  hits, or an operator cancels it.
- **H1 expires after 48 hours** without a TP/SL hit.
- If the status file or Supabase check fails, the engine **fails closed** and
  emits no signal rather than risking a duplicate.

## Deployment note

`/home/ubuntu/web/*.py` are symlinks into this directory, so cron and the repo
share one source of truth. Editing either path edits the same file.

## Tests

```bash
cd /home/ubuntu/web/Traderwatch-repo
python3 -m unittest discover -s tests -v
```
