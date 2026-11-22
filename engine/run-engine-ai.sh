#!/bin/bash
cd /home/ubuntu/web/Traderwatch-repo/engine
set -a
source mt5-pending.env
set +a
/usr/bin/python3 /home/ubuntu/web/Traderwatch-repo/engine/signal-engine-ai.py &
/usr/bin/python3 /home/ubuntu/web/Traderwatch-repo/engine/mt5-pending.py &
wait
