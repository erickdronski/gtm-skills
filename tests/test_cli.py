"""Tests for the ``gtmkit`` front door and ``gtmkit init``.

The front door must add nothing to an analysis: the same arguments reach the
same ``main()`` whichever spelling a user types. These tests pin that, plus
the promises ``gtmkit init`` makes to someone who installed with pip and has
no clone: the starter is exactly the shipped example, it validates as
printed, and it never overwrites a file somebody has been editing.
"""

import contextlib
import errno
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
                fake.assert_called_once_with(argv, prog="gtmkit %s" % name)

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


class TestUsageNames(unittest.TestCase):
    """Usage and errors name the command the user typed, however they typed it."""

    def test_help_names_the_front_door_command(self):
        for name in ANALYSIS_NAMES:
            with self.subTest(analysis=name):
                code, out, _ = run([name, "--help"])
                self.assertEqual(code, 0)
                self.assertTrue(out.startswith("usage: gtmkit %s " % name), out)
                self.assertNotIn("python3 -m", out.split("\n\n", 1)[0])

    def test_a_usage_error_names_the_front_door_command(self):
        code, _, err = run(["valuecase"])
        self.assertEqual(code, 2)
        self.assertTrue(err.startswith("usage: gtmkit valuecase "), err)
        self.assertIn("gtmkit valuecase: error: the following arguments", err)
        self.assertEqual(
            run(["init", "--help"])[1].split(" [", 1)[0], "usage: gtmkit init"
        )

    def test_python_dash_m_gtmkit_names_itself(self):
        for args in (("valuecase", "--help"), ("init", "--help")):
            with self.subTest(args=args):
                result = run_module("-m", "gtmkit", *args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(
                    result.stdout.startswith(
                        ("usage: python3 -m gtmkit %s " % args[0]).encode()
                    ),
                    result.stdout,
                )

    def test_python_dash_m_gtmkit_names_itself_in_its_own_messages(self):
        """The listing and the unknown-analysis error are the front door's own
        text, not argparse's, and must name the command as typed too."""
        listing = run_module("-m", "gtmkit").stdout.decode()
        self.assertIn("usage: python3 -m gtmkit <analysis> [arguments...]", listing)
        self.assertIn("       python3 -m gtmkit init <kind>", listing)
        self.assertIn("e.g. python3 -m gtmkit valuecase case.json", listing)
        self.assertIn("python3 -m gtmkit <analysis> --help", listing)
        self.assertNotRegex(
            listing.replace("python3 -m gtmkit", ""),
            r"\bgtmkit (<|init|valuecase|--version)",
        )
        result = run_module("-m", "gtmkit", "valuecas", "case.json")
        self.assertEqual(result.returncode, 2)
        self.assertTrue(
            result.stderr.startswith(b"python3 -m gtmkit: unknown analysis"),
            result.stderr,
        )

    def test_init_from_a_clone_names_a_command_the_clone_can_run(self):
        """`python3 -m gtmkit init` used to say "then run: gtmkit qualify",
        which a clone without pip does not have."""
        env = dict(os.environ, PYTHONPATH=REPO_ROOT)

        def lines(raw):
            # Windows writes "\r\n" to a piped stderr; compare the text.
            return raw.decode().replace("\r\n", "\n")

        with tempfile.TemporaryDirectory() as work:

            def python(*args):
                return subprocess.run(
                    [sys.executable, *args],
                    cwd=work,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    check=False,
                )

            told = {
                "value-case": "python3 -m gtmkit valuecase case.json --check",
                "deal": "python3 -m gtmkit qualify deal.json",
                "sizing": "python3 -m gtmkit sizing --spec sizing.json",
            }
            for kind, command in told.items():
                with self.subTest(kind=kind):
                    out = command.split()[-2 if kind == "value-case" else -1]
                    result = python("-m", "gtmkit", "init", kind, "--out", out)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(
                        lines(result.stderr),
                        "wrote %s. Edit it, then run: %s\n" % (out, command),
                    )
                    # The suggestion runs, spelled with this interpreter.
                    ran = python(*command.split()[1:])
                    self.assertEqual(ran.returncode, 0, ran.stderr)
                    again = python("-m", "gtmkit", "init", kind, "--out", out)
                    self.assertEqual(
                        lines(again.stderr),
                        "python3 -m gtmkit init: %s already exists; pass --force "
                        "to overwrite it\n" % out,
                    )
            directory = python("-m", "gtmkit", "init", "deal", "--out", ".")
            self.assertTrue(
                directory.stderr.startswith(b"python3 -m gtmkit init: cannot write ."),
                directory.stderr,
            )
            epilog = python("-m", "gtmkit", "init", "--help").stdout.decode()
            self.assertIn("for `python3 -m gtmkit qualify`", epilog)

    def test_a_module_run_directly_keeps_its_own_name(self):
        result = run_module("-m", "gtmkit.valuecase", "--help")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(
            result.stdout.startswith(b"usage: python3 -m gtmkit.valuecase ")
        )


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

    def test_a_directory_is_refused_without_offering_force(self):
        """--force cannot write over a directory, so it must not be suggested."""
        expected = "gtmkit init: cannot write %s: %s\n" % (
            self.tmp.name,
            os.strerror(errno.EISDIR),
        )
        for extra in ([], ["--force"]):
            with self.subTest(extra=extra):
                code, out, err = run(["init", "sizing", "--out", self.tmp.name, *extra])
                self.assertEqual((code, out, err), (1, "", expected))

    def test_a_missing_folder_reads_like_the_analyses_out_error(self):
        target = self.path(os.path.join("missing", "deal.json"))
        code, _, err = run(["init", "deal", "--out", target])
        self.assertEqual(code, 1)
        self.assertEqual(
            err, "gtmkit init: cannot write %s: No such file or directory\n" % target
        )

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


class TestUnreadableInput(unittest.TestCase):
    """An input file that is not UTF-8, or not a file at all, is one line and
    exit 2 in every analysis, as in valuecase, never a traceback."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def utf16(self, *parts):
        """A copy of an example file as PowerShell 5's ``>`` writes it."""
        target = os.path.join(self.tmp.name, "utf16-" + parts[-1])
        with open(example(*parts), encoding="utf-8") as handle:
            text = handle.read()
        with open(target, "w", encoding="utf-16") as handle:
            handle.write(text)
        return target

    def cases(self, bad):
        """Each analysis's arguments with one input replaced by ``bad``(kind)."""
        rubric = example("icp", "rubric.json")
        accounts = example("icp", "accounts.csv")
        stages = example("pipeline", "stages.json")
        deals = example("pipeline", "pipeline.csv")
        meddpicc = os.path.join(
            REPO_ROOT, "skills", "deal-qualification", "assets", "meddpicc-rubric.json"
        )
        return {
            "valuecase spec": [
                "valuecase",
                bad("value-case", "northwind-support-deflection.json"),
            ],
            "qualify deal": ["qualify", bad("deal", "kestrel-expansion.json")],
            "qualify --rubric": [
                "qualify",
                example("deal", "kestrel-expansion.json"),
                "--rubric",
                bad(meddpicc),
            ],
            "sizing --spec": [
                "sizing",
                "--spec",
                bad("sizing", "agent-observability-na.json"),
            ],
            "pricing --responses": [
                "pricing",
                "--responses",
                bad("pricing", "responses.csv"),
            ],
            "scoring --rubric": [
                "scoring",
                "--rubric",
                bad("icp", "rubric.json"),
                "--records",
                accounts,
            ],
            "scoring --records": [
                "scoring",
                "--rubric",
                rubric,
                "--records",
                bad("icp", "accounts.csv"),
            ],
            "pipeline records": [
                "pipeline",
                bad("pipeline", "pipeline.csv"),
                "--stages",
                stages,
            ],
            "pipeline --stages": [
                "pipeline",
                deals,
                "--stages",
                bad("pipeline", "stages.json"),
            ],
        }

    def assert_one_line(self, argv, expected):
        code, out, err = run(argv)
        self.assertEqual((code, out), (2, ""), err)
        self.assertEqual(err.count("\n"), 1, err)
        self.assertIn(expected, err)

    def test_a_file_that_is_not_utf8(self):
        def bad(*parts):
            if len(parts) == 1:  # a path already
                target = os.path.join(
                    self.tmp.name, "utf16-" + os.path.basename(parts[0])
                )
                with open(parts[0], encoding="utf-8") as handle:
                    text = handle.read()
                with open(target, "w", encoding="utf-16") as handle:
                    handle.write(text)
                return target
            return self.utf16(*parts)

        for name, argv in self.cases(bad).items():
            path = next(a for a in argv if os.path.basename(a).startswith("utf16-"))
            with self.subTest(case=name):
                self.assert_one_line(argv, "%s is not UTF-8 text" % path)

    def test_a_directory(self):
        folder = os.path.join(self.tmp.name, "a folder")
        os.mkdir(folder)
        for name, argv in self.cases(lambda *parts: folder).items():
            with self.subTest(case=name):
                self.assert_one_line(argv, "cannot read %s" % folder)


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
