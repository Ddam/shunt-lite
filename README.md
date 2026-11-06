# shunt-lite

A Claude Code plugin that saves tokens on large files, with no external service.

- **Refusal**: a full `Read` of a file over 350 lines is refused, as are bare `cat`, `head`, `tail`, `less` and `more`. The refusal carries the file outline (symbols with their line ranges), so Claude can read just the right range. It also says how to read the whole file when the task needs it (code review, full analysis), and asks Claude to say what it left unread.
- **Repository map**: a tree-sitter map of every symbol, kept in `.git/shunt-lite/map.txt` and updated incrementally.
- **Locator**: the `shunt-lite:locator` subagent runs on Haiku, searches that map and returns `file:start-end` ranges.

Outlines cover Rust, TypeScript, JavaScript, Svelte, PHP, Python and Ruby. Other file types are refused with a pointer to `grep`.

## Setup

```bash
sh scripts/setup.sh
```

This creates the virtualenv in `~/.local/share/shunt-lite/venv`. Without it the refusal still works, but with no outline and no map. Run it again after a Python upgrade.

Install from this directory, for yourself in one project:

```bash
claude plugin marketplace add /path/to/shunt-lite
claude plugin install shunt-lite@shunt-lite --scope local
```

## Updating

Claude Code runs a copy of the plugin, not this directory. After a change, bump `version` in `.claude-plugin/plugin.json`, then:

```bash
claude plugin marketplace update shunt-lite
claude plugin update shunt-lite@shunt-lite --scope local
```

## Configuration

`SHUNT_LITE_MIN_LINES` (default `350`): line count above which a full read is refused.

## Limits

- The Bash check covers a single command: `cd x && cat big.txt` passes.
- The map needs a git repository. Outlines do not.
- The map is refreshed when the locator starts, so it does not cover edits made while it runs.
- Files over 1 MB are left out of the map.

## Tests

```bash
python3 -m unittest tests/test_guard.py
~/.local/share/shunt-lite/venv/bin/python -m unittest tests/test_repomap.py
```
