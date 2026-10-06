"""Tests for deal qualification.

The expected scores are worked by hand from the rubric weights, not captured
from a run. The shipped MEDDPICC weights are metrics 3, economic buyer 4,
decision criteria 3, decision process 3, paper process 3, identified pain 4,
champion 4, competition 2 — 26 in all, on a 0-4 scale.
"""

import contextlib
import copy
import datetime
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest

from gtmkit.qualify import (
    QualificationRubric,
    QualifyError,
    load_rubric,
    main,
    qualify,
    to_markdown,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(REPO_ROOT, "examples", "deal", "kestrel-expansion.json")
SOURCE = "Order form signed 2026-09-01, in the shared drive"


def load_example():
    with open(EXAMPLE, encoding="utf-8") as handle:
        return json.load(handle)


def tiny_rubric():
    """Two elements, small enough that every number is mental arithmetic."""
    return QualificationRubric(
        {
            "name": "Tiny",
            "scale": 4,
            "min_coverage": 0.5,
            "tiers": [{"min": 0.75, "label": "GOOD"}, {"min": 0.0, "label": "WEAK"}],
            "stages": [{"id": "early"}, {"id": "late"}],
            "criteria": [
                {
                    "id": "alpha",
                    "label": "Alpha",
                    "weight": 2,
                    "type": "categorical",
                    "map": {"hi": 4, "lo": 0},
                    "confirm_by": "late",
                },
                {
                    "id": "beta",
                    "label": "Beta",
                    "weight": 1,
                    "type": "categorical",
                    "map": {"hi": 4, "mid": 2, "lo": 0},
                    "confirm_by": "early",
                },
            ],
        }
    )


def tiny_deal(alpha=None, beta=None, stage="early"):
    elements = {}
    if alpha is not None:
        elements["alpha"] = alpha
    if beta is not None:
        elements["beta"] = beta
    return {
        "name": "Tiny deal",
        "stage": stage,
        "as_of": "2026-10-06",
        "elements": elements,
    }


def confirmed(level):
    return {"level": level, "status": "confirmed", "source": SOURCE}


def assumed(level):
    return {"level": level, "status": "assumed"}


class TestScoringArithmetic(unittest.TestCase):
    def setUp(self):
        self.rubric = tiny_rubric()

    def test_score_is_weighted_points_over_weighted_maximum(self):
        # (2 x 4 + 1 x 2) / (3 x 4) = 10 / 12
        result = qualify(tiny_deal(confirmed("hi"), assumed("mid")), self.rubric)
        self.assertAlmostEqual(result["score"], 10 / 12)
        self.assertAlmostEqual(result["coverage"], 1.0)
        self.assertEqual(result["tier"], "GOOD")

    def test_unknown_lowers_coverage_not_score(self):
        """The central behavior, inherited from the ICP scorer."""
        unknown = qualify(
            tiny_deal(confirmed("hi"), {"status": "unknown"}), self.rubric
        )
        known_bad = qualify(tiny_deal(confirmed("hi"), confirmed("lo")), self.rubric)
        # Unknown beta is left out: 8 / 8. Known-bad beta counts: 8 / 12.
        self.assertAlmostEqual(unknown["score"], 1.0)
        self.assertAlmostEqual(unknown["coverage"], 2 / 3)
        self.assertAlmostEqual(known_bad["score"], 8 / 12)

    def test_status_changes_the_evidence_mix_not_the_score(self):
        believed = qualify(tiny_deal(confirmed("hi"), assumed("mid")), self.rubric)
        proven = qualify(tiny_deal(confirmed("hi"), confirmed("mid")), self.rubric)
        self.assertAlmostEqual(believed["score"], proven["score"])
        self.assertAlmostEqual(
            believed["evidence"]["share_by_status"]["confirmed"], 2 / 3
        )
        self.assertAlmostEqual(
            believed["evidence"]["share_by_status"]["assumed"], 1 / 3
        )
        self.assertAlmostEqual(proven["evidence"]["share_by_status"]["confirmed"], 1.0)

    def test_floor_puts_everything_unconfirmed_at_its_worst(self):
        # Alpha confirmed at 4 keeps 8 points; assumed beta falls to 0: 8 / 12.
        result = qualify(tiny_deal(confirmed("hi"), assumed("mid")), self.rubric)
        self.assertAlmostEqual(result["floor"]["score"], 8 / 12)
        self.assertEqual(result["floor"]["tier"], "WEAK")

    def test_low_coverage_is_held_out_of_the_tiers(self):
        # Only beta (weight 1 of 3) answered: 33% coverage, under the 50% bar.
        result = qualify(tiny_deal(None, confirmed("hi")), self.rubric)
        self.assertEqual(result["tier"], "UNKNOWN")
        self.assertAlmostEqual(result["coverage"], 1 / 3)

    def test_points_are_reported_per_element(self):
        result = qualify(tiny_deal(confirmed("hi"), assumed("mid")), self.rubric)
        points = {e["id"]: e["points"] for e in result["elements"]}
        self.assertEqual(points, {"alpha": 4, "beta": 2})


class TestNextAction(unittest.TestCase):
    def setUp(self):
        self.rubric = tiny_rubric()

    def test_picks_the_element_that_can_move_the_tier(self):
        # Beta at worst: 8 / 12 = 67% (WEAK); at best 12 / 12 (GOOD).
        result = qualify(tiny_deal(confirmed("hi"), assumed("mid")), self.rubric)
        action = result["next_action"]
        self.assertEqual(action["element"], "beta")
        self.assertTrue(action["changes_forecast"])
        self.assertEqual(action["tier_if_worst"], "WEAK")
        self.assertAlmostEqual(action["score_if_worst"], 8 / 12)
        self.assertAlmostEqual(action["score_if_best"], 1.0)

    def test_a_settled_element_is_never_the_next_action(self):
        result = qualify(tiny_deal(confirmed("hi"), assumed("mid")), self.rubric)
        self.assertNotIn("Alpha", result["next_action"]["then"])

    def test_everything_confirmed_at_best_leaves_nothing_to_confirm(self):
        result = qualify(tiny_deal(confirmed("hi"), confirmed("hi")), self.rubric)
        self.assertEqual(result["next_action"]["kind"], "none")

    def test_unknown_tier_asks_for_the_answers_that_make_it_tierable(self):
        result = qualify(tiny_deal(None, confirmed("hi")), self.rubric)
        action = result["next_action"]
        self.assertEqual(action["kind"], "coverage")
        self.assertEqual(action["element"], "alpha")
        # Alpha alone lifts coverage from 1/3 to 1, past the 50% bar.
        self.assertTrue(action["changes_forecast"])

    def test_weaker_status_wins_a_tie(self):
        """Unknown ranks ahead of assumed when everything else is equal."""
        rubric = QualificationRubric(
            {
                "name": "Tie",
                "scale": 4,
                "min_coverage": 0.0,
                "tiers": [{"min": 0.5, "label": "UP"}, {"min": 0.0, "label": "DOWN"}],
                "stages": [{"id": "only"}],
                "criteria": [
                    {
                        "id": "a",
                        "weight": 1,
                        "type": "categorical",
                        "map": {"hi": 4, "lo": 0},
                    },
                    {
                        "id": "b",
                        "weight": 1,
                        "type": "categorical",
                        "map": {"hi": 4, "lo": 0},
                    },
                    {
                        "id": "c",
                        "weight": 1,
                        "type": "categorical",
                        "map": {"hi": 4, "lo": 0},
                    },
                ],
            }
        )
        deal = {
            "name": "Tie",
            "stage": "only",
            "as_of": "2026-10-06",
            "elements": {
                "a": assumed("hi"),
                "b": {"status": "unknown"},
                "c": confirmed("hi"),
            },
        }
        # Neither can move the tier: a at its worst is 4/8 = 50%, still UP, and
        # b at its worst is 8/12 = 67%. So the tie falls to status, and the
        # unknown b outranks the assumed a.
        result = qualify(deal, rubric)
        self.assertFalse(result["next_action"]["changes_forecast"])
        self.assertEqual(result["next_action"]["element"], "b")


class TestShippedExample(unittest.TestCase):
    """Hand-worked against the MEDDPICC weights listed in the module docstring."""

    def setUp(self):
        self.result = qualify(load_example())

    def test_believed_score(self):
        # Paper process unknown, so known weight is 26 - 3 = 23, max 92.
        # Points: 3x3 + 4x1 + 3x3 + 3x2 + 4x4 + 4x2 + 2x2 = 56.
        self.assertAlmostEqual(self.result["score"], 56 / 92)
        self.assertAlmostEqual(self.result["coverage"], 23 / 26)
        self.assertEqual(self.result["tier"], "BEST CASE")

    def test_evidence_mix_by_weight(self):
        shares = self.result["evidence"]["share_by_status"]
        self.assertAlmostEqual(shares["confirmed"], 10 / 26)  # M3 + DC3 + IP4
        self.assertAlmostEqual(shares["stated"], 8 / 26)  # EB4 + CH4
        self.assertAlmostEqual(shares["assumed"], 5 / 26)  # DP3 + CO2
        self.assertAlmostEqual(shares["unknown"], 3 / 26)  # PP3

    def test_floor(self):
        # Only the confirmed points survive: 9 + 9 + 16 = 34 of 104.
        self.assertAlmostEqual(self.result["floor"]["score"], 34 / 104)
        self.assertEqual(self.result["floor"]["tier"], "AT RISK")

    def test_failure_patterns_at_proposal(self):
        fired = {p["id"] for p in self.result["patterns"]}
        self.assertEqual(
            fired,
            {
                "no_economic_buyer_access",
                "champion_untested",
                "decision_process_assumed",
                "paper_process_late",
            },
        )

    def test_next_action_is_the_economic_buyer(self):
        action = self.result["next_action"]
        self.assertEqual(action["element"], "economic_buyer")
        # Worst: 52 / 92 = 57%, PIPELINE. Best: 68 / 92 = 74%, still BEST CASE.
        self.assertAlmostEqual(action["score_if_worst"], 52 / 92)
        self.assertEqual(action["tier_if_worst"], "PIPELINE")
        self.assertAlmostEqual(action["score_if_best"], 68 / 92)
        self.assertEqual(
            action["then"], ["Champion", "Paper process", "Decision process"]
        )

    def test_days_to_close(self):
        self.assertEqual(self.result["days_to_close"], 45)

    def test_markdown_leads_with_the_verdict(self):
        markdown = to_markdown(self.result)
        self.assertLess(markdown.index("## Verdict"), markdown.index("## Elements"))
        for heading in ("## Next action", "## Failure patterns (4)", "## Evidence mix"):
            self.assertIn(heading, markdown)

    def test_matches_the_scoring_engine(self):
        """Same rubric, same levels: the two tools must agree on the tier."""
        from gtmkit.scoring import score_record

        rubric = load_rubric()
        record = {
            e["id"]: e["level"]
            for e in self.result["elements"]
            if e["level"] is not None
        }
        scored = score_record(rubric.scoring, record)
        self.assertAlmostEqual(scored["fit"], self.result["score"])
        self.assertEqual(scored["tier"], self.result["tier"])


class TestStageAwareness(unittest.TestCase):
    def with_stage(self, stage, close_date="2026-11-20"):
        spec = load_example()
        spec["stage"] = stage
        spec["close_date"] = close_date
        return qualify(spec)

    def test_nothing_fires_in_discovery(self):
        """The same gaps are normal early, which is why they are not flagged."""
        self.assertEqual(self.with_stage("discovery")["patterns"], [])

    def test_only_solution_stage_gates_fire_at_solution(self):
        fired = {p["id"] for p in self.with_stage("solution")["patterns"]}
        self.assertEqual(fired, {"no_economic_buyer_access", "champion_untested"})

    def test_paper_clock_fires_before_its_stage(self):
        # 30 days out is inside the 42-day lead time, so the paper process is
        # flagged at Solution even though its stage gate is Proposal.
        result = self.with_stage("solution", close_date="2026-11-05")
        paper = [p for p in result["patterns"] if p["id"] == "paper_process_late"]
        self.assertEqual(len(paper), 1)
        self.assertTrue(paper[0]["by_clock"])
        self.assertIn("42-day", paper[0]["when"])

    def test_paper_clock_respects_the_lead_time(self):
        # 43 days out is outside the lead time.
        result = self.with_stage("solution", close_date="2026-11-18")
        self.assertNotIn("paper_process_late", {p["id"] for p in result["patterns"]})

    def test_elapsed_close_date_is_noted(self):
        result = self.with_stage("proposal", close_date="2026-09-30")
        self.assertEqual(result["days_to_close"], -6)
        self.assertTrue(any("6 days past" in n for n in result["notes"]))


class TestDisqualification(unittest.TestCase):
    def spec_without_pain(self, status):
        spec = load_example()
        spec["elements"]["identified_pain"] = {"level": "none", "status": status}
        if status == "confirmed":
            spec["elements"]["identified_pain"]["source"] = (
                "Dana Ruiz email 2026-10-01: the backlog fix is deferred to FY28"
            )
        return spec

    def test_no_pain_is_out(self):
        result = qualify(self.spec_without_pain("confirmed"))
        self.assertEqual(result["tier"], "OUT")
        self.assertEqual(result["next_action"]["kind"], "disqualify")
        self.assertIn("Disqualify it", result["next_action"]["action"])

    def test_unconfirmed_no_pain_asks_for_confirmation_first(self):
        result = qualify(self.spec_without_pain("assumed"))
        self.assertEqual(result["tier"], "OUT")
        self.assertIn("Confirm Identified pain", result["next_action"]["action"])


class TestConfirmationRules(unittest.TestCase):
    """A 'confirmed' answer must point at something a reviewer could open."""

    def confirm_with(self, source):
        spec = tiny_deal({"level": "hi", "status": "confirmed", "source": source})
        return qualify(spec, tiny_rubric())

    def test_rejects_unfalsifiable_sources(self):
        for source in (
            "industry standard",
            "Multiple calls with the customer",
            "Several emails from the buyer",
            "The customer said so",
            "Rep's notes",
            "Salesforce notes",
            "Verbal confirmation",
            "CRM",
        ):
            with self.subTest(source=source), self.assertRaises(QualifyError):
                self.confirm_with(source)

    def test_rejects_a_conversation_without_saying_which_one(self):
        with self.assertRaises(QualifyError) as ctx:
            self.confirm_with("Discovery call with Dana Ruiz")
        self.assertIn("add the date", str(ctx.exception))

    def test_error_points_at_the_honest_alternatives(self):
        with self.assertRaises(QualifyError) as ctx:
            self.confirm_with("industry standard")
        self.assertIn("stated", str(ctx.exception))
        self.assertIn("assumed", str(ctx.exception))

    def test_accepts_checkable_sources(self):
        for source in (
            "Dana Ruiz email 2026-09-14",
            "Signed mutual action plan, version 3",
            "Call with Tom Akers on Sep 12, Gong",
            "The customer confirmed it on the 2026-09-12 call",
            "Security questionnaire returned by their IT team",
        ):
            with self.subTest(source=source):
                self.assertEqual(self.confirm_with(source)["tier"], "GOOD")

    def test_stated_needs_a_person(self):
        for by in ("the customer", "They", "champion", ""):
            with self.subTest(by=by):
                spec = tiny_deal({"level": "hi", "status": "stated", "by": by})
                with self.assertRaises(QualifyError):
                    qualify(spec, tiny_rubric())
        spec = tiny_deal(
            {"level": "hi", "status": "stated", "by": "Dana Ruiz, VP Support"}
        )
        self.assertEqual(qualify(spec, tiny_rubric())["tier"], "GOOD")

    def test_assumed_needs_no_source(self):
        result = qualify(tiny_deal(assumed("hi")), tiny_rubric())
        self.assertEqual(result["elements"][0]["status"], "assumed")


class TestSpecValidation(unittest.TestCase):
    def assert_rejected(self, spec, fragment, rubric=None):
        with self.assertRaises(QualifyError) as ctx:
            qualify(spec, rubric or tiny_rubric())
        self.assertIn(fragment, str(ctx.exception))

    def test_unknown_with_a_level_is_a_contradiction(self):
        self.assert_rejected(tiny_deal({"level": "hi", "status": "unknown"}), "assumed")

    def test_unknown_level_lists_the_real_ones(self):
        self.assert_rejected(tiny_deal(assumed("medium")), "hi, lo")

    def test_level_matching_forgives_spacing_and_case(self):
        spec = load_example()
        spec["elements"]["economic_buyer"]["level"] = "Identified Not Met"
        self.assertEqual(qualify(spec)["tier"], "BEST CASE")

    def test_status_is_required(self):
        self.assert_rejected(tiny_deal({"level": "hi"}), "status")

    def test_misspelled_key_is_not_silently_dropped(self):
        self.assert_rejected(
            tiny_deal({"level": "hi", "status": "confirmed", "sorce": SOURCE}),
            "sorce",
        )

    def test_element_the_rubric_does_not_define(self):
        spec = tiny_deal(assumed("hi"))
        spec["elements"]["gamma"] = assumed("hi")
        self.assert_rejected(spec, "gamma")

    def test_stage_must_be_in_the_rubric(self):
        self.assert_rejected(
            tiny_deal(assumed("hi"), stage="contracting"), "early, late"
        )

    def test_dates_must_be_iso(self):
        spec = tiny_deal(assumed("hi"))
        spec["close_date"] = "11/20/2026"
        self.assert_rejected(spec, "YYYY-MM-DD")

    def test_amount_must_be_positive(self):
        spec = tiny_deal(assumed("hi"))
        spec["amount"] = -5
        self.assert_rejected(spec, "amount")

    def test_missing_element_is_unknown_and_reported(self):
        result = qualify(tiny_deal(assumed("hi")), tiny_rubric())
        beta = result["elements"][1]
        self.assertEqual(beta["status"], "unknown")
        self.assertFalse(beta["recorded"])
        self.assertTrue(any("Not in the spec" in n for n in result["notes"]))

    def test_patterns_the_rubric_cannot_support_are_listed(self):
        result = qualify(tiny_deal(assumed("hi")), tiny_rubric())
        self.assertEqual(len(result["patterns_not_checked"]), 6)


class TestRubricValidation(unittest.TestCase):
    def raw(self):
        with open(
            os.path.join(
                REPO_ROOT,
                "skills",
                "deal-qualification",
                "assets",
                "meddpicc-rubric.json",
            ),
            encoding="utf-8",
        ) as handle:
            return json.load(handle)

    def test_shipped_rubric_loads(self):
        rubric = QualificationRubric(self.raw())
        self.assertEqual(len(rubric.stages), 6)
        self.assertEqual(rubric.paper_lead_days, 42)

    def test_requires_stages(self):
        raw = self.raw()
        del raw["stages"]
        with self.assertRaises(QualifyError):
            QualificationRubric(raw)

    def test_confirm_by_must_name_a_stage(self):
        raw = self.raw()
        raw["criteria"][0]["confirm_by"] = "demo"
        with self.assertRaises(QualifyError) as ctx:
            QualificationRubric(raw)
        self.assertIn("demo", str(ctx.exception))

    def test_requires_categorical_levels(self):
        raw = copy.deepcopy(self.raw())
        raw["criteria"][0] = {
            "id": "metrics",
            "weight": 3,
            "type": "numeric",
            "bands": [{"min": 0, "score": 4}],
        }
        with self.assertRaises(QualifyError):
            QualificationRubric(raw)


class TestCommandLine(unittest.TestCase):
    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_markdown_run(self):
        code, out, _ = self.run_main(EXAMPLE)
        self.assertEqual(code, 0)
        self.assertIn("BEST CASE on belief, AT RISK at the floor", out)

    def test_json_run(self):
        code, out, _ = self.run_main(EXAMPLE, "--format", "json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["next_action"]["element"], "economic_buyer")

    def test_as_of_overrides_the_spec(self):
        _, out, _ = self.run_main(EXAMPLE, "--format", "json", "--as-of", "2026-11-01")
        self.assertEqual(json.loads(out)["days_to_close"], 19)

    def test_bad_spec_exits_2_with_the_reason(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "deal.json")
            spec = load_example()
            spec["elements"]["metrics"]["source"] = "industry standard"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(spec, handle)
            code, _, err = self.run_main(path)
        self.assertEqual(code, 2)
        self.assertIn("metrics", err)

    def test_missing_file_exits_2(self):
        code, _, err = self.run_main("no-such-deal.json")
        self.assertEqual(code, 2)
        self.assertIn("no such deal spec", err)

    def test_module_runs_as_a_script(self):
        """Exercise ``__main__`` the way a user does, not just main()."""
        completed = subprocess.run(
            [sys.executable, "-m", "gtmkit.qualify", EXAMPLE, "--format", "json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["tier"], "BEST CASE")


class TestDefaultAsOf(unittest.TestCase):
    def test_today_is_used_and_reported_when_nothing_is_given(self):
        spec = tiny_deal(assumed("hi"))
        del spec["as_of"]
        result = qualify(spec, tiny_rubric())
        self.assertEqual(result["as_of"], datetime.date.today().isoformat())


if __name__ == "__main__":
    unittest.main()
