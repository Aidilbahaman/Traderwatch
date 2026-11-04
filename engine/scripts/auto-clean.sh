#!/bin/bash
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Auto-clean started"
if [ -f /home/ubuntu/web/Traderwatch-repo/logs/mt5-pending-live.log ]; then
    tail -n 50 /home/ubuntu/web/Traderwatch-repo/logs/mt5-pending-live.log > /tmp/mt5-log-temp.log
    mv /tmp/mt5-log-temp.log /home/ubuntu/web/Traderwatch-repo/logs/mt5-pending-live.log
fi
rm -f /tmp/sq-collector.lock
find /home/ubuntu/web/Traderwatch-repo/logs/ -type f -name '*.log.*' -mtime +7 -delete 2>/dev/null || true
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Auto-clean finished"
