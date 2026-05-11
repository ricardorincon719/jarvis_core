#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="${JARVIS_CORE_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
BASHRC="${HOME}/.bashrc"
START_MARKER="# PEARL_CORE_AUTOSTART_START"
END_MARKER="# PEARL_CORE_AUTOSTART_END"

mkdir -p "$(dirname "$BASHRC")"
touch "$BASHRC"

backup="${BASHRC}.pearl.bak.$(date +%Y%m%d%H%M%S)"
cp "$BASHRC" "$backup"

tmp_file="$(mktemp)"
awk -v start="$START_MARKER" -v end="$END_MARKER" '
    $0 == start { skip = 1; next }
    $0 == end { skip = 0; next }
    !skip { print }
' "$BASHRC" > "$tmp_file"

cat >> "$tmp_file" <<EOF

$START_MARKER
if [ -n "\${PS1:-}" ] && [ -x "$ROOT_DIR/scripts/start_core_if_needed_termux.sh" ]; then
    "$ROOT_DIR/scripts/start_core_if_needed_termux.sh" >/dev/null 2>&1
fi
$END_MARKER
EOF

mv "$tmp_file" "$BASHRC"

echo "Autoinicio instalado en $BASHRC"
echo "Backup: $backup"
echo "PEARL iniciara cuando abras una nueva sesion de Termux."
