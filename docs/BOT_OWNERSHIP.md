# Telegram bot ownership — prevent sending the wrong keyboard

Two bots, two audiences. Sending a keyboard from the wrong one puts admin
buttons in front of members (or hides them from the admin).

| Bot | Username | Token | Audience | Menu |
|---|---|---|---|---|
| Signals / membership | `@Traderwatchmembershipbot` | `TELEGRAM_SIGNALS_BOT_TOKEN` | members | **Subscription only** |
| Backend / admin | `@Twbackendbot` | `BOT_TOKEN` in `tw-bot/.env` | owner only | full 8-button menu |

`signal-tg-bot.py` (the membership bot service) never sends a reply keyboard —
it only uses inline keyboards. Do not add one there.

Member-facing chat should only ever show the single `💳 Subscription` button.
Admin-only buttons (Draft Signal, Auto Screener, Profit Guard) exist **only**
in `bot_v2.py` `MENU_ADMIN`, which is served by `@Twbackendbot`.

## Verify before sending any keyboard

```bash
python3 - <<'PY'
import os, json, urllib.request, pathlib
tok = dict(l.split('=',1) for l in pathlib.Path('/home/ubuntu/tw-bot/.env')
           .read_text().splitlines() if '=' in l)['BOT_TOKEN'].strip('"\'')
print(json.loads(urllib.request.urlopen(
    f'https://api.telegram.org/bot{tok}/getMe').read())['result']['username'])
PY
```

Expect `@Twbackendbot`. If you see `@Twreg_bot` or
`@Traderwatchmembershipbot`, you are about to broadcast the wrong menu.

## Commands

Owner-only, in `@Twbackendbot`:

- `/subs` — subscription list for every member
- `/warn <tg_id>` — send the renew message to a member
- `/renew <tg_id> [PRO|MAX|FREE]` — change a member's tier

## Historical

The admin 8-button menu was once sent from `@Traderwatchmembershipbot`, so a
member-facing chat showed Draft Signal, Auto Screener and Profit Guard. Each
keyboard must be sent from the bot that owns that audience.