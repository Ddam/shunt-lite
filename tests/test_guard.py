import json
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.join(os.path.dirname(__file__), "..")
GUARD = os.path.join(ROOT, "hooks", "guard.py")


class GuardTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = self.temp.name
        self.big = self.write("big.txt", "line\n" * 400)
        self.small = self.write("small.txt", "line\n" * 10)

    def write(self, name, content):
        path = os.path.join(self.dir, name)
        with open(path, "wb") as handle:
            handle.write(content if isinstance(content, bytes) else content.encode())
        return path

    def run_guard(self, payload, **env):
        result = subprocess.run(
            [sys.executable, GUARD],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            env={**os.environ, "XDG_DATA_HOME": self.dir, **env},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout) if result.stdout else None

    def read(self, path, **extra):
        return self.run_guard(
            {"tool_name": "Read", "tool_input": {"file_path": path, **extra}}
        )

    def bash(self, command):
        return self.run_guard(
            {"tool_name": "Bash", "cwd": self.dir, "tool_input": {"command": command}}
        )

    def assertDenied(self, output):
        self.assertIsNotNone(output)
        self.assertEqual(output["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_full_read_of_a_large_file_is_denied(self):
        self.assertDenied(self.read(self.big))

    def test_ranged_reads_are_allowed(self):
        self.assertIsNone(self.read(self.big, offset=10, limit=20))
        self.assertIsNone(self.read(self.big, offset=0))
        self.assertIsNone(self.read(self.big, limit=20))

    def test_small_and_missing_files_are_allowed(self):
        self.assertIsNone(self.read(self.small))
        self.assertIsNone(self.read(os.path.join(self.dir, "missing.txt")))

    def test_binary_files_are_allowed(self):
        png = self.write("shot.png", b"\x89PNG\x00" + b"\n" * 1000)
        self.assertIsNone(self.read(png))

    def test_pdf_and_notebooks_are_allowed(self):
        self.assertIsNone(self.read(self.write("doc.pdf", "line\n" * 1000)))
        self.assertIsNone(self.read(self.write("nb.ipynb", "line\n" * 1000)))

    def test_the_symbol_map_cannot_be_read_even_by_range(self):
        path = os.path.join(self.dir, ".git", "shunt-lite", "map.txt")
        self.assertDenied(self.read(path))
        self.assertDenied(self.read(path, offset=100, limit=200))

    def test_threshold_is_configurable(self):
        output = self.run_guard(
            {"tool_name": "Read", "tool_input": {"file_path": self.big}},
            SHUNT_LITE_MIN_LINES="1000",
        )
        self.assertIsNone(output)

    def test_bash_full_reads_are_denied(self):
        self.assertDenied(self.bash(f"cat {self.big}"))
        self.assertDenied(self.bash("cat big.txt"))

    def test_bash_targeted_reads_are_allowed(self):
        self.assertIsNone(self.bash(f"head -n 20 {self.big}"))
        self.assertIsNone(self.bash(f"cat {self.big} | grep line"))
        self.assertIsNone(self.bash(f"cat {self.big} > /dev/null"))
        self.assertIsNone(self.bash(f"cat {self.small}"))
        self.assertIsNone(self.bash("git status"))

    def test_without_the_environment_the_guidance_falls_back_to_grep(self):
        reason = self.read(self.big)["hookSpecificOutput"]["permissionDecisionReason"]
        self.assertIn("grep -n", reason)
        self.assertNotIn("Outline", reason)


if __name__ == "__main__":
    unittest.main()
