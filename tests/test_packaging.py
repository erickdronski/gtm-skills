"""Tests that the installable package says what the repository says.

A version that disagrees between the wheel, the plugin manifest, and the
changelog, or a starter spec that drifted from the example CI exercises, is
invisible until a user installs the release. These checks read the files a
build reads, so the drift is caught on the commit that introduces it.
"""

import fnmatch
import json
import os
import re
import unittest

from gtmkit import __version__, cli

try:  # Python 3.11+
    import tomllib
except ImportError:  # pragma: no cover - exercised on 3.9 and 3.10
    tomllib = None

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATES = os.path.join(REPO_ROOT, "gtmkit", "templates")

# Each starter `gtmkit init` prints, and the shipped example it copies.
STARTER_SOURCES = {
    "value-case": os.path.join("value-case", "northwind-support-deflection.json"),
    "deal": os.path.join("deal", "kestrel-expansion.json"),
    "sizing": os.path.join("sizing", "agent-observability-na.json"),
}


def read(*parts):
    with open(os.path.join(REPO_ROOT, *parts), encoding="utf-8") as handle:
        return handle.read()


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

    def test_package_data_glob_covers_every_template(self):
        globs = re.search(
            r"\[tool\.setuptools\.package-data\]\s*gtmkit\s*=\s*\[([^\]]*)\]",
            read("pyproject.toml"),
        )
        self.assertIsNotNone(globs, "pyproject.toml must ship gtmkit/templates")
        patterns = re.findall(r'"([^"]+)"', globs.group(1))
        for filename in os.listdir(TEMPLATES):
            with self.subTest(template=filename):
                self.assertTrue(
                    any(fnmatch.fnmatch("templates/%s" % filename, p) for p in patterns)
                )


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
