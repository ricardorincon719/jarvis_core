#!/usr/bin/env bash
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TEMPLATE="$REPO_DIR/deploy/systemd/pearl-core.service.in"
SYSTEMD_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
SERVICE_FILE="$SYSTEMD_DIR/pearl-core.service"
PYTHON_BIN="$REPO_DIR/.venv/bin/python"

if [[ ! -x "$PYTHON_BIN" ]]; then
    printf 'No se encontro el virtualenv del Core: %s\n' "$PYTHON_BIN" >&2
    exit 1
fi

mkdir -p "$SYSTEMD_DIR"

sed \
    -e "s|@REPO_DIR@|$REPO_DIR|g" \
    -e "s|@PYTHON_BIN@|$PYTHON_BIN|g" \
    "$TEMPLATE" > "$SERVICE_FILE"

systemctl --user daemon-reload
systemctl --user enable --now pearl-core.service

printf 'PEARL Core instalado: %s\n' "$SERVICE_FILE"
printf 'Estado: systemctl --user status pearl-core.service\n'
printf 'Logs: journalctl --user -u pearl-core.service -f\n'
