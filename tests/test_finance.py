"""Tests for the finance primitives.

These are the numbers that end up in front of a CFO, so the expected values
here are hand-checked against closed-form results rather than snapshotted from
the implementation. A snapshot test would have happily locked in the off-by-one
discount error these tests exist to prevent.
"""

import unittest

from gtmkit import finance


class TestPresentValue(unittest.TestCase):
    def test_period_zero_is_undiscounted(self):
        self.assertEqual(finance.present_value(1000, 0.1, 0), 1000)

    def test_discounting_matches_closed_form(self):
        # 1000 / 1.1^3 = 751.3148...
        self.assertAlmostEqual(
            finance.present_value(1000, 0.1, 3), 751.3148009, places=6
        )

    def test_rejects_impossible_rate(self):
        with self.assertRaises(finance.InvalidCashFlows):
            finance.present_value(100, -1.0, 1)

    def test_rejects_negative_period(self):
        with self.assertRaises(finance.InvalidCashFlows):
            finance.present_value(100, 0.1, -1)


class TestNPV(unittest.TestCase):
    def test_known_value(self):
        # -1000 + 500/1.1 + 500/1.1^2 + 500/1.1^3
        #   = -1000 + 454.545455 + 413.223140 + 375.657400
        #   = 243.425995
        result = finance.npv(0.1, [-1000, 500, 500, 500])
        self.assertAlmostEqual(result, 243.4259955, places=6)

    def test_zero_rate_is_plain_sum(self):
        self.assertAlmostEqual(finance.npv(0.0, [-100, 60, 60]), 20.0)

    def test_textbook_convention_differs_from_excel(self):
        """Period 0 must not be discounted.

        If this test fails, every business case built on the library is
        overstating or understating by one period of discounting — the single
        most common error in circulated models.
        """
        flows = [-1000, 1100]
        # Textbook: -1000 + 1100/1.1 = 0
        self.assertAlmostEqual(finance.npv(0.1, flows), 0.0, places=9)

    def test_requires_two_periods(self):
        with self.assertRaises(finance.InvalidCashFlows):
            finance.npv(0.1, [100])

    def test_rejects_non_numeric(self):
        with self.assertRaises(finance.InvalidCashFlows):
            finance.npv(0.1, [-100, "500"])

    def test_rejects_booleans(self):
        with self.assertRaises(finance.InvalidCashFlows):
            finance.npv(0.1, [-100, True])


class TestIRR(unittest.TestCase):
    def test_irr_zeroes_the_npv(self):
        flows = [-1000, 400, 400, 400]
        rate = finance.irr(flows)
        self.assertIsNotNone(rate)
        self.assertAlmostEqual(finance.npv(rate, flows), 0.0, places=5)

    def test_known_simple_case(self):
        # -100 today, 110 in one period => exactly 10%.
        self.assertAlmostEqual(finance.irr([-100, 110]), 0.10, places=6)

    def test_all_positive_has_no_irr(self):
        self.assertIsNone(finance.irr([100, 100, 100]))

    def test_all_negative_has_no_irr(self):
        self.assertIsNone(finance.irr([-100, -100]))

    def test_returns_none_rather_than_diverging(self):
        # Far outside any bracketable range.
        self.assertIsNone(finance.irr([-1, 0.0000001]))

    def test_sign_changes_flags_ambiguity(self):
        self.assertEqual(finance.sign_changes([-100, 300, -250]), 2)
        self.assertEqual(finance.sign_changes([-100, 50, 50]), 1)

    def test_zeros_do_not_count_as_sign_changes(self):
        self.assertEqual(finance.sign_changes([-100, 0, 0, 200]), 1)


class TestPayback(unittest.TestCase):
    def test_interpolates_within_the_crossing_period(self):
        # -100, +50, +50 => cumulative -100, -50, 0 => pays back at exactly 2.
        self.assertAlmostEqual(finance.payback_period([-100, 50, 50]), 2.0)

    def test_fractional_payback(self):
        # -100, +40, +80 => cumulative -100, -60, +20.
        # Crossing inside period 2: 60/80 of the way => 1.75.
        self.assertAlmostEqual(finance.payback_period([-100, 40, 80]), 1.75)

    def test_never_pays_back_returns_none(self):
        self.assertIsNone(finance.payback_period([-100, 10, 10]))

    def test_discounted_payback_is_later_than_undiscounted(self):
        flows = [-1000, 400, 400, 400, 400]
        plain = finance.payback_period(flows)
        discounted = finance.discounted_payback_period(0.12, flows)
        self.assertIsNotNone(plain)
        self.assertIsNotNone(discounted)
        self.assertGreater(
            discounted,
            plain,
            "discounting must make payback later, never earlier",
        )

    def test_immediate_payback(self):
        self.assertEqual(finance.payback_period([100, 50]), 0.0)


class TestBreakEven(unittest.TestCase):
    def test_multiplier_scales_benefits_to_zero_npv(self):
        benefits = [0, 500, 500, 500]
        costs = [1000, 0, 0, 0]
        multiplier = finance.break_even_multiplier(0.1, benefits, costs)
        self.assertIsNotNone(multiplier)
        scaled = [b * multiplier - c for b, c in zip(benefits, costs)]
        self.assertAlmostEqual(finance.npv(0.1, scaled), 0.0, places=6)

    def test_multiplier_below_one_means_slack(self):
        benefits = [0, 900, 900, 900]
        costs = [1000, 0, 0, 0]
        multiplier = finance.break_even_multiplier(0.1, benefits, costs)
        self.assertLess(multiplier, 1.0)

    def test_multiplier_above_one_means_no_margin(self):
        benefits = [0, 100, 100, 100]
        costs = [1000, 0, 0, 0]
        multiplier = finance.break_even_multiplier(0.1, benefits, costs)
        self.assertGreater(multiplier, 1.0)

    def test_no_benefits_returns_none(self):
        self.assertIsNone(finance.break_even_multiplier(0.1, [0, 0], [100, 0]))

    def test_no_costs_breaks_even_immediately(self):
        self.assertEqual(finance.break_even_multiplier(0.1, [0, 100], [0, 0]), 0.0)


class TestRates(unittest.TestCase):
    def test_monthly_compounds_not_adds(self):
        # 1% monthly is 12.6825% annually, not 12%.
        self.assertAlmostEqual(
            finance.annualized_rate(0.01, 12), 0.1268250301, places=8
        )

    def test_round_trip(self):
        annual = 0.15
        monthly = finance.periodic_rate(annual, 12)
        self.assertAlmostEqual(finance.annualized_rate(monthly, 12), annual, places=10)

    def test_rejects_zero_periods(self):
        with self.assertRaises(finance.InvalidCashFlows):
            finance.annualized_rate(0.01, 0)


class TestSummarize(unittest.TestCase):
    def setUp(self):
        self.benefits = [0, 400, 600, 600]
        self.costs = [500, 100, 100, 100]
        self.net = [b - c for b, c in zip(self.benefits, self.costs)]

    def test_gross_flows_beat_inferring_from_net(self):
        """A year with both benefit and cost must not net to 'benefit'."""
        with_gross = finance.summarize(
            self.net, 0.1, benefit_flows=self.benefits, cost_flows=self.costs
        )
        without = finance.summarize(self.net, 0.1)
        self.assertEqual(with_gross["total_benefit"], 1600)
        self.assertEqual(with_gross["total_investment"], 800)
        # The inferred version undercounts both sides.
        self.assertLess(without["total_benefit"], with_gross["total_benefit"])

    def test_reports_nulls_rather_than_fabricating(self):
        result = finance.summarize([100, 100], 0.1)
        self.assertIsNone(result["irr_per_period"])
        self.assertIsNone(result["irr_annual"])

    def test_flags_ambiguous_irr(self):
        result = finance.summarize([-100, 300, -250], 0.1)
        self.assertTrue(result["irr_is_ambiguous"])

    def test_all_keys_present(self):
        result = finance.summarize(self.net, 0.1)
        for key in (
            "npv",
            "irr_annual",
            "roi",
            "payback_periods",
            "discounted_payback_periods",
            "break_even_benefit_multiplier",
            "total_investment",
            "total_benefit",
        ):
            self.assertIn(key, result)


if __name__ == "__main__":
    unittest.main()
