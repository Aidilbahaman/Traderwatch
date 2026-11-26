# QA Checklist — Manual Close UX (frontend)

Scope: `member/index.html`, `member/layout-dense.html`, `member/layout-compact.html`, `member/layout-wide.html`, `member/layout-focus.html`.
Backend `/api/league/trade-close` (tw-league-api :8103) TIDAK diubah. Commit ini frontend-only.

## Apa yang ditambah

1. **Guard status**: box close (`#tdCloseBox`) disembunyikan bila `status !== 'open'` (sedia ada, dikekalkan); `applyManualClose` juga early-return bila bukan open.
2. **Anti double-submit**: `tdCloseBusy` latch — semasa request in-flight, kedua-dua button `disabled` + `aria-busy="true"` (via `syncCloseBox`), klik kedua diabaikan.
3. **Confirm dialog**: `window.confirm()` sebelum hantar request. Mesej lebih tegas (`closeConfirmMt5`) bila akaun boleh trade MT5 (`mt5Enabled()`); mesej biasa (`closeConfirm`) untuk akaun paper sahaja. Termasuk ID 6 aksara terakhir + pair.
4. **Error toast sebenar**: mesej `error` dari response backend dipapar (`fail(d.error)`); fallback `closeErr` hanya untuk network error / response tanpa `error`.
5. **MT5 toast tepat**: `closeMt5Ok` HANYA bila `mt5.synced === true`; jika tidak, `closeDone`.

## Checklist QA manual (per layout file)

Prasyarat: login member, ada 1 paper trade `open`; service tw-league-api live.

- [ ] **Buka trade detail** → box "Close in Profit / Close in Loss" muncul (status open).
- [ ] **Trade closed (tp/sl)** → buka trade detail closed → box close TIDAK muncul. (Req 1)
- [ ] **Klik Close in Profit** → confirm dialog muncul dulu, trade TIDAK tertutup sebelum OK.
- [ ] **Cancel confirm** → tiada request ke `/api/league/trade-close` (semak Network tab), trade masih open, button masih boleh klik.
- [ ] **OK confirm** → button kedua-duanya disabled + kelihatan pudar semasa request; tak boleh klik kedua kali (Req 2, T5).
- [ ] **Berjaya (akaun paper)** → toast "Trade ditutup." sahaja; box close hilang; status jadi TP/SL; leaderboard refresh. (Req 5, tanpa MT5)
- [ ] **Berjaya (akaun MT5, position ada)** → toast "Trade ditutup — posisi MT5 juga ditutup."; posisi MT5 ditutup di broker.
- [ ] **Berjaya (akaun MT5, tiada position)** → toast "Trade ditutup." sahaja (mt5.synced=false).
- [ ] **Error backend** (cth. trade dah ditutup dari device lain semasa dialog terbuka → 409 "Trade already closed.") → mesej error SEBENAR dari backend muncul dalam toast, button re-enabled boleh klik semula. (Req 3)
- [ ] **Offline / network fail** → toast generik "Gagal menutup trade.", button re-enabled. (Req 3)
- [ ] **Klik semula selepas error** → confirm muncul semula, boleh retry.
- [ ] **Bahasa** (ms / en / zh / id / ta) → confirm message mengikut bahasa aktif; tiada key mentah (cth. `closeConfirmMt5`) terpapar.
- [ ] **PWA cache**: selepas deploy, hard-refresh / update service worker supaya HTML lama (tanpa confirm) tidak terus dihidangkan.

## Ujian automatik (sudah lulus — 23/23)

Harness Node melawan kod sebenar yang diekstrak dari `member/index.html` (stubs untuk `$`, `t`, `apiFetch`, `toast`, `confirm`):

```bash
node <harness>   # RESULT: 23 pass, 0 fail
```

Kes dibangkitkan: T1 cancel-confirm (tiada request), T2 request body `{id, reason}` + button disabled + aria-busy + toast closeDone + league reload + state update, T2b toast MT5 bila synced=true (dan tiada toast berganda), T3 mesej error backend + re-enable + latch released, T4 network fail fallback + re-enable, T5 double-click → hanya 1 request, T6 status bukan 'open' → tiada confirm/tiada request, T7 teks confirm MT5 lebih tegas untuk akaun MT5.

Nota QA: T2b sahkan Req 4 — `closeMt5Ok` hanya bila `mt5.synced===true`.

## ChecksCI/teknikal yang dilakukan sebelum commit

- `node --check` pada SEMUA inline `<script>` block (3 blok × 5 fail) — lulus.
- Core JS (latch + `syncCloseBox` + `applyManualClose`) byte-identical merentas 5 fail (md5 sama).
- 5 lokasi i18n per fail (ms/en/zh/id/ta) dimasukkan pada blok DICT yang betul, `closeConfirm`/`closeConfirmMt5` ×5 setiap fail.
- `git diff -U0` = 12 hunk per fail, tiada perubahan lain disentuh; fail lain (glass-*/style-* tidak ada UI close, backend, data) tidak diubah.

## Smoke test ringkas tanpa login (optional)

- `curl -s -X POST http://127.0.0.1:8103/api/league/trade-close -H 'Content-Type: application/json' -d '{"id":"x","reason":"profit"}'` → expect `{"error":"Please sign in as a member."}` (401). Sahkan route hidup.
