# bot/ — Twbackendbot (admin/analisis bot)

Salinan **version-controlled** daripada `/home/ubuntu/tw-bot/`.
Fail live kekal di `/home/ubuntu/tw-bot/` (bukan symlink) kerana bot itu
guna `bot.db`, `lib/`, `.env` dan `PYTHONPATH` sendiri.

## Fail
- `bot_v2.py` — bot admin/analisis (`@Twbackendbot`).
  - Model LLM **dipin** ke `minimax/minimax-m3.1-flash:free` (OpenRouter),
    preset lain dilumpuhkan dalam menu `/model` (lihat `PINNED_PRESET`).
  - `fcntl`-style single-instance tak relevan di sini; yang penting
    `_apply_pin()` dipanggil sebelum `Application.builder()`.
  - Route per model (`MODEL_ROUTES`) supaya chain fallback boleh campur
    OpenRouter + serveras.
- `set-llm-preset.py` — CLI tukar preset (ada preset `flash`).

## Sync
Setelah ubah fail live, salin semula ke repo:

```bash
cp /home/ubuntu/tw-bot/bot_v2.py      web/Traderwatch-repo/bot/bot_v2.py
cp /home/ubuntu/tw-bot/set-llm-preset.py web/Traderwatch-repo/bot/set-llm-preset.py
```

## Rahsia
`.env` (BOT_TOKEN, ADMIN_IDS) **tidak** masuk repo. Kunci LLM dibaca dari
`~/.hermes/profiles/bobbuilder/.env` (`OPENROUTER_API_KEY`).
