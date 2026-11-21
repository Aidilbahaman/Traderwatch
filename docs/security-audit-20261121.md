# Security Audit — traderwatch.org (2026-11-21)

**Skor: 82/100 — launchable with caveats.** (H2/H3 dibaiki susulan; M1/M2 dalam kerja) Tiada blocker kritikal tinggal selepas
fix audit ini; baki risiko ialah keputusan owner (Turnstile real key, scope sudo,
SSL Cloudflare Full-strict) dan hardening tambahan (CSP, rate-limit turnstile).

Audit berasaskan bukti tempatan sahaja (tiada scanner luar / data dihantar ke
pihak ketiga). Semua probe terhadap URL deployed sendiri + Supabase project sendiri.

## Dibaiiki & disahkan dalam audit ini

| # | Isu | Teruk | Fix | Bukti |
|---|-----|-------|-----|-------|
| 1 | `get_leaderboard` RPC boleh dipanggil **anon/publishable key** → nama ahli + stats + user_id bocor tanpa login | High | REVOKE EXECUTE FROM PUBLIC, anon | probe anon → `42501 permission denied` |
| 2 | `bump_analyses(p_uid)` PUBLIC **tiada auth** → sesiapa boleh tambah count analisis mana-mana uid (dibuktikan live: count owner naik 1) | Medium | REVOKE → service_role sahaja; count owner dipulihkan -1 | probe anon → 42501 |
| 3 | RPC tiering mati (`submit_payment_request`, `queue_plan_notification`) boleh ditulis authenticated; fungsi trigger (`handle_new_user`, `touch_ideas_updated_at`) public-executable | Medium | REVOKE PUBLIC/anon/authenticated | signup sah masih cipta profile (trigger jalan) ✓ |
| 4 | Supabase terima password **6 aksara** (client sahaja kuatkuasa 8) | Medium | `password_min_length=8` via management API | signup 6 char → `422 weak_password` |
| 5 | **Tiada security headers** langsung (clickjack, MIME-sniff, referrer) | Medium | Caddy: nosniff, X-Frame-Options DENY, Referrer-Policy, Permissions-Policy, HSTS (blok HTTPS + HTTP) | curl -I live menunjukkan semua header |
| 6 | Chat API `Access-Control-Allow-Origin: *` | Low-Med | Whitelist `https://traderwatch.org` (+www), Vary: Origin | Origin evil → ACAO traderwatch.org |
| 7 | Fail `engine/mt5-pending.env.bak-risk-*` committed dalam git (kandungan: config risk sahaja, **tiada credential**) | Low | `git rm` | git ls-files bersih |
| 8 | **H2: ubuntu sudo NOPASSWD ALL** (RCE→root) | High | sudoers scoped `/etc/sudoers.d/10-ubuntu-traderwatch` (whitelist systemctl tw-*/caddy, cp/sed/chown terhad dest, bridge mt5, read ops); grant ALL dikoment | smoke: bridge MT5 ok, systemctl ok, caddy validate ok, cp+chown ok; `cat /etc/shadow` & `sudo bash` DITOLAK |
| 9 | **H3: CF Flexible SSL + www NXDOMAIN** | High | CNAME www dicipta (CF_DNS_TOKEN); SSL mode zone → **strict**; origin cert LE CN=traderwatch.org sah | curl via CF: /member/ 200, /login.html 200, api health ok; www 525 sementara (backoff cert Caddy 6j — reset pada restart caddy seterusnya) |

## Kekuatan sedia ada (disahkan)

- Laluan privasi 404: `/engine/*`, `/state/*`, `/migrations/*`, `/docs/*`,
  `/supabase/*`, `/.git/*`, `*.bak`, `/bot/*`, `/member-data.json`.
- Semua API service bind `127.0.0.1` (8101/8102/8103); Caddy proxy sahaja.
- RLS: `paper_trades`, `chat_messages`, `signals` → anon dapat `[]`.
- RPC admin (`admin_set_plan`, `admin_review_payment`, `admin_list_*`) guarded
  `is_admin()` / `profiles.role='admin'`; `create_link_token` self-only;
  `my_payment_requests` own-rows.
- Chat sanitisation **server-side** (link/phone/email/handle); client render `esc()`.
- Secrets di `/home/ubuntu/.secrets/` mode 600, di luar repo; tiada token dalam log.
- Rate limit: analyze 20s gap + 12/jam; chat 5s; league max open trades.
- Auth gate member: token + `expires_at` disemak setiap buka app.
- Origin IP private (10.x) — tiada bypass langsung dari internet; traffic masuk via Cloudflare.
- Idempotency MT5: dedup key 6 jam, reconcile magic sebelum place, kill-switch, max pending.

## Risiko tinggal / keputusan owner

- **H1 — Turnstile TEST key** (`1x00000000000000000000AA`, always-pass) + backend
  fail-open bila CF unreachable → login tiada protection bot sebenar; panggilan
  terus ke Supabase auth bypass widget. Fix: widget Turnstile sebenar (dashboard
  owner) + enable **Supabase Auth captcha** dengan key sama.
- **H2 — `ubuntu` sudo NOPASSWD ALL.** Service web-facing berjalan sebagai ubuntu;
  jika RCE pada mana-mana API → root serta-merta. Fix: scope sudoers kepada
  senarai command diperlukan (systemctl unit tw-*, caddy, bridge mt5, fail ops).
  Perlu enumerasi teliti supaya ops tidak pecah.
- **H3 — Cloudflare Flexible SSL** → CF→origin HTTP plaintext (dalam network
  private cloud). Fix: Full (strict) + origin certificate. Berkaitan:
  `www.traderwatch.org` NXDOMAIN → Caddy loop cuba cert (attempt 25+) dan www mati;
  tambah CNAME www di Cloudflare atau buang blok site www.
- **M1 — Tiada CSP.** App inline-JS berat; mula dengan `Content-Security-Policy-Report-Only`
  dan ketatkan berperingkat. Impak XSS tinggi kerana session dalam localStorage.
- **M2 — `/api/turnstile/verify` unauth tanpa rate limit** → abuse quota siteverify CF.
- **M3 — Tiada CI / regression security automatik.** QC headless wujud tetapi manual.
- **L1 — Caddy admin endpoint disabled** → `systemctl reload` gagal (guna restart);
  enable admin localhost:2019 untuk reload graceful (pilihan).

## Evidence checked

- `curl -I` headers live; probe 10 laluan privasi; `ss -tln`; `sudo -n -l`;
  `ls -la .secrets`; `ufw status`; `hostname -I`.
- Supabase REST probes dengan publishable key (paper_trades/chat_messages/signals/
  rpc get_leaderboard/bump_analyses); `pg_proc` ACL + `pg_get_functiondef` semua
  fungsi public; `pg_trigger`; management API config/auth.
- Signup probes (6 char → 422 selepas fix; 8+ char → profile trigger jalan);
  akaun probe dipadam selepas setiap ujian.
- `git ls-files` secret sweep; grep token dalam /tmp/*.log (tiada).
- Caddyfile kedua blok (HTTPS + HTTP mirror private rules ✓).

## Evidence missing

- Dashboard Cloudflare: SSL mode sebenar, WAF/rate-limit rules sedia ada.
- Dashboard Supabase Auth: captcha setting, auth rate limits.
- Kandungan penuh sudoers.d (untuk scope H2 dengan selamat).

## Next action

Owner beri **Turnstile site key + secret** (dashboard → Turnstile → Add widget,
domain traderwatch.org, mode Managed); saya swap key login + secret service dan
enable Supabase Auth captcha. Kemudian scope sudoers (H2) dan CF Full-strict (H3).