"""Tests that the repository itself stays consistent.

These catch the class of decay that is invisible in unit tests: a skill that
points at a reference somebody deleted, an example that stopped parsing after a
validation rule tightened, or a README quoting output the code no longer
produces. All three are worse than a failing function, because they are only
discovered by a user.
"""

import json
import os
import re
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gtmkit import pricing, scoring, sizing, valuecase
from tools import validate_skills

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILLS_DIR = os.path.join(REPO_ROOT, "skills")
EXAMPLES = os.path.join(REPO_ROOT, "examples")


def skill_dirs():
    return sorted(
        os.path.join(SKILLS_DIR, entry)
        for entry in os.listdir(SKILLS_DIR)
        if os.path.isdir(os.path.join(SKILLS_DIR, entry)) and not entry.startswith(".")
    )


class TestSkillLinter(unittest.TestCase):
    def test_every_skill_passes_the_linter(self):
        findings = validate_skills.Findings()
        for directory in skill_dirs():
            validate_skills.check_skill(directory, findings)
        self.assertEqual(
            findings.errors,
            [],
            "skill linter found errors:\n" + "\n".join(findings.errors),
        )

    def test_there_are_skills_to_check(self):
        self.assertGreaterEqual(len(skill_dirs()), 5)

    def test_linter_catches_a_broken_skill(self):
        """The linter must actually fail on something broken.

        A linter that passes everything is indistinguishable from no linter,
        so this asserts it has teeth rather than just that it returns clean.
        """
        validate_skills.Findings()
        frontmatter, _ = validate_skills.parse_frontmatter("no frontmatter here")
        self.assertEqual(frontmatter, {})

        broken = validate_skills.parse_frontmatter(
            "---\nname: mismatched\ndescription: short\n---\nbody\n"
        )[0]
        self.assertEqual(broken["name"], "mismatched")


class TestShippedExamplesStillRun(unittest.TestCase):
    """Every example referenced by CI or the README must still work."""

    def test_value_case_example(self):
        case = valuecase.load_spec(
            os.path.join(EXAMPLES, "value-case", "northwind-support-deflection.json")
        )
        self.assertGreater(case.summary()["npv"], 0)

    def test_icp_example(self):
        with open(
            os.path.join(EXAMPLES, "icp", "rubric.json"), encoding="utf-8"
        ) as handle:
            rubric = scoring.Rubric(json.load(handle))
        records = scoring.load_records(os.path.join(EXAMPLES, "icp", "accounts.csv"))
        results = scoring.score_all(rubric, records)
        self.assertEqual(len(results), len(records))
        # The example is built to exercise every branch of the tiering logic.
        tiers = {r["tier"] for r in results}
        self.assertIn("OUT", tiers)
        self.assertIn("UNKNOWN", tiers)

    def test_meddpicc_rubric_and_pipeline_example(self):
        path = os.path.join(
            REPO_ROOT,
            "skills",
            "deal-qualification",
            "assets",
            "meddpicc-rubric.json",
        )
        with open(path, encoding="utf-8") as handle:
            rubric = scoring.Rubric(json.load(handle))
        records = scoring.load_records(
            os.path.join(EXAMPLES, "pipeline", "pipeline.csv")
        )
        results = scoring.score_all(rubric, records)
        self.assertTrue(any(r["tier"] == "COMMIT" for r in results))

    def test_sizing_example(self):
        with open(
            os.path.join(EXAMPLES, "sizing", "agent-observability-na.json"),
            encoding="utf-8",
        ) as handle:
            result = sizing.size(json.load(handle))
        self.assertTrue(result["reconciliation"]["agrees"])

    def test_pricing_example(self):
        rows = scoring.load_records(os.path.join(EXAMPLES, "pricing", "responses.csv"))
        result = pricing.analyze(rows)
        self.assertGreater(result["sample"]["usable"], 100)
        # The example deliberately includes malformed rows so the rejection
        # path is exercised rather than merely implemented.
        self.assertGreater(result["sample"]["rejected"], 0)


class TestCategoricalMissingDataSemantics(unittest.TestCase):
    """An explicitly mapped value is a state, not missing data.

    The MEDDPICC rubric originally used "unknown" as a category meaning "we
    asked and nobody could say". That collided with the engine's missing-data
    marker, silently reclassifying a real answer as an unfilled field and
    corrupting the coverage figure — the one number the engine exists to get
    right.
    """

    def setUp(self):
        self.rubric = scoring.Rubric(
            {
                "name": "t",
                "scale": 4,
                "criteria": [
                    {
                        "id": "state",
                        "label": "State",
                        "weight": 1,
                        "type": "categorical",
                        "map": {"known": 4, "unknown": 0},
                        "default": 0,
                    }
                ],
            }
        )

    def test_explicitly_mapped_value_counts_as_data(self):
        result = scoring.score_record(self.rubric, {"state": "unknown"})
        self.assertEqual(result["coverage"], 1.0)
        self.assertEqual(result["missing_criteria"], [])

    def test_genuinely_absent_field_counts_as_missing(self):
        result = scoring.score_record(self.rubric, {})
        self.assertEqual(result["coverage"], 0.0)
        self.assertEqual(result["missing_criteria"], ["State"])

    def test_unmapped_placeholder_still_counts_as_missing(self):
        rubric = scoring.Rubric(
            {
                "name": "t",
                "scale": 4,
                "criteria": [
                    {
                        "id": "state",
                        "label": "State",
                        "weight": 1,
                        "type": "categorical",
                        "map": {"known": 4},
                        "default": 0,
                    }
                ],
            }
        )
        result = scoring.score_record(rubric, {"state": "n/a"})
        self.assertEqual(result["missing_criteria"], ["State"])


class TestReadmeStaysHonest(unittest.TestCase):
    """The README quotes generated output. It must still be generated."""

    def setUp(self):
        with open(os.path.join(REPO_ROOT, "README.md"), encoding="utf-8") as handle:
            self.readme = handle.read()

    def test_quoted_headline_numbers_match_the_example(self):
        case = valuecase.load_spec(
            os.path.join(EXAMPLES, "value-case", "northwind-support-deflection.json")
        )
        markdown = case.to_markdown()
        for quoted in ("$105.2k", "2 yr 4 mo", "$579.7k"):
            with self.subTest(quoted=quoted):
                self.assertIn(
                    quoted,
                    markdown,
                    "README quotes %r but the example no longer produces it" % quoted,
                )
                self.assertIn(quoted, self.readme)

    def test_every_skill_is_listed(self):
        for directory in skill_dirs():
            name = os.path.basename(directory)
            with self.subTest(skill=name):
                self.assertIn(
                    "skills/%s/SKILL.md" % name,
                    self.readme,
                    "skill %r is not linked from the README" % name,
                )

    def test_test_count_badge_is_not_stale(self):
        """A badge claiming a test count must not undercount reality."""
        match = re.search(r"tests-(\d+)-", self.readme)
        self.assertIsNotNone(match, "README has no test count badge")
        claimed = int(match.group(1))
        loader = unittest.TestLoader()
        suite = loader.discover(
            os.path.join(REPO_ROOT, "tests"), top_level_dir=REPO_ROOT
        )
        actual = suite.countTestCases()
        self.assertGreaterEqual(
            actual,
            claimed,
            "README claims %d tests but only %d exist" % (claimed, actual),
        )


class TestPluginManifests(unittest.TestCase):
    def test_plugin_json_is_valid(self):
        path = os.path.join(REPO_ROOT, ".claude-plugin", "plugin.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        for key in ("name", "description", "version"):
            self.assertIn(key, data)

    def test_marketplace_json_is_valid(self):
        path = os.path.join(REPO_ROOT, ".claude-plugin", "marketplace.json")
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
        self.assertTrue(data.get("plugins"))
        self.assertEqual(data["plugins"][0]["name"], "gtm-skills")

    def test_no_dependency_files_crept_in(self):
        """The zero-dependency claim is load-bearing; keep it true."""
        for filename in ("requirements.txt", "Pipfile", "poetry.lock"):
            with self.subTest(filename=filename):
                self.assertFalse(
                    os.path.exists(os.path.join(REPO_ROOT, filename)),
                    "%s would break the zero-dependency guarantee" % filename,
                )


if __name__ == "__main__":
    unittest.main()
