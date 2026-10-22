#!/usr/bin/env python3
"""Tukar preset model LLM TraderWatch: berbayar atau percuma.

Guna:
  python3 set-llm-preset.py paid     # v4-flash sahaja
  python3 set-llm-preset.py free     # freemodel sahaja
  python3 set-llm-preset.py auto     # v4-flash, jatuh ke free bila 402
  python3 set-llm-preset.py status   # tunjuk preset semasa

Preset ditulis ke /home/ubuntu/tw-bot/.env. Perubahan berkuat kuasa
sebaik sahaja perkhidmatan di-restart (bot baca .env semasa import).
"""
import re
import subprocess
import sys
from pathlib import Path

ENV = Path("/home/ubuntu/tw-bot/.env")
SERVICE = "traderwatch-signals-bot"

PRESETS = {
    "minimax": {
        "desc": "MiniMax m3.1 flash free (OpenRouter) - paling cepat",
        "model": "minimax/minimax-m3.1-flash:free",
        "fallback": "asai/freemodel-2-MiniMax",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
    },
    "deepseek": {
        "desc": "DeepSeek v4 Flash (OpenRouter) - analisis paling tepat",
        "model": "deepseek/deepseek-v4-flash",
        "fallback": "asai/deepseek-v4-flash",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
    },
    "free": {
        "desc": "GLM free (serveras) - percuma, sandaran bila MiniMax sibuk",
        "model": "asai/freemodel-1-GLM",
        "fallback": "minimax/minimax-m3.1-flash:free",
        "url": "https://serveras.click/v1/chat/completions",
        "key_env": "HERMES_CUSTOM_SERVERAS_CLICK_API_KEY",
    },
}


def read_env():
    vals = {}
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            vals[k.strip()] = v
    return vals


def write_preset(name):
    cfg = PRESETS[name]
    text = ENV.read_text()
    lines = text.splitlines()
    out = []
    seen = set()
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else None
        if key == "LLM_MODEL":
            out.append(f"LLM_MODEL={cfg['model']}")
            seen.add("LLM_MODEL")
        elif key == "LLM_FALLBACK_MODELS":
            out.append(f"LLM_FALLBACK_MODELS={cfg['fallback']}")
            seen.add("LLM_FALLBACK_MODELS")
        elif key == "LLM_URL":
            out.append(f"LLM_URL={cfg['url']}")
            seen.add("LLM_URL")
        elif key == "LLM_KEY_ENV":
            out.append(f"LLM_KEY_ENV={cfg['key_env']}")
            seen.add("LLM_KEY_ENV")
        else:
            out.append(line)
    if "LLM_MODEL" not in seen:
        out.append(f"LLM_MODEL={cfg['model']}")
    if "LLM_FALLBACK_MODELS" not in seen:
        out.append(f"LLM_FALLBACK_MODELS={cfg['fallback']}")
    if "LLM_URL" not in seen:
        out.append(f"LLM_URL={cfg['url']}")
    if "LLM_KEY_ENV" not in seen:
        out.append(f"LLM_KEY_ENV={cfg['key_env']}")
    ENV.write_text("\n".join(out).rstrip() + "\n")


def restart():
    subprocess.run(["sudo", "systemctl", "restart", SERVICE],
                   capture_output=True, text=True, timeout=120)
    r = subprocess.run(["systemctl", "show", SERVICE,
                        "-p", "ActiveState", "-p", "MainPID", "--no-pager"],
                       capture_output=True, text=True)
    return r.stdout.strip().replace("\n", " ")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in PRESETS and sys.argv[1] != "status":
        print("Guna: set-llm-preset.py [minimax|deepseek|free|status]")
        return 2

    cmd = sys.argv[1]
    if cmd == "status":
        v = read_env()
        print("Preset semasa:")
        print("  LLM_MODEL          =", v.get("LLM_MODEL"))
        print("  LLM_FALLBACK_MODELS=", repr(v.get("LLM_FALLBACK_MODELS", "")))
        return 0

    cfg = PRESETS[cmd]
    write_preset(cmd)
    print(f"Preset ditetapkan: {cmd}")
    print(f"  {cfg['desc']}")
    print(f"  LLM_MODEL          = {cfg['model']}")
    print(f"  LLM_FALLBACK_MODELS= {cfg['fallback'] or '(kosong)'}")
    print("Restart perkhidmatan...")
    print(" ", restart())
    return 0


if __name__ == "__main__":
    sys.exit(main())
