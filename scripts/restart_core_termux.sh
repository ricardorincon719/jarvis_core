#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${JARVIS_CORE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_FILE="${JARVIS_CORE_LOG:-$ROOT_DIR/core.log}"

cd "$ROOT_DIR"

mapfile -t pids < <(pgrep -f "python.*core.py" || true)
for pid in "${pids[@]}"; do
    if [[ "$pid" != "$$" ]]; then
        kill "$pid" 2>/dev/null || true
    fi
done

sleep 1

mapfile -t remaining < <(pgrep -f "python.*core.py" || true)
for pid in "${remaining[@]}"; do
    if [[ "$pid" != "$$" ]]; then
        kill -9 "$pid" 2>/dev/null || true
    fi
done

nohup python core.py >> "$LOG_FILE" 2>&1 &
new_pid="$!"

echo "JARVIS CORE reiniciado"
echo "PID: $new_pid"
echo "Log: $LOG_FILE"
