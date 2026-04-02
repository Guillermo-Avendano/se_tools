#!/bin/bash
set -e

# ── Shared init: truststores + application YAML per repo ──
/app/worker/init_conf.sh

if [ -n "$WORKER" ]; then
    echo "Starting worker: $WORKER"
    exec python3 /app/worker/worker.py
else
    echo "Starting se-ce-tools (frontend + backend)"
    exec supervisord -c /etc/supervisor/supervisord.conf
fi
