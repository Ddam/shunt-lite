"""Builds symbol maps with tree-sitter: a per-file outline and a repository-wide map."""

import json
import os
import re
import subprocess
import sys

import tree_sitter
import tree_sitter_php
import tree_sitter_python
import tree_sitter_ruby
import tree_sitter_rust
import tree_sitter_typescript

CACHE_VERSION = 1
MAX_FILE_BYTES = 1_000_000

GRAMMARS = {
    "php": tree_sitter_php.language_php,
    "python": tree_sitter_python.language,
    "ruby": tree_sitter_ruby.language,
    "rust": tree_sitter_rust.language,
    "tsx": tree_sitter_typescript.language_tsx,
    "typescript": tree_sitter_typescript.language_typescript,
}

EXTENSIONS = {
    ".cjs": "typescript",
    ".cts": "typescript",
    ".js": "typescript",
    ".jsx": "tsx",
    ".mjs": "typescript",
    ".mts": "typescript",
    ".php": "php",
    ".py": "python",
    ".rb": "ruby",
    ".rs": "rust",
    ".svelte": "svelte",
    ".ts": "typescript",
    ".tsx": "tsx",
}

TYPESCRIPT_KINDS = {
    "abstract_class_declaration": "class",
    "class_declaration": "class",
    "enum_declaration": "enum",
    "function_declaration": "function",
    "generator_function_declaration": "function",
    "interface_declaration": "interface",
    "method_definition": "method",
    "type_alias_declaration": "type",
}

KINDS = {
    "php": {
        "class_declaration": "class",
        "enum_declaration": "enum",
        "function_definition": "function",
        "interface_declaration": "interface",
        "method_declaration": "method",
        "trait_declaration": "trait",
    },
    "python": {
        "class_definition": "class",
        "function_definition": "function",
    },
    "ruby": {
        "class": "class",
        "method": "method",
        "module": "module",
        "singleton_method": "method",
    },
    "rust": {
        "const_item": "constant",
        "enum_item": "enum",
        "function_item": "function",
        "impl_item": "impl",
        "macro_definition": "macro",
        "mod_item": "module",
        "static_item": "static",
        "struct_item": "struct",
        "trait_item": "trait",
        "type_item": "type",
    },
    "tsx": TYPESCRIPT_KINDS,
    "typescript": TYPESCRIPT_KINDS,
}

FUNCTION_VALUES = {"arrow_function", "function", "function_expression"}
SECTION_KINDS = {"markup", "script", "style"}
SVELTE_BLOCK = re.compile(r"<(script|style)\b[^>]*>(.*?)</\1>", re.DOTALL)


def node_label(node):
    if node.type == "impl_item":
        target = node.child_by_field_name("type")
        trait = node.child_by_field_name("trait")
        target_text = target.text.decode(errors="replace") if target else "<unknown>"
        if trait:
            return f"{trait.text.decode(errors='replace')} for {target_text}"
        return target_text
    name = node.child_by_field_name("name")
    return name.text.decode(errors="replace") if name else "<anonymous>"


def last_line(node):
    row, column = node.end_point
    return max(node.start_point[0] + 1, row + 1 if column else row)


def function_value(node):
    if node.type != "variable_declarator":
        return False
    value = node.child_by_field_name("value")
    return value is not None and value.type in FUNCTION_VALUES


def parse_symbols(source, grammar, first_line=1, base_depth=0):
    parser = tree_sitter.Parser(tree_sitter.Language(GRAMMARS[grammar]()))
    kinds = KINDS[grammar]
    symbols = []
    stack = [(parser.parse(source).root_node, base_depth)]
    while stack:
        node, depth = stack.pop()
        kind = kinds.get(node.type) if node.is_named else None
        if kind is None and grammar in ("tsx", "typescript") and function_value(node):
            kind = "function"
        child_depth = depth
        if kind is not None:
            symbols.append(
                [
                    depth,
                    kind,
                    node_label(node),
                    node.start_point[0] + first_line,
                    last_line(node) + first_line - 1,
                ]
            )
            child_depth = depth + 1
        stack.extend((child, child_depth) for child in reversed(node.children))
    return symbols


def svelte_symbols(source):
    text = source.decode(errors="replace")

    def line_at(offset):
        return text.count("\n", 0, offset) + 1

    def section(kind, start, end):
        leading = len(text[start:end]) - len(text[start:end].lstrip())
        trailing = len(text[start:end].rstrip())
        return [0, kind, kind, line_at(start + leading), line_at(start + trailing - 1)]

    symbols = []
    position = 0
    for block in SVELTE_BLOCK.finditer(text):
        if text[position : block.start()].strip():
            symbols.append(section("markup", position, block.start()))
        symbols.append(section(block.group(1), block.start(), block.end()))
        if block.group(1) == "script":
            body = block.group(2).encode()
            symbols.extend(parse_symbols(body, "typescript", line_at(block.start(2)), 1))
        position = block.end()
    if text[position:].strip():
        symbols.append(section("markup", position, len(text)))
    return symbols


def file_symbols(path):
    language = EXTENSIONS.get(os.path.splitext(path)[1].lower())
    if language is None:
        return None
    with open(path, "rb") as handle:
        source = handle.read()
    if language == "svelte":
        return svelte_symbols(source)
    return parse_symbols(source, language)


def format_outline(symbols):
    return "\n".join(
        f"{'  ' * depth}{start}-{end} {kind} {name}"
        for depth, kind, name, start, end in symbols
    )


def format_map(path, symbols):
    lines = []
    parents = []
    for depth, kind, name, start, end in symbols:
        del parents[depth:]
        parents.append(None if kind in SECTION_KINDS else name)
        qualified = ".".join(parent for parent in parents if parent)
        lines.append(f"{path}:{start}-{end} {kind} {qualified or name}")
    return lines


def git_output(root, *args):
    return subprocess.run(
        ["git", "-C", root, *args], capture_output=True, text=True, check=True
    ).stdout


def write_atomic(path, content):
    temporary = f"{path}.{os.getpid()}"
    with open(temporary, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(temporary, path)


def load_cache(path):
    try:
        with open(path, encoding="utf-8") as handle:
            cache = json.load(handle)
    except (OSError, ValueError):
        return {}
    return cache.get("files", {}) if cache.get("version") == CACHE_VERSION else {}


def refresh(start):
    root = git_output(start, "rev-parse", "--show-toplevel").strip()
    state_dir = os.path.join(
        root, git_output(root, "rev-parse", "--git-path", "shunt-lite").strip()
    )
    os.makedirs(state_dir, exist_ok=True)
    cache_path = os.path.join(state_dir, "cache.json")
    map_path = os.path.join(state_dir, "map.txt")
    previous = load_cache(cache_path)
    listing = git_output(root, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    current = {}
    lines = []
    for relative in sorted(filter(None, listing.split("\0"))):
        if os.path.splitext(relative)[1].lower() not in EXTENSIONS:
            continue
        path = os.path.join(root, relative)
        try:
            stat = os.stat(path)
        except OSError:
            continue
        if stat.st_size > MAX_FILE_BYTES:
            continue
        entry = previous.get(relative)
        if entry is None or entry["mtime"] != stat.st_mtime_ns or entry["size"] != stat.st_size:
            entry = {
                "mtime": stat.st_mtime_ns,
                "size": stat.st_size,
                "symbols": file_symbols(path),
            }
        current[relative] = entry
        lines.extend(format_map(relative, entry["symbols"]))
    write_atomic(cache_path, json.dumps({"version": CACHE_VERSION, "files": current}))
    write_atomic(map_path, "\n".join(lines) + "\n")
    return map_path


def main():
    command, target = sys.argv[1], sys.argv[2]
    if command == "outline":
        symbols = file_symbols(target)
        if symbols:
            print(format_outline(symbols))
    elif command == "refresh":
        print(refresh(target))
    else:
        sys.exit(f"unknown command: {command}")


if __name__ == "__main__":
    main()
