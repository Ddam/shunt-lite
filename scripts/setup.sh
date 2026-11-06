#!/bin/sh
set -eu

root=$(cd "$(dirname "$0")/.." && pwd)
venv="${XDG_DATA_HOME:-$HOME/.local/share}/shunt-lite/venv"

python3 -m venv "$venv"
"$venv/bin/pip" install --quiet --disable-pip-version-check -r "$root/scripts/requirements.txt"
echo "shunt-lite environment ready: $venv"
