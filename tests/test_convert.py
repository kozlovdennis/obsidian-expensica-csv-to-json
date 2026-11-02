import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from convert import main


class ConvertCommandTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.pairs = []
        for name in ("debit", "credit", "saving"):
            source = self.root / f"{name}.csv"
            source.write_text(f"2026-10-01,Original {name} description,100,\n", encoding="utf-8")
            self.pairs.append((source, self.root / f"{name}.json"))
        self.arguments = [str(path) for pair in self.pairs for path in pair]

    def run_command(self, arguments):
        output = io.StringIO()
        with patch("sys.argv", ["convert.py", *arguments]), contextlib.redirect_stdout(output):
            self.assertEqual(main(), 0)
        return output.getvalue()

    def test_three_pairs_write_separate_outputs_in_order(self):
        log = self.run_command([*self.arguments, "--pretty"])
        lines = log.splitlines()
        self.assertEqual(len(lines), 3)
        for index, (source, destination) in enumerate(self.pairs):
            payload = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(len(payload["transactions"]), 1)
            self.assertEqual(payload["transactions"][0]["description"], f"Original {source.stem} description")
            self.assertIn(str(destination), lines[index])
            self.assertIn('\n  "transactions"', destination.read_text(encoding="utf-8"))

    def test_single_input_uses_default_output(self):
        source, destination = self.pairs[0]
        with patch("convert.default_output_path", return_value=destination):
            self.run_command([str(source)])
        self.assertTrue(destination.exists())

    def test_incomplete_pairs_rejected_before_writing(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            self.run_command(self.arguments[:-1])
        self.assertEqual(error.exception.code, 2)
        self.assertFalse(any(destination.exists() for _, destination in self.pairs))

    def test_dry_run_prints_each_payload_without_writes_or_prompts(self):
        destination = self.pairs[0][1]
        destination.write_text("existing data", encoding="utf-8")
        with patch("builtins.input", side_effect=AssertionError("Unexpected overwrite prompt")):
            log = self.run_command([*self.arguments, "--dry-run"])
        payloads = [json.loads(line) for line in log.splitlines()]
        self.assertEqual(
            [payload["transactions"][0]["description"] for payload in payloads],
            [f"Original {source.stem} description" for source, _ in self.pairs],
        )
        self.assertEqual(destination.read_text(encoding="utf-8"), "existing data")
        self.assertFalse(any(path.exists() for _, path in self.pairs[1:]))

    def test_overwrite_choice_is_applied_to_each_pair(self):
        first, second = self.pairs[0][1], self.pairs[1][1]
        for destination in (first, second):
            destination.write_text("existing data", encoding="utf-8")
        with patch("builtins.input", side_effect=["n", "o"]) as prompt:
            self.run_command(self.arguments)
        self.assertEqual(prompt.call_count, 2)
        self.assertEqual(first.read_text(encoding="utf-8"), "existing data")
        self.assertTrue(first.with_stem(first.stem + "_1").exists())
        self.assertEqual(json.loads(second.read_text(encoding="utf-8"))["transactions"][0]["description"],
                         "Original credit description")

    def test_failure_stops_after_previously_completed_files(self):
        arguments = self.arguments.copy()
        arguments[2] = str(self.root / "missing.csv")
        with self.assertRaises(FileNotFoundError):
            self.run_command(arguments)
        self.assertTrue(self.pairs[0][1].exists())
        self.assertFalse(any(destination.exists() for _, destination in self.pairs[1:]))


if __name__ == "__main__":
    unittest.main()
