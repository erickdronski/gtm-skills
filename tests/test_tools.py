"""Tests for the funnel, sizing, pricing, scoring, and formatting modules."""

import os
import unittest

from gtmkit import fmt
from gtmkit.funnel import FunnelError, parse_stage, plan
from gtmkit.pricing import PricingError, analyze, parse_responses
from gtmkit.scoring import Rubric, RubricError, score_all, score_record
from gtmkit.sizing import SizingError, size

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# --------------------------------------------------------------------------
# Funnel
# --------------------------------------------------------------------------


class TestFunnel(unittest.TestCase):
    def stages(self):
        return [parse_stage("visit:0.1"), parse_stage("opp:0.25")]

    def test_deals_needed_is_target_over_acv(self):
        result = plan(1_000_000, 50_000, self.stages())
        self.assertAlmostEqual(result["deals_needed"], 20.0)

    def test_volumes_chain_backwards_correctly(self):
        result = plan(1_000_000, 50_000, self.stages())
        stages = {s["name"]: s["required_volume"] for s in result["stages"]}
        # 20 deals / 0.25 = 80 opps; 80 / 0.1 = 800 visits.
        self.assertAlmostEqual(stages["opp"], 80.0)
        self.assertAlmostEqual(stages["visit"], 800.0)

    def test_end_to_end_conversion_is_the_product(self):
        result = plan(1_000_000, 50_000, self.stages())
        self.assertAlmostEqual(result["end_to_end_conversion"], 0.025)

    def test_win_rate_increases_required_volume(self):
        without = plan(1_000_000, 50_000, self.stages())
        with_win = plan(1_000_000, 50_000, self.stages(), win_rate=0.5)
        self.assertAlmostEqual(
            with_win["top_of_funnel_volume"],
            without["top_of_funnel_volume"] * 2,
        )

    def test_spend_and_cac(self):
        result = plan(
            1_000_000, 50_000, self.stages(), cost_per_unit=5, cost_stage="visit"
        )
        self.assertAlmostEqual(result["spend"], 4000.0)
        self.assertAlmostEqual(result["cac"], 200.0)

    def test_audience_ceiling_flags_infeasible_plans(self):
        result = plan(
            1_000_000, 50_000, self.stages(), audience_ceiling=100
        )
        self.assertFalse(result["feasible"])
        self.assertIn("not reachable", result["ceiling_note"].lower())

    def test_feasible_plan_has_no_ceiling_note(self):
        result = plan(
            1_000_000, 50_000, self.stages(), audience_ceiling=10_000
        )
        self.assertTrue(result["feasible"])
        self.assertIsNone(result["ceiling_note"])

    def test_rejects_percentage_style_rate(self):
        with self.assertRaises(FunnelError) as ctx:
            parse_stage("mql:25")
        self.assertIn("0.25", str(ctx.exception))

    def test_rejects_malformed_stage(self):
        with self.assertRaises(FunnelError):
            parse_stage("mql")

    def test_rejects_unknown_cost_stage(self):
        with self.assertRaises(FunnelError):
            plan(
                1_000_000,
                50_000,
                self.stages(),
                cost_per_unit=1,
                cost_stage="nope",
            )

    def test_rejects_zero_acv(self):
        with self.assertRaises(FunnelError):
            plan(1_000_000, 0, self.stages())

    def test_rejects_empty_funnel(self):
        with self.assertRaises(FunnelError):
            plan(1_000_000, 50_000, [])


# --------------------------------------------------------------------------
# Sizing
# --------------------------------------------------------------------------


def sizing_spec(**overrides):
    spec = {
        "name": "Test market",
        "currency": "USD",
        "bottom_up": {
            "units": {
                "value": 1000,
                "confidence": "fact",
                "source": "Crunchbase export dated 2026-07-01",
            },
            "attach_rate": {
                "value": 0.5,
                "confidence": "assumption",
                "source": "Between 30% and 70% based on two comparable rollouts",
                "low": 0.3,
                "high": 0.7,
            },
            "annual_price": {
                "value": 100,
                "confidence": "fact",
                "source": "Published list price on the 2026 pricing page",
            },
        },
        "top_down": {
            "market_total": {
                "value": 1_000_000,
                "confidence": "fact",
                "source": "Vendor S-1 filing, market section, dated 2026-03-14",
            },
            "share": {
                "value": 0.05,
                "confidence": "assumption",
                "source": "Anchored on the 3-8% an adjacent category held",
                "low": 0.03,
                "high": 0.08,
            },
        },
        "sam_share": 0.5,
        "som_share": 0.1,
    }
    spec.update(overrides)
    return spec


class TestSizing(unittest.TestCase):
    def test_bottom_up_multiplies_through(self):
        result = size(sizing_spec())
        self.assertAlmostEqual(result["bottom_up"]["tam"], 50_000.0)

    def test_top_down_multiplies_through(self):
        result = size(sizing_spec())
        self.assertAlmostEqual(result["top_down"]["tam"], 50_000.0)

    def test_identical_methods_agree(self):
        result = size(sizing_spec())
        self.assertTrue(result["reconciliation"]["agrees"])
        self.assertAlmostEqual(result["reconciliation"]["ratio"], 1.0)

    def test_wide_divergence_is_called_out_not_averaged(self):
        spec = sizing_spec()
        spec["top_down"]["market_total"]["value"] = 100_000_000
        result = size(spec)
        self.assertFalse(result["reconciliation"]["agrees"])
        self.assertIn("wrong assumption", result["reconciliation"]["verdict"])

    def test_sam_and_som_chain_down(self):
        result = size(sizing_spec())
        self.assertAlmostEqual(result["sam"], 25_000.0)
        self.assertAlmostEqual(result["som"], 2_500.0)

    def test_single_method_reports_that_nothing_checks_it(self):
        spec = sizing_spec()
        del spec["top_down"]
        result = size(spec)
        self.assertFalse(result["reconciliation"]["possible"])
        self.assertIn("assertion", result["reconciliation"]["verdict"])

    def test_requires_at_least_one_method(self):
        with self.assertRaises(SizingError):
            size({"name": "x"})

    def test_rejects_percentage_style_share(self):
        with self.assertRaises(SizingError):
            size(sizing_spec(sam_share=50))

    def test_enforces_the_evidence_rules(self):
        spec = sizing_spec()
        spec["bottom_up"]["units"]["source"] = "industry standard"
        with self.assertRaises(SizingError):
            size(spec)


# --------------------------------------------------------------------------
# Pricing
# --------------------------------------------------------------------------


def response(tc, c, e, te):
    return {
        "too_cheap": tc,
        "cheap": c,
        "expensive": e,
        "too_expensive": te,
    }


class TestPricing(unittest.TestCase):
    def sample(self, n=60):
        rows = []
        for i in range(n):
            offset = i % 10
            rows.append(response(20 + offset, 40 + offset, 80 + offset, 120 + offset))
        return rows

    def test_rejects_non_monotonic_responses(self):
        valid, rejected = parse_responses([response(100, 50, 30, 10)])
        self.assertEqual(len(valid), 0)
        self.assertEqual(len(rejected), 1)
        self.assertIn("ascending order", rejected[0]["reason"])

    def test_rejects_non_numeric(self):
        valid, rejected = parse_responses([response("n/a", 40, 80, 120)])
        self.assertEqual(len(rejected), 1)
        self.assertEqual(rejected[0]["reason"], "non-numeric price")

    def test_rejects_negative_prices(self):
        valid, rejected = parse_responses([response(-5, 40, 80, 120)])
        self.assertEqual(len(rejected), 1)

    def test_accepts_monotonic_responses(self):
        valid, rejected = parse_responses([response(10, 20, 30, 40)])
        self.assertEqual(len(valid), 1)
        self.assertEqual(len(rejected), 0)

    def test_missing_column_is_a_hard_error(self):
        with self.assertRaises(PricingError) as ctx:
            parse_responses([{"too_cheap": 1, "cheap": 2}])
        self.assertIn("missing column", str(ctx.exception))

    def test_intersections_are_ordered(self):
        result = analyze(self.sample())
        points = result["points"]
        self.assertLess(
            points["point_of_marginal_cheapness"],
            points["point_of_marginal_expensiveness"],
        )

    def test_acceptable_range_matches_the_two_marginal_points(self):
        result = analyze(self.sample())
        self.assertEqual(
            result["acceptable_range"]["low"],
            result["points"]["point_of_marginal_cheapness"],
        )

    def test_small_samples_are_labelled_indicative(self):
        result = analyze(self.sample(n=10))
        self.assertEqual(result["sample"]["reliability"], "indicative only")
        self.assertIn("not to set a price", result["sample"]["reliability_note"])

    def test_large_samples_are_labelled_strong(self):
        result = analyze(self.sample(n=220))
        self.assertEqual(result["sample"]["reliability"], "strong")

    def test_rejected_rows_are_counted_not_hidden(self):
        rows = self.sample() + [response(100, 50, 30, 10)]
        result = analyze(rows)
        self.assertEqual(result["sample"]["rejected"], 1)
        self.assertEqual(len(result["rejected_rows"]), 1)

    def test_too_few_usable_responses_raises(self):
        with self.assertRaises(PricingError):
            analyze([response(10, 20, 30, 40)])


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------


def rubric_dict(**overrides):
    data = {
        "name": "Test rubric",
        "scale": 5,
        "min_coverage": 0.6,
        "criteria": [
            {
                "id": "size",
                "label": "Size",
                "weight": 3,
                "type": "numeric",
                "bands": [{"min": 500, "score": 5}, {"min": 100, "score": 3}],
            },
            {
                "id": "sponsor",
                "label": "Sponsor",
                "weight": 2,
                "type": "boolean",
                "true_score": 5,
                "false_score": 0,
            },
            {
                "id": "industry",
                "label": "Industry",
                "weight": 1,
                "type": "categorical",
                "map": {"logistics": 5, "retail": 2},
                "default": 0,
            },
        ],
    }
    data.update(overrides)
    return data


class TestScoring(unittest.TestCase):
    def setUp(self):
        self.rubric = Rubric(rubric_dict())

    def test_perfect_record_scores_one(self):
        result = score_record(
            self.rubric,
            {"size": 900, "sponsor": "true", "industry": "logistics"},
        )
        self.assertAlmostEqual(result["fit"], 1.0)
        self.assertAlmostEqual(result["coverage"], 1.0)
        self.assertEqual(result["tier"], "A")

    def test_missing_data_lowers_coverage_not_fit(self):
        """The central behavior: unknown must not read as bad."""
        known = score_record(
            self.rubric, {"size": 900, "sponsor": "true", "industry": "logistics"}
        )
        partial = score_record(self.rubric, {"size": 900, "sponsor": "true"})
        self.assertAlmostEqual(partial["fit"], known["fit"])
        self.assertLess(partial["coverage"], known["coverage"])

    def test_low_coverage_is_held_back_from_ranking(self):
        result = score_record(self.rubric, {"size": 900})
        self.assertEqual(result["tier"], "UNKNOWN")
        self.assertIn("unresearched", result["confidence_note"])

    def test_blank_and_placeholder_values_count_as_missing(self):
        for placeholder in ("", "unknown", "N/A", "-", "?"):
            with self.subTest(placeholder=placeholder):
                result = score_record(
                    self.rubric,
                    {"size": 900, "sponsor": "true", "industry": placeholder},
                )
                self.assertIn("Industry", result["missing_criteria"])

    def test_numeric_below_all_bands_scores_zero(self):
        result = score_record(
            self.rubric, {"size": 10, "sponsor": "true", "industry": "logistics"}
        )
        detail = {d["id"]: d["score"] for d in result["detail"]}
        self.assertEqual(detail["size"], 0.0)

    def test_categorical_falls_back_to_default(self):
        result = score_record(
            self.rubric,
            {"size": 900, "sponsor": "true", "industry": "aerospace"},
        )
        detail = {d["id"]: d["score"] for d in result["detail"]}
        self.assertEqual(detail["industry"], 0.0)

    def test_numeric_parsing_tolerates_formatting(self):
        result = score_record(
            self.rubric,
            {"size": "1,200", "sponsor": "yes", "industry": "logistics"},
        )
        self.assertAlmostEqual(result["fit"], 1.0)

    def test_disqualifier_removes_from_ranking_with_a_reason(self):
        rubric = Rubric(
            rubric_dict(
                disqualifiers=[
                    {
                        "field": "size",
                        "op": "<",
                        "value": 50,
                        "reason": "Below the minimum viable deployment size",
                    }
                ]
            )
        )
        result = score_record(
            rubric, {"size": 10, "sponsor": "true", "industry": "logistics"}
        )
        self.assertTrue(result["disqualified"])
        self.assertEqual(result["tier"], "OUT")
        self.assertIn("minimum viable", result["disqualifier_reason"])

    def test_disqualifier_not_in_operator(self):
        rubric = Rubric(
            rubric_dict(
                disqualifiers=[
                    {
                        "field": "region",
                        "op": "not in",
                        "value": ["na", "emea"],
                        "reason": "No data residency coverage in that region",
                    }
                ]
            )
        )
        result = score_record(rubric, {"size": 900, "region": "apac"})
        self.assertTrue(result["disqualified"])

    def test_ranking_puts_researched_records_first(self):
        records = [
            {"name": "high-fit-unresearched", "size": 900},
            {
                "name": "lower-fit-researched",
                "size": 200,
                "sponsor": "true",
                "industry": "retail",
            },
        ]
        ranked = score_all(self.rubric, records)
        self.assertEqual(ranked[0]["record"]["name"], "lower-fit-researched")

    def test_rejects_zero_weight(self):
        data = rubric_dict()
        data["criteria"][0]["weight"] = 0
        with self.assertRaises(RubricError):
            Rubric(data)

    def test_rejects_score_outside_scale(self):
        data = rubric_dict()
        data["criteria"][0]["bands"][0]["score"] = 9
        with self.assertRaises(RubricError):
            Rubric(data)

    def test_rejects_disqualifier_without_reason(self):
        with self.assertRaises(RubricError) as ctx:
            Rubric(
                rubric_dict(
                    disqualifiers=[{"field": "size", "op": "<", "value": 5}]
                )
            )
        self.assertIn("reason", str(ctx.exception))

    def test_rejects_duplicate_criterion_ids(self):
        data = rubric_dict()
        data["criteria"].append(dict(data["criteria"][0]))
        with self.assertRaises(RubricError):
            Rubric(data)


# --------------------------------------------------------------------------
# Formatting
# --------------------------------------------------------------------------


class TestFormatting(unittest.TestCase):
    def test_currency_compacts_by_magnitude(self):
        self.assertEqual(fmt.fmt_currency(1_260_000), "$1.3M")
        self.assertEqual(fmt.fmt_currency(12_500), "$12.5k")
        self.assertEqual(fmt.fmt_currency(1_200_000_000), "$1.2B")
        self.assertEqual(fmt.fmt_currency(250), "$250")

    def test_currency_handles_negatives(self):
        self.assertEqual(fmt.fmt_currency(-1_260_000), "-$1.3M")

    def test_exact_ties_round_half_to_even(self):
        """Display rounding follows Python/IEEE, not half-up.

        Pinned rather than "fixed" because these strings are for reading, not
        for arithmetic — every computed number in this package keeps full
        precision internally, and forcing half-up here would only move which
        edge case looks surprising. If you are reconciling a rendered figure
        against a spreadsheet and it differs by one in the last displayed
        digit, this is why.
        """
        self.assertEqual(fmt.fmt_currency(1_250_000), "$1.2M")
        self.assertEqual(fmt.fmt_currency(1_350_000), "$1.4M")

    def test_currency_precise_keeps_cents(self):
        self.assertEqual(fmt.fmt_currency(1234.5, precise=True), "$1,234.50")

    def test_currency_precise_widens_below_a_dollar(self):
        """A cost-per-impression must not round to two decimals."""
        self.assertEqual(fmt.fmt_currency(0.022, precise=True), "$0.0220")

    def test_currency_uses_symbols(self):
        self.assertTrue(fmt.fmt_currency(100, "EUR").startswith("€"))
        self.assertTrue(fmt.fmt_currency(100, "XYZ").startswith("XYZ"))

    def test_none_renders_as_na_not_zero(self):
        self.assertEqual(fmt.fmt_currency(None), "n/a")
        self.assertEqual(fmt.fmt_pct(None), "n/a")
        self.assertEqual(fmt.fmt_multiple(None), "n/a")

    def test_pct_precision_adapts(self):
        self.assertEqual(fmt.fmt_pct(0.25), "25%")
        self.assertEqual(fmt.fmt_pct(0.075), "7.5%")

    def test_tiny_pct_does_not_collapse_to_zero(self):
        """A 0.0004% conversion rate is a number, not a zero."""
        self.assertNotEqual(fmt.fmt_pct(0.00000392), "0%")
        self.assertEqual(fmt.fmt_pct(0.00000392), "0.0004%")

    def test_exact_zero_is_zero(self):
        self.assertEqual(fmt.fmt_pct(0), "0%")

    def test_periods_render_as_years_and_months(self):
        self.assertEqual(fmt.fmt_periods(1.17), "1 yr 2 mo")
        self.assertEqual(fmt.fmt_periods(2.0), "2 yr")
        self.assertEqual(fmt.fmt_periods(0.5), "6 mo")
        self.assertEqual(fmt.fmt_periods(0), "immediate")

    def test_periods_none_is_explicit(self):
        self.assertIn("never", fmt.fmt_periods(None))

    def test_month_rounding_carries_to_a_year(self):
        self.assertEqual(fmt.fmt_periods(1.999), "2 yr")

    def test_table_escapes_pipes(self):
        rendered = fmt.table(["A"], [["x | y"]])
        self.assertIn("\\|", rendered)

    def test_table_collapses_newlines(self):
        rendered = fmt.table(["A"], [["x\ny"]])
        self.assertNotIn("\n", rendered.splitlines()[2])

    def test_table_pads_columns(self):
        rendered = fmt.table(["Name", "V"], [["long-value", "1"]])
        header, separator, row = rendered.splitlines()
        self.assertEqual(len(header), len(row))
        self.assertEqual(len(header), len(separator))

    def test_empty_table_is_explicit(self):
        self.assertEqual(fmt.table(["A"], []), "_No rows._")

    def test_bar_clamps(self):
        self.assertEqual(len(fmt.bar(2.0, width=10)), 10)
        self.assertEqual(len(fmt.bar(-1.0, width=10)), 10)


if __name__ == "__main__":
    unittest.main()
