import json
import os
import sys

from client import run_repomap


def main():
    payload = json.load(sys.stdin)
    map_path = run_repomap("refresh", payload.get("cwd") or os.getcwd())
    if map_path is None:
        return
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "SubagentStart",
                "additionalContext": (
                    f"Symbol map of this repository: {map_path}. "
                    "Search it with grep."
                ),
            }
        },
        sys.stdout,
    )


if __name__ == "__main__":
    main()
