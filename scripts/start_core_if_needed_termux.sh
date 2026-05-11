#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${JARVIS_CORE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_FILE="${JARVIS_CORE_LOG:-$ROOT_DIR/core.log}"

cd "$ROOT_DIR"

if pgrep -f "python.*core.py" >/dev/null 2>&1; then
    echo "JARVIS CORE ya esta corriendo"
    exit 0
fi

nohup python core.py >> "$LOG_FILE" 2>&1 &
new_pid="$!"

echo "JARVIS CORE iniciado"
echo "PID: $new_pid"
echo "Log: $LOG_FILE"
