"""Runs repomap.py in the plugin virtualenv, for hooks limited to the standard library."""

import os
import subprocess

REPOMAP = os.path.join(os.path.dirname(__file__), "..", "scripts", "repomap.py")
TIMEOUT_SECONDS = 30


def run_repomap(*args):
    data_home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    python = os.path.join(data_home, "shunt-lite", "venv", "bin", "python")
    if not os.path.isfile(python):
        return None
    try:
        result = subprocess.run(
            [python, REPOMAP, *args],
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    output = result.stdout.rstrip()
    return output if result.returncode == 0 and output else None
