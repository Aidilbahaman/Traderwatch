#!/bin/bash
# Wrapper: jalankan Ironwall bridge di dalam Wine sebagai user mt5.
# Elak masalah escape sequence systemd untuk path Windows.
export DISPLAY=:99
export WINEPREFIX=/home/mt5/.mt5
exec /usr/bin/sudo -n -u mt5 env \
  DISPLAY=:99 \
  WINEPREFIX=/home/mt5/.mt5 \
  IRONWALL_TOKEN="${IRONWALL_TOKEN:-}" \
  /opt/wine-staging/bin/wine 'C:\Python311\python.exe' 'C:\mt5work\ironwall_bridge.py' "$@"
