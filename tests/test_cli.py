"""Tests for the ``gtmkit`` front door and ``gtmkit init``.

The front door must add nothing to an analysis: the same arguments reach the
same ``main()`` whichever spelling a user types. These tests pin that, plus
the promises ``gtmkit init`` makes to someone who installed with pip and has
no clone: the starter is exactly the shipped example, it validates as
printed, and it never overwrites a file somebody has been editing.
"""

import contextlib
import importlib
import io
import os
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from gtmkit import __version__, cli, qualify, sizing, valuecase
from tools import validate_skills

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NORTHWIND = os.path.join(
    REPO_ROOT, "examples", "value-case", "northwind-support-deflection.json"
)
ANALYSIS_NAMES = [name for name, _, _ in cli.ANALYSES]
KINDS = [kind for kind, _, _, _ in cli.STARTERS]


def run(argv):
    """Run the front door in-process; return (exit code, stdout, stderr)."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = cli.main(argv)
        except SystemExit as exc:  # argparse exits on usage errors and --help
            code = exc.code
    return code, out.getvalue(), err.getvalue()


def run_module(*args):
    """Run ``python -m ...`` from the repository root, as a user would."""
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


class TestListing(unittest.TestCase):
    def test_no_arguments_lists_every_analysis_with_an_example(self):
        code, out, _ = run([])
        self.assertEqual(code, 0)
        for name, summary, example in cli.ANALYSES:
            with self.subTest(analysis=name):
                self.assertIn(summary, out)
                self.assertIn("gtmkit %s %s" % (name, example), out)
        self.assertIn("gtmkit init value-case", out)

    def test_help_is_the_same_listing(self):
        self.assertEqual(run(["--help"]), run([]))
        self.assertEqual(run(["-h"]), run([]))

    def test_the_analyses_are_exactly_the_runnable_modules(self):
        self.assertEqual(
            sorted(ANALYSIS_NAMES),
            [
                "funnel",
                "pipeline",
                "pricing",
                "qualify",
                "scoring",
                "sizing",
                "valuecase",
            ],
        )
        for name in ANALYSIS_NAMES:
            with self.subTest(analysis=name):
                self.assertTrue(validate_skills.module_is_runnable(name))

    def test_every_listed_example_uses_flags_the_analysis_accepts(self):
        for name, _, example in cli.ANALYSES:
            with self.subTest(analysis=name):
                command = "gtmkit %s %s" % (name, example)
                self.assertEqual(validate_skills.command_problems(command), [])

    def test_version(self):
        self.assertEqual(run(["--version"]), (0, "gtmkit %s\n" % __version__, ""))
        self.assertEqual(run(["-V"])[1], "gtmkit %s\n" % __version__)


class TestDispatch(unittest.TestCase):
    def test_remaining_arguments_reach_main_unchanged(self):
        argv = ["my case.json", "--format", "json", "--out", "x y.md", "--"]
        for name in ANALYSIS_NAMES:
            module = importlib.import_module("gtmkit.%s" % name)
            with (
                self.subTest(analysis=name),
                mock.patch.object(module, "main", return_value=0) as fake,
            ):
                self.assertEqual(run([name, *argv])[0], 0)
                fake.assert_called_once_with(argv)

    def test_exit_code_comes_from_the_analysis(self):
        with mock.patch.object(valuecase, "main", return_value=2):
            self.assertEqual(run(["valuecase", "x.json"])[0], 2)
        with mock.patch.object(valuecase, "main", return_value=None):
            self.assertEqual(run(["valuecase", "x.json"])[0], 0)

    def test_real_dispatch_runs_the_analysis(self):
        code, out, _ = run(["valuecase", NORTHWIND, "--check"])
        self.assertEqual(code, 0)
        self.assertIn("is valid: 3 driver(s), 3 cost line(s)", out)

    def test_analysis_usage_errors_keep_their_exit_code(self):
        self.assertEqual(run(["sizing", "--no-such-flag"])[0], 2)

    def test_unknown_analysis_exits_2_with_the_valid_names(self):
        code, out, err = run(["valuecas", "case.json"])
        self.assertEqual(code, 2)
        self.assertEqual(out, "")
        self.assertIn("unknown analysis 'valuecas'", err)
        self.assertIn("Did you mean 'valuecase'?", err)
        for name in ANALYSIS_NAMES:
            self.assertIn(name, err)

    def test_an_option_in_place_of_the_analysis_exits_2(self):
        code, _, err = run(["--format", "json"])
        self.assertEqual(code, 2)
        self.assertIn("expected an analysis name first", err)

    def test_python_dash_m_gtmkit_is_the_front_door(self):
        result = run_module("-m", "gtmkit", "--version")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.decode().strip(), "gtmkit %s" % __version__)

    def test_modules_still_run_directly(self):
        result = run_module("-m", "gtmkit.valuecase", NORTHWIND, "--check")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(b"is valid", result.stdout)


class TestInit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def path(self, name):
        return os.path.join(self.tmp.name, name)

    def test_prints_each_starter_exactly(self):
        for kind in KINDS:
            with self.subTest(kind=kind):
                code, out, err = run(["init", kind])
                self.assertEqual((code, err), (0, ""))
                self.assertEqual(out, cli.starter_bytes(kind).decode("utf-8"))

    def test_stdout_carries_the_exact_bytes(self):
        result = run_module("-m", "gtmkit", "init", "value-case")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, cli.starter_bytes("value-case"))

    def test_out_writes_the_file_and_names_the_next_command(self):
        target = self.path("case.json")
        code, out, err = run(["init", "value-case", "--out", target])
        self.assertEqual((code, out), (0, ""))
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), cli.starter_bytes("value-case"))
        self.assertIn("gtmkit valuecase", err)

    def test_refuses_to_overwrite_without_force(self):
        target = self.path("case.json")
        with open(target, "w", encoding="utf-8") as handle:
            handle.write("my edits")
        code, _, err = run(["init", "value-case", "--out", target])
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertIn("--force", err)
        with open(target, encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "my edits")

        code, _, _ = run(["init", "value-case", "--out", target, "--force"])
        self.assertEqual(code, 0)
        with open(target, "rb") as handle:
            self.assertEqual(handle.read(), cli.starter_bytes("value-case"))

    def test_unwritable_destination_is_reported(self):
        code, _, err = run(["init", "deal", "--out", self.tmp.name, "--force"])
        self.assertEqual(code, 1)
        self.assertIn("cannot write", err)

    def test_unknown_or_missing_kind_is_a_usage_error(self):
        self.assertEqual(run(["init", "pricing"])[0], 2)
        self.assertEqual(run(["init"])[0], 2)

    def test_value_case_starter_passes_check(self):
        target = self.path("case.json")
        self.assertEqual(run(["init", "value-case", "--out", target])[0], 0)
        code, out, _ = run(["valuecase", target, "--check"])
        self.assertEqual(code, 0)
        self.assertIn("is valid", out)

    def test_deal_starter_runs(self):
        target = self.path("deal.json")
        self.assertEqual(run(["init", "deal", "--out", target])[0], 0)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(qualify.main([target]), 0)
        self.assertIn("## Verdict", out.getvalue())

    def test_sizing_starter_runs(self):
        target = self.path("market.json")
        self.assertEqual(run(["init", "sizing", "--out", target])[0], 0)
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(sizing.main(["--spec", target]), 0)
        self.assertTrue(out.getvalue().strip())


def example(*parts):
    return os.path.join(REPO_ROOT, "examples", *parts)


# Arguments that make each analysis with an --out option produce output.
WRITERS = {
    "valuecase": [NORTHWIND],
    "scoring": [
        "--rubric",
        example("icp", "rubric.json"),
        "--records",
        example("icp", "accounts.csv"),
    ],
    "sizing": ["--spec", example("sizing", "agent-observability-na.json")],
    "pricing": ["--responses", example("pricing", "responses.csv")],
    "qualify": [example("deal", "kestrel-expansion.json")],
    "pipeline": [
        example("pipeline", "pipeline.csv"),
        "--stages",
        example("pipeline", "stages.json"),
        "--target",
        "1200000",
        "--as-of",
        "2026-10-06",
    ],
}


class TestOut(unittest.TestCase):
    """Every --out reports a file it cannot write; none raises a traceback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def test_every_analysis_with_out_is_covered(self):
        with_out = [
            name
            for name in ANALYSIS_NAMES
            if "--out" in (validate_skills.module_flags(name) or ())
        ]
        self.assertEqual(sorted(with_out), sorted(WRITERS))

    def test_a_missing_directory_is_one_line_and_exit_1(self):
        for name, args in WRITERS.items():
            target = os.path.join(self.tmp.name, "missing", "%s.out" % name)
            with self.subTest(analysis=name):
                code, out, err = run([name, *args, "--out", target])
                self.assertEqual(code, 1)
                self.assertEqual(out, "")
                self.assertEqual(
                    err, "error: cannot write %s: No such file or directory\n" % target
                )
                self.assertFalse(os.path.exists(target))

    def test_writes_the_file_and_says_where(self):
        for name, args in WRITERS.items():
            target = os.path.join(self.tmp.name, "%s.out" % name)
            with self.subTest(analysis=name):
                code, out, err = run([name, *args, "--out", target])
                self.assertEqual((code, out, err), (0, "", "wrote %s\n" % target))
                with open(target, encoding="utf-8") as handle:
                    self.assertTrue(handle.read().strip())

    def test_emit_prints_without_a_destination(self):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(cli.emit("text", None), 0)
        self.assertEqual(out.getvalue(), "text\n")


if __name__ == "__main__":
    unittest.main()
