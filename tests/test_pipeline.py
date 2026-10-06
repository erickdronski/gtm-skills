"""Tests for pipeline coverage and the weighted forecast.

Most numbers here come from a three-deal pipeline small enough to check in
your head, worked below. The shipped example is pinned separately, also by
hand, because the README and the skills quote it.

Model: early 20% (fact), late 50% (assumption, 40-60%).
As of 2026-10-06, period ends 2026-12-31, target $300k, $50k already closed.

    A  $100k  late   commit     close 2026-10-01 (5 days past)
    B   $50k  early  pipeline   last activity 2026-08-01 (66 days)
    C  $200k  early  best case  close 2026-11-15, was 2026-11-01 (pushed 14)
    D   $80k  late   pipeline   close 2027-01-15 (after the period), pushed 2x

In period: A, B, C = $350k. Weighted 100 x .5 + 50 x .2 + 200 x .2 = $100k.
"""

import contextlib
import datetime
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest

from gtmkit.pipeline import (
    PipelineError,
    analyze,
    default_stage_model,
    load_stage_model,
    main,
    to_markdown,
)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE_CSV = os.path.join(REPO_ROOT, "examples", "pipeline", "pipeline.csv")
EXAMPLE_STAGES = os.path.join(REPO_ROOT, "examples", "pipeline", "stages.json")
AS_OF = datetime.date(2026, 10, 6)
PERIOD_END = datetime.date(2026, 12, 31)


def model_spec():
    return {
        "name": "Test model",
        "stages": [
            {
                "id": "early",
                "category": "pipeline",
                "probability": {
                    "value": 0.2,
                    "confidence": "fact",
                    "source": "Stage report FY2026: 40 of 200 early entries won",
                },
            },
            {
                "id": "late",
                "category": "best_case",
                "probability": {
                    "value": 0.5,
                    "confidence": "assumption",
                    "source": "Bounded by the 40-60% seen across FY2024 to FY2026",
                    "low": 0.4,
                    "high": 0.6,
                },
            },
        ],
    }


def rows():
    return [
        {
            "opportunity": "A",
            "amount": "100000",
            "stage": "late",
            "close_date": "2026-10-01",
            "last_activity": "2026-10-05",
            "forecast_category": "commit",
        },
        {
            "opportunity": "B",
            "amount": "50000",
            "stage": "early",
            "close_date": "2026-12-01",
            "last_activity": "2026-08-01",
            "forecast_category": "pipeline",
        },
        {
            "opportunity": "C",
            "amount": "200000",
            "stage": "early",
            "close_date": "2026-11-15",
            "original_close_date": "2026-11-01",
            "last_activity": "2026-10-01",
            "forecast_category": "best_case",
        },
        {
            "opportunity": "D",
            "amount": "80000",
            "stage": "late",
            "close_date": "2027-01-15",
            "push_count": "2",
            "last_activity": "2026-10-01",
            "forecast_category": "pipeline",
        },
    ]


def run(records=None, **overrides):
    kwargs = {
        "model": load_stage_model(model_spec()),
        "as_of": AS_OF,
        "target": 300000,
        "closed": 50000,
        "period_end": PERIOD_END,
    }
    kwargs.update(overrides)
    return analyze(rows() if records is None else records, **kwargs)


class TestForecastArithmetic(unittest.TestCase):
    def setUp(self):
        self.result = run()

    def test_only_in_period_deals_count(self):
        self.assertEqual(self.result["deals_in_period"], 3)
        self.assertAlmostEqual(self.result["pipeline"], 350000)
        self.assertEqual(self.result["later"], {"deals": 1, "amount": 80000})

    def test_weighted_forecast_and_its_range(self):
        self.assertAlmostEqual(self.result["weighted"], 100000)
        # Only the late stage has a range: A moves between 40k and 60k.
        self.assertAlmostEqual(self.result["weighted_low"], 90000)
        self.assertAlmostEqual(self.result["weighted_high"], 110000)

    def test_spread_is_the_bernoulli_standard_deviation(self):
        # sqrt(100k^2 x .25 + 50k^2 x .16 + 200k^2 x .16) = sqrt(9.3e9)
        self.assertAlmostEqual(self.result["spread"], math.sqrt(9.3e9))
        self.assertAlmostEqual(self.result["spread"], 96436.508, places=2)

    def test_coverage_against_what_is_left(self):
        # $300k target - $50k closed = $250k left; $350k / $250k = 1.4x.
        self.assertAlmostEqual(self.result["remaining"], 250000)
        self.assertAlmostEqual(self.result["coverage"], 1.4)

    def test_required_coverage_comes_from_the_probabilities(self):
        # Blended 100k / 350k = 2/7, so the stage mix needs 3.5x.
        self.assertAlmostEqual(self.result["blended_probability"], 2 / 7)
        self.assertAlmostEqual(self.result["required_coverage"], 3.5)

    def test_landing_and_gap(self):
        self.assertAlmostEqual(self.result["landing"], 150000)
        self.assertAlmostEqual(self.result["landing_low"], 140000)
        self.assertAlmostEqual(self.result["landing_high"], 160000)
        self.assertAlmostEqual(self.result["gap"], -150000)

    def test_categories_build_up_from_closed(self):
        by_key = {c["category"]: c for c in self.result["categories"]}
        self.assertAlmostEqual(by_key["commit"]["amount"], 100000)
        self.assertAlmostEqual(by_key["commit"]["cumulative_with_closed"], 150000)
        self.assertAlmostEqual(by_key["commit"]["share_of_target"], 0.5)
        self.assertAlmostEqual(by_key["best_case"]["cumulative_with_closed"], 350000)
        self.assertAlmostEqual(by_key["pipeline"]["cumulative_with_closed"], 400000)
        self.assertAlmostEqual(by_key["pipeline"]["weighted"], 10000)

    def test_concentration(self):
        concentration = run(top=2)["concentration"]
        # C + A = $300k of $350k.
        self.assertAlmostEqual(concentration["top_share"], 300000 / 350000)
        self.assertAlmostEqual(concentration["top_weighted_share"], 0.9)
        self.assertEqual(concentration["largest"]["name"], "C")
        self.assertEqual(concentration["deals_to_half"], 1)
        # Without C: weighted 60k, landing 110k, coverage 150k / 250k.
        without = concentration["without_largest"]
        self.assertAlmostEqual(without["weighted"], 60000)
        self.assertAlmostEqual(without["landing"], 110000)
        self.assertAlmostEqual(without["coverage"], 0.6)

    def test_evidence_grade_weighs_by_forecast_dollars(self):
        # $50k on a fact (B, C) and $50k on an assumption (A): half measured.
        evidence = self.result["evidence"]
        self.assertAlmostEqual(evidence["share_fact"], 0.5)
        self.assertAlmostEqual(evidence["share_assumption"], 0.5)
        self.assertEqual(evidence["grade"], "C")

    def test_stage_rows_total_to_the_forecast(self):
        stages = {s["id"]: s for s in self.result["stages"]}
        self.assertEqual(stages["early"]["deals"], 2)
        self.assertAlmostEqual(stages["early"]["weighted"], 50000)
        self.assertAlmostEqual(
            sum(s["weighted"] for s in self.result["stages"]), self.result["weighted"]
        )


class TestHygiene(unittest.TestCase):
    def setUp(self):
        self.result = run()
        self.flags = {
            d["name"]: {f["kind"]: f for f in d["flags"]} for d in self.result["deals"]
        }

    def test_past_due(self):
        self.assertEqual(self.flags["A"]["past_due"]["days"], 5)

    def test_stale(self):
        self.assertEqual(self.flags["B"]["stale"]["days"], 66)
        self.assertNotIn("stale", self.flags["C"])

    def test_pushed_by_original_date_and_by_count(self):
        self.assertEqual(self.flags["C"]["pushed"]["days"], 14)
        self.assertEqual(self.flags["D"]["push_count"]["count"], 2)

    def test_out_of_period_deals_are_still_checked(self):
        self.assertIn("D", [d["name"] for d in self.result["hygiene"]])

    def test_commit_deals_are_listed_first(self):
        self.assertEqual(
            [d["name"] for d in self.result["hygiene"]], ["A", "C", "D", "B"]
        )

    def test_stale_threshold_is_adjustable(self):
        result = run(stale_days=70)
        names = {
            d["name"]
            for d in result["deals"]
            if any(f["kind"] == "stale" for f in d["flags"])
        }
        self.assertEqual(names, set())

    def test_model_threshold_applies_without_a_flag(self):
        spec = model_spec()
        spec["stale_after_days"] = 70
        result = run(model=load_stage_model(spec))
        self.assertEqual(result["stale_after_days"], 70)


class TestHonestNotes(unittest.TestCase):
    def test_thin_pipeline_says_so_with_the_spread(self):
        notes = " ".join(run()["notes"])
        self.assertIn("Only 3 deals", notes)
        self.assertIn("$96.4k", notes)

    def test_concentration_is_called_out(self):
        notes = " ".join(run()["notes"])
        self.assertIn("C is 57% of the pipeline", notes)

    def test_default_model_is_labelled_a_scenario(self):
        records = rows()
        for row in records:
            row["stage"] = "proposal"
        result = run(records, model=default_stage_model())
        self.assertTrue(result["model_is_default"])
        self.assertEqual(result["evidence"]["grade"], "F")
        self.assertIn("scenario, not a forecast", result["notes"][0])

    def test_no_period_end_counts_everything_and_says_so(self):
        result = run(period_end=None)
        self.assertEqual(result["deals_in_period"], 4)
        self.assertTrue(any("--period-end" in n for n in result["notes"]))

    def test_no_target_skips_coverage(self):
        result = run(target=None)
        self.assertIsNone(result["coverage"])
        self.assertIsNone(result["gap"])
        self.assertTrue(any("--target" in n for n in result["notes"]))

    def test_target_already_met(self):
        result = run(closed=300000)
        self.assertIsNone(result["coverage"])
        self.assertTrue(any("already meets" in n for n in result["notes"]))

    def test_missing_optional_columns_are_reported(self):
        records = [
            {
                k: v
                for k, v in row.items()
                if k in ("opportunity", "amount", "stage", "close_date")
            }
            for row in rows()
        ]
        notes = " ".join(run(records)["notes"])
        self.assertIn("stale deals were not checked", notes)
        self.assertIn("pushed close dates", notes)

    def test_crm_probability_column_is_ignored_out_loud(self):
        records = rows()
        for row in records:
            row["probability"] = "90"
        result = run(records)
        self.assertAlmostEqual(result["weighted"], 100000)
        self.assertTrue(
            any("probability column was ignored" in n for n in result["notes"])
        )

    def test_omitted_deals_leave_the_totals(self):
        records = rows()
        records[1]["forecast_category"] = "Omitted"
        result = run(records)
        self.assertEqual(result["omitted"], {"deals": 1, "amount": 50000})
        self.assertAlmostEqual(result["pipeline"], 300000)

    def test_blank_category_falls_back_to_the_stage(self):
        records = rows()
        records[0]["forecast_category"] = ""
        result = run(records)
        deal = next(d for d in result["deals"] if d["name"] == "A")
        self.assertEqual(deal["category"], "best_case")
        self.assertEqual(deal["category_source"], "stage")
        self.assertTrue(
            any("took the stage model's category" in n for n in result["notes"])
        )


class TestRowHandling(unittest.TestCase):
    def test_headers_are_matched_loosely(self):
        records = [
            {
                "Opportunity": "A",
                "Amount": "$100,000",
                "Stage": "Late",
                "Close Date": "2026-11-01",
            }
        ]
        result = run(records)
        self.assertAlmostEqual(result["weighted"], 50000)

    def test_unusable_rows_are_excluded_with_reasons(self):
        records = [
            *rows(),
            {
                "opportunity": "E",
                "amount": "10",
                "stage": "demo",
                "close_date": "2026-11-01",
            },
            {
                "opportunity": "F",
                "amount": "10",
                "stage": "Closed Won",
                "close_date": "2026-11-01",
            },
            {
                "opportunity": "G",
                "amount": "lots",
                "stage": "early",
                "close_date": "2026-11-01",
            },
            {
                "opportunity": "H",
                "amount": "0",
                "stage": "early",
                "close_date": "2026-11-01",
            },
            {
                "opportunity": "I",
                "amount": "10",
                "stage": "early",
                "close_date": "11/01/2026",
            },
            {
                "opportunity": "J",
                "amount": "10",
                "stage": "early",
                "close_date": "2026-11-01",
                "forecast_category": "maybe",
            },
        ]
        result = run(records)
        reasons = {r["deal"]: r["reason"] for r in result["excluded_rows"]}
        self.assertEqual(set(reasons), set("EFGHIJ"))
        self.assertIn("not in the stage model", reasons["E"])
        self.assertIn("--closed", reasons["F"])
        self.assertIn("not a number", reasons["G"])
        self.assertIn("placeholder", reasons["H"])
        self.assertIn("YYYY-MM-DD", reasons["I"])
        self.assertIn("forecast_category", reasons["J"])
        # The totals are untouched by every excluded row.
        self.assertAlmostEqual(result["weighted"], 100000)

    def test_unreadable_optional_value_keeps_the_deal(self):
        records = rows()
        records[0]["last_activity"] = "last week"
        result = run(records)
        self.assertAlmostEqual(result["weighted"], 100000)
        self.assertEqual(result["ignored_values"][0]["field"], "last_activity")

    def test_nothing_usable_is_an_error(self):
        with self.assertRaises(PipelineError) as ctx:
            run(
                [
                    {
                        "opportunity": "X",
                        "amount": "1",
                        "stage": "nope",
                        "close_date": "x",
                    }
                ]
            )
        self.assertIn("none of the 1 row", str(ctx.exception))

    def test_empty_input_is_an_error(self):
        with self.assertRaises(PipelineError):
            run([])

    def test_rejects_bad_arguments(self):
        for kwargs in ({"target": 0}, {"closed": -1}, {"top": 0}, {"stale_days": 0}):
            with self.subTest(**kwargs), self.assertRaises(PipelineError):
                run(**kwargs)


class TestStageModel(unittest.TestCase):
    def assert_rejected(self, mutate, fragment):
        spec = model_spec()
        mutate(spec)
        with self.assertRaises(PipelineError) as ctx:
            load_stage_model(spec)
        self.assertIn(fragment, str(ctx.exception))

    def test_percentage_style_probability(self):
        def mutate(spec):
            spec["stages"][0]["probability"]["value"] = 20

        self.assert_rejected(mutate, "0.35, not 35")

    def test_unfalsifiable_source(self):
        def mutate(spec):
            spec["stages"][0]["probability"]["source"] = "industry standard"

        self.assert_rejected(mutate, "unfalsifiable")

    def test_assumption_needs_a_range(self):
        def mutate(spec):
            del spec["stages"][1]["probability"]["low"]

        self.assert_rejected(mutate, "low")

    def test_crm_default_cannot_be_a_fact(self):
        def mutate(spec):
            spec["stages"][0]["probability"]["source"] = (
                "Salesforce default stage probability for Prospecting"
            )

        self.assert_rejected(mutate, "picklist")

    def test_crm_default_is_fine_as_a_ranged_assumption(self):
        spec = model_spec()
        spec["stages"][0]["probability"] = {
            "value": 0.1,
            "confidence": "assumption",
            "source": "Salesforce default stage probability, not yet checked",
            "low": 0.05,
            "high": 0.2,
        }
        self.assertEqual(load_stage_model(spec).stages[0]["probability"].value, 0.1)

    def test_closed_stage_in_the_model(self):
        def mutate(spec):
            spec["stages"][0]["id"] = "Closed Won"

        self.assert_rejected(mutate, "closed stage")

    def test_duplicate_stage(self):
        def mutate(spec):
            spec["stages"][1]["id"] = "early"

        self.assert_rejected(mutate, "duplicate")

    def test_bad_category(self):
        def mutate(spec):
            spec["stages"][0]["category"] = "upside-ish"

        self.assert_rejected(mutate, "category")

    def test_falling_probability_is_noted_not_refused(self):
        spec = model_spec()
        spec["stages"].reverse()
        model = load_stage_model(spec)
        self.assertEqual(len(model.notes), 1)
        self.assertIn("lower probability", model.notes[0])

    def test_default_model_is_all_ranged_assumptions(self):
        model = default_stage_model()
        self.assertTrue(model.is_default)
        for stage in model.stages:
            probability = stage["probability"]
            with self.subTest(stage=stage["id"]):
                self.assertEqual(probability.confidence, "assumption")
                self.assertLess(probability.low, probability.value)
                self.assertGreater(probability.high, probability.value)


class TestShippedExample(unittest.TestCase):
    """Worked by hand from examples/pipeline/; the skills quote these figures."""

    def setUp(self):
        from gtmkit.scoring import load_records

        with open(EXAMPLE_STAGES, encoding="utf-8") as handle:
            model = load_stage_model(json.load(handle))
        self.result = analyze(
            load_records(EXAMPLE_CSV),
            model,
            as_of=AS_OF,
            target=1200000,
            closed=95000,
            period_end=PERIOD_END,
        )

    def test_in_period_totals(self):
        # 16 of 18 deals close by 2026-12-31; Aster and Norland ($600k) do not.
        self.assertEqual(self.result["deals_in_period"], 16)
        self.assertAlmostEqual(self.result["pipeline"], 2404000)
        self.assertEqual(self.result["later"], {"deals": 2, "amount": 600000})

    def test_weighted_forecast(self):
        # By stage: discovery 188k x .08 = 15.04k; qualification 391k x .17 =
        # 66.47k; solution 629k x .31 = 194.99k; proposal 820k x .45 = 369k;
        # negotiation 312k x .70 = 218.4k; closing 64k x .88 = 56.32k.
        self.assertAlmostEqual(self.result["weighted"], 920220, places=6)
        # Ranges: proposal +/-.03, negotiation .55-.85, closing .75-.95.
        self.assertAlmostEqual(self.result["weighted_low"], 840500, places=6)
        self.assertAlmostEqual(self.result["weighted_high"], 996100, places=6)

    def test_coverage_and_landing(self):
        self.assertAlmostEqual(self.result["coverage"], 2404000 / 1105000)
        self.assertAlmostEqual(self.result["required_coverage"], 2404000 / 920220)
        self.assertAlmostEqual(self.result["gap"], -184780, places=6)

    def test_categories(self):
        amounts = {c["category"]: c["amount"] for c in self.result["categories"]}
        self.assertEqual(
            amounts, {"commit": 472000, "best_case": 955000, "pipeline": 977000}
        )

    def test_hygiene_flags_the_lapsed_commit_first(self):
        hygiene = self.result["hygiene"]
        self.assertEqual(len(hygiene), 6)
        self.assertEqual(hygiene[0]["name"], "Ostrava Parcel platform")
        kinds = {f["kind"] for f in hygiene[0]["flags"]}
        self.assertEqual(kinds, {"past_due", "pushed", "stale"})

    def test_evidence_grade(self):
        # Facts carry 276.5k of the 920.22k, the proposal inference 369k.
        evidence = self.result["evidence"]
        self.assertAlmostEqual(evidence["share_fact"], 276500 / 920220)
        self.assertAlmostEqual(evidence["share_inference"], 369000 / 920220)
        self.assertEqual(evidence["grade"], "C")

    def test_markdown_renders_every_section(self):
        markdown = to_markdown(self.result)
        for heading in (
            "## Headline",
            "## Evidence grade: C",
            "## Forecast categories",
            "## Needs a new date or a touch",
            "## Concentration",
            "## Stage model",
        ):
            self.assertIn(heading, markdown)
        self.assertLess(
            markdown.index("## Evidence grade"),
            markdown.index("## Forecast categories"),
        )


class TestCommandLine(unittest.TestCase):
    ARGS = (
        EXAMPLE_CSV,
        "--stages",
        EXAMPLE_STAGES,
        "--target",
        "1200000",
        "--closed",
        "95000",
        "--period-end",
        "2026-12-31",
        "--as-of",
        "2026-10-06",
    )

    def run_main(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_markdown_run(self):
        code, out, _ = self.run_main(*self.ARGS)
        self.assertEqual(code, 0)
        self.assertIn("$184.8k short of target", out)

    def test_json_run(self):
        code, out, _ = self.run_main(*self.ARGS, "--format", "json")
        self.assertEqual(code, 0)
        self.assertAlmostEqual(json.loads(out)["weighted"], 920220, places=6)

    def test_out_writes_a_file(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, "review.md")
            code, out, _ = self.run_main(*self.ARGS, "--out", path)
            with open(path, encoding="utf-8") as handle:
                self.assertIn("# Pipeline review", handle.read())
        self.assertEqual((code, out), (0, ""))

    def test_bad_date_exits_2(self):
        code, _, err = self.run_main(EXAMPLE_CSV, "--as-of", "10/06/2026")
        self.assertEqual(code, 2)
        self.assertIn("YYYY-MM-DD", err)

    def test_missing_file_exits_2(self):
        code, _, err = self.run_main("no-such-pipeline.csv")
        self.assertEqual(code, 2)
        self.assertIn("file not found", err)

    def test_module_runs_as_a_script(self):
        """Exercise ``__main__`` the way a user does, not just main()."""
        completed = subprocess.run(
            [sys.executable, "-m", "gtmkit.pipeline", *self.ARGS, "--format", "json"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout)["deals_in_period"], 16)


if __name__ == "__main__":
    unittest.main()
