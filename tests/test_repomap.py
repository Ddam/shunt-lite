import os
import subprocess
import sys
import tempfile
import textwrap
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import repomap


def names(symbols):
    return [(kind, name) for _, kind, name, _, _ in symbols]


class TempFiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = self.temp.name

    def write(self, name, content):
        path = os.path.join(self.dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(textwrap.dedent(content).lstrip("\n"))
        return path


class SymbolsTest(TempFiles):
    def test_rust(self):
        path = self.write(
            "a.rs",
            """
            struct Foo;

            impl Display for Foo {
                fn fmt(&self) {
                    work();
                }
            }
            """,
        )
        symbols = repomap.file_symbols(path)
        self.assertEqual(
            symbols,
            [
                [0, "struct", "Foo", 1, 1],
                [0, "impl", "Display for Foo", 3, 7],
                [1, "function", "fmt", 4, 6],
            ],
        )

    def test_typescript_arrow_functions_are_symbols(self):
        path = self.write(
            "a.ts",
            """
            export const list = () => 1;
            export const size = 3;
            export function make() {
              return 1;
            }
            """,
        )
        self.assertEqual(
            names(repomap.file_symbols(path)), [("function", "list"), ("function", "make")]
        )

    def test_tsx(self):
        path = self.write("a.tsx", "export function Page() {\n  return <div />;\n}\n")
        self.assertEqual(repomap.file_symbols(path), [[0, "function", "Page", 1, 3]])

    def test_php(self):
        path = self.write(
            "a.php",
            """
            <?php
            use App\\Entity\\User;

            class Service
            {
                public function run(): void
                {
                }
            }
            """,
        )
        self.assertEqual(
            repomap.file_symbols(path),
            [[0, "class", "Service", 4, 9], [1, "method", "run", 6, 8]],
        )

    def test_python_block_ends_on_its_last_line(self):
        path = self.write("a.py", "def run():\n    return 1\n\n\nvalue = 2\n")
        self.assertEqual(repomap.file_symbols(path), [[0, "function", "run", 1, 2]])

    def test_ruby(self):
        path = self.write(
            "a.rb",
            """
            class Service
              def run
              end
            end
            """,
        )
        self.assertEqual(
            repomap.file_symbols(path),
            [[0, "class", "Service", 1, 4], [1, "method", "run", 2, 3]],
        )

    def test_svelte_maps_every_section_with_file_line_numbers(self):
        path = self.write(
            "a.svelte",
            """
            <script module lang="ts">
              export const first = () => 1;
            </script>

            <script lang="ts">
              function second() {
                return 2;
              }
            </script>

            <div>
              text
            </div>

            <style>
              div { color: red; }
            </style>
            """,
        )
        self.assertEqual(
            repomap.file_symbols(path),
            [
                [0, "script", "script", 1, 3],
                [1, "function", "first", 2, 2],
                [0, "script", "script", 5, 9],
                [1, "function", "second", 6, 8],
                [0, "markup", "markup", 11, 13],
                [0, "style", "style", 15, 17],
            ],
        )

    def test_unsupported_extension_has_no_symbols(self):
        self.assertIsNone(repomap.file_symbols(self.write("a.toml", "a = 1\n")))


class FormatTest(unittest.TestCase):
    SYMBOLS = [
        [0, "script", "script", 1, 9],
        [1, "class", "Foo", 2, 8],
        [2, "method", "bar", 3, 4],
        [0, "function", "baz", 10, 12],
    ]

    def test_outline_indents_by_depth(self):
        self.assertEqual(
            repomap.format_outline(self.SYMBOLS),
            "1-9 script script\n  2-8 class Foo\n    3-4 method bar\n10-12 function baz",
        )

    def test_map_qualifies_names_and_skips_sections(self):
        self.assertEqual(
            repomap.format_map("a.svelte", self.SYMBOLS),
            [
                "a.svelte:1-9 script script",
                "a.svelte:2-8 class Foo",
                "a.svelte:3-4 method Foo.bar",
                "a.svelte:10-12 function baz",
            ],
        )


class RefreshTest(TempFiles):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q", self.dir], check=True)
        self.write(".gitignore", "ignored.rs\n")
        self.write("src/a.rs", "fn one() {}\n")
        self.write("ignored.rs", "fn hidden() {}\n")
        self.write("notes.toml", "a = 1\n")

    def read_map(self):
        with open(repomap.refresh(self.dir), encoding="utf-8") as handle:
            return handle.read().splitlines()

    def test_map_lists_untracked_files_and_respects_gitignore(self):
        self.assertEqual(self.read_map(), ["src/a.rs:1-1 function one"])

    def test_map_lives_inside_git_metadata(self):
        self.assertTrue(
            repomap.refresh(self.dir).startswith(os.path.join(self.dir, ".git", ""))
        )

    def test_unchanged_files_are_not_parsed_again(self):
        self.read_map()
        original = repomap.file_symbols
        repomap.file_symbols = lambda path: self.fail(f"parsed again: {path}")
        self.addCleanup(setattr, repomap, "file_symbols", original)
        self.assertEqual(self.read_map(), ["src/a.rs:1-1 function one"])

    def test_changed_and_deleted_files_are_picked_up(self):
        self.read_map()
        self.write("src/a.rs", "// one\n// two\nfn moved() {}\n")
        self.write("src/b.rs", "fn two() {}\n")
        self.assertEqual(
            self.read_map(),
            ["src/a.rs:3-3 function moved", "src/b.rs:1-1 function two"],
        )
        os.remove(os.path.join(self.dir, "src", "b.rs"))
        self.assertEqual(self.read_map(), ["src/a.rs:3-3 function moved"])


if __name__ == "__main__":
    unittest.main()
