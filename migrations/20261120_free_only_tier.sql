-- 2026-11-20: Hapus tiering pro/max — semua ahli jadi FREE (Free Card sahaja).
-- Keputusan pemilik: tiada lagi tier berbayar; semua member yang pernah
-- jadi max/pro dipindah menjadi free member. Akses signal penuh untuk semua
-- ahli (get_signals() live memang pulangkan semua verified signal kepada
-- mana-mana authenticated user — tiada gating plan di server).
--
-- Backup sebelum migration: backups/profiles-pre-free-migration-<ts>.json
-- (11 profiles: 7 max, 2 pro, 2 free → semua 11 free).
--
-- Rollback (jika perlu): restore plan dari backup JSON tersebut.

update public.profiles
set plan = 'free'
where plan in ('pro', 'max');

-- UI app (member/root/pwa-app) dikemas kini serentak:
--  - Kad "Automation Trade RM150" → "Free Card" (tiada harga, tiada naik taraf).
--  - Chip PRO/MAX, teaser signal locked, butang "Naik taraf" dibuang.
--  - "Signal anda": papar signal TERKINI sahaja untuk setiap pair; signal dah
--    tutup (SL/TP/expired/cancelled) diarkibkan (tidak dipapar dalam senarai
--    aktif — ada dalam "Keputusan terkini" / Prestasi).