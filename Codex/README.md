# Codex — Rootsys Model Registry

Folder ini menyimpan senarai model Rootsys tambahan yang boleh digunakan oleh
Codex / OpenCode dan engine TraderWatch.

## Model semasa

- Primary (sedang digunakan): `rootsys/qwen4-max`
- Model tambahan: lihat `rootsys-models.json`

## Cara guna

- Untuk OpenCode: model diberi awalan `rootsys/<nama-model>`.
- Untuk Codex CLI: tambah model ke `model_providers.rootsys` dalam `~/.codex/config.toml`,
  atau guna `codex --model <nama-model>` selepas Didaftarkan.
- Untuk engine TraderWatch: set `AI_LLM_MODEL` / `AI_LLM_FALLBACKS` dengan
  nama model berprefiks `rootsys/` — `_route()` dalam `engine/llm_analyst.py`
  sudah auto-routing ke `https://rootsys.cloud/v1` bila ada prefiks itu.
