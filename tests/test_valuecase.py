"""Tests for the business-case model, including the shipped example.

The example test matters more than it looks: the README quotes that output, and
a repo whose README shows numbers the code no longer produces is worse than one
with no README at all.
"""

import json
import os
import unittest

from gtmkit import finance
from gtmkit.valuecase import SpecError, load_spec, validate_spec

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXAMPLE = os.path.join(
    REPO_ROOT, "examples", "value-case", "northwind-support-deflection.json"
)


def minimal_spec(**overrides):
    spec = {
        "name": "Test case",
        "currency": "USD",
        "horizon_years": 3,
        "discount_rate_annual": 0.12,
        "drivers": [
            {
                "id": "d1",
                "label": "Driver one",
                "formula": "volume * rate * unit_value",
                "inputs": {
                    "volume": {
                        "value": 1000,
                        "confidence": "fact",
                        "source": "Warehouse export dated 2026-01-01",
                    },
                    "rate": {
                        "value": 0.2,
                        "confidence": "assumption",
                        "source": "Observed between 10% and 30% at two peers",
                        "low": 0.1,
                        "high": 0.3,
                    },
                    "unit_value": {
                        "value": 50,
                        "confidence": "inference",
                        "source": "Loaded cost of $104,000 over 2,080 hours",
                    },
                },
                "ramp": [0.5, 1.0, 1.0],
                "realization": 0.8,
            }
        ],
        "costs": [
            {"id": "sub", "label": "Subscription", "schedule": [0, 3000, 3000, 3000]},
            {"id": "impl", "label": "Implementation", "schedule": [5000, 0, 0, 0]},
        ],
    }
    spec.update(overrides)
    return spec


class TestCashFlows(unittest.TestCase):
    def setUp(self):
        self.case = validate_spec(minimal_spec())

    def test_period_zero_has_no_benefit(self):
        self.assertEqual(self.case.benefit_flows()[0], 0.0)

    def test_ramp_and_realization_both_apply(self):
        # 1000 * 0.2 * 50 = 10000 run rate; year 1 = 10000 * 0.5 ramp * 0.8
        self.assertAlmostEqual(self.case.benefit_flows()[1], 4000.0)
        self.assertAlmostEqual(self.case.benefit_flows()[2], 8000.0)

    def test_schedule_length_matches_horizon(self):
        self.assertEqual(len(self.case.net_flows()), 4)

    def test_net_is_benefit_minus_cost(self):
        benefits = self.case.benefit_flows()
        costs = self.case.cost_flows()
        net = self.case.net_flows()
        for i in range(len(net)):
            self.assertAlmostEqual(net[i], benefits[i] - costs[i])

    def test_ramp_shorter_than_horizon_holds_last_value(self):
        spec = minimal_spec()
        spec["drivers"][0]["ramp"] = [0.5]
        case = validate_spec(spec)
        flows = case.benefit_flows()
        self.assertAlmostEqual(flows[1], flows[2])
        self.assertAlmostEqual(flows[2], flows[3])


class TestAttribution(unittest.TestCase):
    def setUp(self):
        self.case = validate_spec(minimal_spec())

    def test_shares_sum_to_one(self):
        shares = self.case.drivers[0].input_shares()
        self.assertAlmostEqual(sum(shares.values()), 1.0, places=9)

    def test_pure_product_splits_evenly(self):
        """``a * b * c`` gives each input equal elasticity, so equal share."""
        shares = self.case.drivers[0].input_shares()
        for name, share in shares.items():
            with self.subTest(name=name):
                self.assertAlmostEqual(share, 1.0 / 3.0, places=4)

    def test_insensitive_input_gets_a_small_share(self):
        spec = minimal_spec()
        spec["drivers"][0]["formula"] = "volume * rate * unit_value + tiny"
        spec["drivers"][0]["inputs"]["tiny"] = {
            "value": 1,
            "confidence": "assumption",
            "source": "Rounding allowance agreed with finance in July 2026",
            "low": 0,
            "high": 2,
        }
        case = validate_spec(spec)
        shares = case.drivers[0].input_shares()
        self.assertLess(shares["tiny"], 0.01)

    def test_evidence_grade_discriminates(self):
        """One soft input among three must not grade the same as all-soft."""
        mixed = validate_spec(minimal_spec()).evidence()

        spec = minimal_spec()
        for name in spec["drivers"][0]["inputs"]:
            spec["drivers"][0]["inputs"][name] = {
                "value": spec["drivers"][0]["inputs"][name]["value"],
                "confidence": "assumption",
                "source": "Bounded by the range seen across two peer accounts",
                "low": spec["drivers"][0]["inputs"][name]["value"] * 0.5,
                "high": spec["drivers"][0]["inputs"][name]["value"] * 1.5,
            }
        all_soft = validate_spec(spec).evidence()

        self.assertGreater(mixed["measured_share"], all_soft["measured_share"])
        self.assertEqual(all_soft["grade"], "F")
        self.assertNotEqual(mixed["grade"], "F")

    def test_attribution_totals_match_driver_npv(self):
        by_input = self.case.evidence_by_input()
        attributed = sum(row["npv_attributed"] for row in by_input)
        driver_npv = sum(row["npv"] for row in self.case.driver_contributions())
        self.assertAlmostEqual(attributed, driver_npv, places=6)


class TestSensitivity(unittest.TestCase):
    def setUp(self):
        self.case = validate_spec(minimal_spec())

    def test_only_ranged_inputs_appear(self):
        rows = self.case.sensitivity()
        self.assertEqual([r["input"] for r in rows], ["rate"])

    def test_low_bound_produces_lower_npv(self):
        row = self.case.sensitivity()[0]
        self.assertLess(row["npv_low"], row["npv_high"])

    def test_swing_is_absolute(self):
        row = self.case.sensitivity()[0]
        self.assertGreaterEqual(row["swing"], 0)

    def test_floor_case_is_no_better_than_base(self):
        floor = self.case.floor_case()
        self.assertLessEqual(floor["npv"], self.case.npv_with())

    def test_sorted_by_swing_descending(self):
        spec = minimal_spec()
        spec["drivers"][0]["inputs"]["unit_value"] = {
            "value": 50,
            "confidence": "assumption",
            "source": "Loaded cost varies between $40 and $60 by region",
            "low": 40,
            "high": 60,
        }
        rows = validate_spec(spec).sensitivity()
        swings = [r["swing"] for r in rows]
        self.assertEqual(swings, sorted(swings, reverse=True))


class TestSpecValidation(unittest.TestCase):
    def test_rejects_missing_name(self):
        spec = minimal_spec()
        del spec["name"]
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_rejects_percentage_style_discount_rate(self):
        with self.assertRaises(SpecError) as ctx:
            validate_spec(minimal_spec(discount_rate_annual=12))
        self.assertIn("decimal", str(ctx.exception))

    def test_rejects_absurd_horizon(self):
        with self.assertRaises(SpecError):
            validate_spec(minimal_spec(horizon_years=25))

    def test_rejects_benefit_only_case(self):
        spec = minimal_spec()
        spec["costs"] = []
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("wish list", str(ctx.exception))

    def test_rejects_undefined_formula_variable(self):
        spec = minimal_spec()
        spec["drivers"][0]["formula"] = "volume * rate * missing_input"
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("missing_input", str(ctx.exception))

    def test_rejects_declared_but_unused_input(self):
        """A stale ledger misleads reviewers as much as a stale formula."""
        spec = minimal_spec()
        spec["drivers"][0]["inputs"]["orphan"] = {
            "value": 1,
            "confidence": "fact",
            "source": "Left over from an earlier version of this model",
        }
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("never uses", str(ctx.exception))

    def test_rejects_wrong_length_cost_schedule(self):
        spec = minimal_spec()
        spec["costs"][0]["schedule"] = [0, 100]
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("schedule entries", str(ctx.exception))

    def test_rejects_negative_cost_entry(self):
        spec = minimal_spec()
        spec["costs"][0]["schedule"] = [0, -100, 0, 0]
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_rejects_realization_above_one(self):
        spec = minimal_spec()
        spec["drivers"][0]["realization"] = 1.4
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_rejects_duplicate_driver_ids(self):
        spec = minimal_spec()
        spec["drivers"].append(dict(spec["drivers"][0]))
        with self.assertRaises(SpecError):
            validate_spec(spec)

    def test_propagates_evidence_errors_with_driver_context(self):
        spec = minimal_spec()
        spec["drivers"][0]["inputs"]["rate"]["source"] = "industry standard"
        with self.assertRaises(SpecError) as ctx:
            validate_spec(spec)
        self.assertIn("d1", str(ctx.exception))


class TestShippedExample(unittest.TestCase):
    """The example the README quotes must keep loading and keep its shape."""

    def setUp(self):
        self.case = load_spec(EXAMPLE)

    def test_loads(self):
        self.assertEqual(self.case.horizon, 3)
        self.assertEqual(len(self.case.drivers), 3)

    def test_is_internally_consistent(self):
        """Headcount and tickets-per-agent must not contradict each other.

        The first draft of this example claimed 62 agents while deriving cost
        per ticket from 6,400 tickets per agent-year against 124,800 tickets —
        implying 20 agents. Exactly the kind of quiet inconsistency this whole
        pack exists to catch, so it is pinned here.
        """
        attrition = [d for d in self.case.drivers if d.id == "attrition"][0]
        deflection = [d for d in self.case.drivers if d.id == "deflection"][0]
        agents = attrition.inputs["agents"].value
        tickets = deflection.inputs["tickets_per_year"].value
        implied_per_agent = tickets / agents
        self.assertTrue(
            5000 <= implied_per_agent <= 8000,
            "implied %.0f tickets per agent-year contradicts the stated 6,400"
            % implied_per_agent,
        )

    def test_case_is_positive_but_not_trivially_so(self):
        summary = self.case.summary()
        self.assertGreater(summary["npv"], 0)
        self.assertIsNotNone(summary["discounted_payback_periods"])
        # A margin of safety this thin is the interesting teaching case.
        self.assertLess(summary["break_even_benefit_multiplier"], 1.0)

    def test_floor_case_goes_negative(self):
        """The example is chosen so the stress test actually bites."""
        self.assertFalse(self.case.floor_case()["still_positive"])

    def test_top_assumption_flips_the_decision(self):
        top = self.case.sensitivity()[0]
        self.assertTrue(top["flips_decision"])
        self.assertEqual(top["input"], "deflection_rate")

    def test_renders_markdown_without_error(self):
        markdown = self.case.to_markdown()
        for heading in (
            "## Headline",
            "## Evidence grade",
            "## Value drivers",
            "## Cash flow",
            "## What would have to be true",
            "## Floor case",
            "## Assumption ledger",
        ):
            self.assertIn(heading, markdown)

    def test_serializes_to_json(self):
        payload = json.dumps(self.case.to_dict())
        self.assertGreater(len(payload), 1000)

    def test_no_pipe_characters_leak_into_tables(self):
        """A source string containing a pipe would silently corrupt a table."""
        for line in self.case.to_markdown().splitlines():
            if line.startswith("|"):
                # Escaped pipes are fine; raw ones inside a cell are not.
                self.assertNotIn("||", line)


if __name__ == "__main__":
    unittest.main()
