import json
import os
import shlex
import sys

from client import run_repomap

READ_COMMANDS = {"cat", "head", "tail", "less", "more"}
SHELL_OPERATORS = ("|", ">", "<", ";", "&")
UNREADABLE_AS_TEXT = {".ipynb", ".pdf"}
MAX_OUTLINE_CHARS = 6000
MAP_SUFFIX = os.path.join("shunt-lite", "map.txt")


def threshold():
    raw = os.environ.get("SHUNT_LITE_MIN_LINES", "350")
    return int(raw) if raw.isdigit() else 350


def count_lines(path):
    if os.path.splitext(path)[1].lower() in UNREADABLE_AS_TEXT:
        return None
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError:
        return None
    if b"\0" in data:
        return None
    if not data:
        return 0
    return data.count(b"\n") + (0 if data.endswith(b"\n") else 1)


def deny(reason):
    json.dump(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        },
        sys.stdout,
    )
    sys.exit(0)


def trim_outline(outline):
    if len(outline) <= MAX_OUTLINE_CHARS:
        return outline
    kept = outline[:MAX_OUTLINE_CHARS].rsplit("\n", 1)[0]
    omitted = outline.count("\n") - kept.count("\n")
    return f"{kept}\n... {omitted} more symbols omitted"


def guidance(path, lines, limit):
    header = f"{path} has {lines} lines (limit {limit}), so reading it whole is refused."
    outline = run_repomap("outline", path)
    if outline is None:
        return (
            f"{header} Find the relevant part with grep -n and a symbol or keyword, "
            "then Read only that range with offset and limit."
        )
    return (
        f"{header} Read only the range you need with offset and limit. "
        f"Outline (start-end kind name):\n{trim_outline(outline)}\n"
        "If this does not show where to look, use grep -n or the shunt-lite:locator agent."
    )


def check_path(path):
    limit = threshold()
    lines = count_lines(path)
    if lines is not None and lines > limit:
        deny(guidance(path, lines, limit))


def check_read(tool_input):
    path = tool_input.get("file_path")
    if path and path.endswith(MAP_SUFFIX):
        deny(f"Do not Read the symbol map. Search it with grep: grep -iE 'keyword|other' {path}")
    if tool_input.get("offset") is not None or tool_input.get("limit") is not None:
        return
    if path and os.path.isfile(path):
        check_path(path)


def check_bash(command, cwd):
    if any(op in command for op in SHELL_OPERATORS):
        return
    try:
        tokens = shlex.split(command)
    except ValueError:
        return
    if not tokens or tokens[0] not in READ_COMMANDS:
        return
    files = [token for token in tokens[1:] if not token.startswith("-")]
    if len(files) != len(tokens) - 1:
        return
    for token in files:
        path = os.path.join(cwd, token)
        if os.path.isfile(path):
            check_path(path)


def main():
    payload = json.load(sys.stdin)
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input") or {}
    if tool_name == "Read":
        check_read(tool_input)
    elif tool_name == "Bash":
        check_bash(tool_input.get("command", ""), payload.get("cwd") or os.getcwd())


if __name__ == "__main__":
    main()
