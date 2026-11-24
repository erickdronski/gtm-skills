"""Tests that the installable package says what the repository says.

A version that disagrees between the wheel, the plugin manifest, and the
changelog, a starter spec that drifted from the example CI exercises, or a
file the package reads at run time that the wheel leaves out, is invisible
until a user installs the release. These checks read the files a build reads,
so the drift is caught on the commit that introduces it.
"""

import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

from gtmkit import __version__, cli, qualify

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - exercised on 3.9 and 3.10
    tomllib = None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGE = os.path.join(REPO_ROOT, "gtmkit")
TEMPLATES = os.path.join(PACKAGE, "templates")
DATA = os.path.join(PACKAGE, "data")
SKILL_RUBRIC = os.path.join(
    "skills", "deal-qualification", "assets", "meddpicc-rubric.json"
)

# Each starter `gtmkit init` prints, and the shipped example it copies.
STARTER_SOURCES = {
    "value-case": os.path.join("value-case", "northwind-support-deflection.json"),
    "deal": os.path.join("deal", "kestrel-expansion.json"),
    "sizing": os.path.join("sizing", "agent-observability-na.json"),
}


def read(*parts):
    with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


def package_data_globs():
    found = re.search(
        r"\[tool\.setuptools\.package-data\]\s*gtmkit\s*=\s*\[([^\]]*)\]",
        read("pyproject.toml"),
    )
    return re.findall(r'"([^"]+)"', found.group(1)) if found else []


def wheel_files():
    """The files a wheel built from pyproject.toml puts under gtmkit/: every
    module of the one package, plus whatever the package-data globs match."""
    shipped = [name for name in os.listdir(PACKAGE) if name.endswith(".py")]
    for root, _, names in os.walk(PACKAGE):
        for name in names:
            path = os.path.relpath(os.path.join(root, name), PACKAGE)
            path = path.replace(os.sep, "/")
            if any(fnmatch.fnmatch(path, glob) for glob in package_data_globs()):
                shipped.append(path)
    return sorted(shipped)


# The front door run from a copy of the package with nothing else importable:
# -I leaves out the current directory, PYTHONPATH and the user site-packages.
FRONT_DOOR = (
    "import sys; site = sys.argv.pop(1); sys.path.insert(0, site); "
    "import gtmkit; assert gtmkit.__file__.startswith(site), gtmkit.__file__; "
    "from gtmkit.cli import main; sys.exit(main())"
)


class TestStarterTemplates(unittest.TestCase):
    def test_every_starter_has_a_source_example(self):
        self.assertEqual(sorted(STARTER_SOURCES), sorted(k for k, *_ in cli.STARTERS))

    def test_templates_match_their_examples_byte_for_byte(self):
        for kind, filename, _, _ in cli.STARTERS:
            with self.subTest(kind=kind):
                source = os.path.join(REPO_ROOT, "examples", STARTER_SOURCES[kind])
                with open(source, "rb") as handle:
                    expected = handle.read()
                self.assertEqual(
                    cli.starter_bytes(kind),
                    expected,
                    "gtmkit/templates/%s has drifted from examples/%s. Copy the "
                    "example over the template." % (filename, STARTER_SOURCES[kind]),
                )

    def test_no_orphan_template_files(self):
        shipped = sorted(os.listdir(TEMPLATES))
        self.assertEqual(shipped, sorted(f for _, f, _, _ in cli.STARTERS))

    def test_package_data_globs_cover_every_data_file(self):
        globs = package_data_globs()
        self.assertTrue(globs, "pyproject.toml must ship gtmkit/templates and data")
        for directory in (TEMPLATES, DATA):
            for filename in os.listdir(directory):
                path = "%s/%s" % (os.path.basename(directory), filename)
                with self.subTest(path=path):
                    self.assertTrue(any(fnmatch.fnmatch(path, g) for g in globs))


class TestPackagedRubric(unittest.TestCase):
    """`gtmkit qualify` reads the skill's rubric, or this copy after pip."""

    def test_packaged_rubric_matches_the_skill_byte_for_byte(self):
        with open(os.path.join(REPO_ROOT, SKILL_RUBRIC), "rb") as handle:
            expected = handle.read()
        with open(os.path.join(PACKAGE, *qualify.PACKAGED_RUBRIC), "rb") as handle:
            self.assertEqual(
                handle.read(),
                expected,
                "gtmkit/data/meddpicc-rubric.json has drifted from %s. Copy the "
                "skill's rubric over the packaged one." % SKILL_RUBRIC,
            )

    def test_the_data_directory_holds_only_the_rubric(self):
        self.assertEqual(qualify.PACKAGED_RUBRIC[0], os.path.basename(DATA))
        self.assertEqual(os.listdir(DATA), [qualify.PACKAGED_RUBRIC[1]])


class TestInstalledLayout(unittest.TestCase):
    """What pip installs, run where there is no clone to fall back on."""

    def front_door(self, site, cwd, *args):
        return subprocess.run(
            [sys.executable, "-I", "-c", FRONT_DOOR, site, *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_wheel_carries_the_modules_templates_and_rubric(self):
        shipped = wheel_files()
        self.assertIn("cli.py", shipped)
        self.assertIn("data/meddpicc-rubric.json", shipped)
        for _, filename, _, _ in cli.STARTERS:
            self.assertIn("templates/%s" % filename, shipped)

    def test_every_starter_runs_the_command_init_names(self):
        with tempfile.TemporaryDirectory() as tmp:
            site = os.path.join(tmp, "site")
            for path in wheel_files():
                target = os.path.join(site, "gtmkit", *path.split("/"))
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copyfile(os.path.join(PACKAGE, *path.split("/")), target)
            work = os.path.join(tmp, "work")
            os.mkdir(work)
            for kind, _, _, _ in cli.STARTERS:
                with self.subTest(kind=kind):
                    out = "%s.json" % kind
                    init = self.front_door(site, work, "init", kind, "--out", out)
                    self.assertEqual(init.returncode, 0, init.stderr)
                    told = init.stderr.decode("utf-8").split("then run: ", 1)[1]
                    command = shlex.split(told)
                    self.assertEqual(command[0], "gtmkit")
                    result = self.front_door(site, work, *command[1:])
                    self.assertEqual(
                        result.returncode, 0, result.stderr.decode("utf-8")
                    )
                    self.assertTrue(result.stdout.strip())


class TestProjectMetadata(unittest.TestCase):
    def setUp(self):
        self.text = read("pyproject.toml")
        self.data = tomllib.loads(self.text) if tomllib else None

    def test_version_is_single_sourced_from_the_package(self):
        if self.data:
            project = self.data["project"]
            self.assertNotIn("version", project, "version must stay dynamic")
            self.assertIn("version", project["dynamic"])
            self.assertEqual(
                self.data["tool"]["setuptools"]["dynamic"]["version"],
                {"attr": "gtmkit.__version__"},
            )
        self.assertRegex(self.text, r'dynamic\s*=\s*\["version"\]')
        self.assertRegex(
            self.text, r'version\s*=\s*\{\s*attr\s*=\s*"gtmkit\.__version__"\s*\}'
        )
        self.assertIsNone(re.search(r'(?m)^version\s*=\s*"', self.text))

    def test_plugin_manifest_carries_the_same_version(self):
        manifest = json.loads(read(".claude-plugin", "plugin.json"))
        self.assertEqual(manifest["version"], __version__)

    def test_changelog_has_an_entry_for_this_version(self):
        self.assertIn("## [%s]" % __version__, read("CHANGELOG.md"))

    def test_python_classifiers_match_the_ci_matrix(self):
        matrix = re.search(
            r"python-version:\s*\[([^\]]*)\]", read(".github", "workflows", "ci.yml")
        )
        self.assertIsNotNone(matrix)
        tested = sorted(
            re.findall(r'"(3\.\d+)"', matrix.group(1)), key=lambda v: int(v[2:])
        )
        declared = sorted(
            re.findall(r"Programming Language :: Python :: (3\.\d+)", self.text),
            key=lambda v: int(v[2:]),
        )
        self.assertEqual(declared, tested)
        self.assertRegex(
            self.text, r'requires-python\s*=\s*">=%s"' % re.escape(tested[0])
        )

    def test_no_runtime_dependencies(self):
        self.assertRegex(self.text, r"(?m)^dependencies\s*=\s*\[\]")
        if self.data:
            self.assertEqual(self.data["project"]["dependencies"], [])

    def test_console_script_is_the_front_door(self):
        self.assertRegex(self.text, r'gtmkit\s*=\s*"gtmkit\.cli:main"')
        if self.data:
            self.assertEqual(
                self.data["project"]["scripts"], {"gtmkit": "gtmkit.cli:main"}
            )
            self.assertEqual(self.data["tool"]["setuptools"]["packages"], ["gtmkit"])


if __name__ == "__main__":
    unittest.main()
