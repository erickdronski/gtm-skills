"""Tests for the assumption ledger.

The rules encoded here are opinionated by design. They exist to make the most
common way a business case fails — a confident number with nothing behind it —
into a hard error at authoring time rather than a soft embarrassment in a
review meeting.
"""

import unittest

from gtmkit.evidence import (
    EvidenceError,
    grade_evidence,
    validate_input,
    weakest_confidence,
    weasel_phrases,
)


def make(**overrides):
    base = {
        "value": 100,
        "confidence": "fact",
        "source": "Salesforce closed-won export dated 2026-07-01",
    }
    base.update(overrides)
    return base


class TestValidateInput(unittest.TestCase):
    def test_accepts_a_well_formed_fact(self):
        result = validate_input("acv", make())
        self.assertEqual(result.value, 100.0)
        self.assertEqual(result.confidence, "fact")

    def test_requires_a_value(self):
        with self.assertRaises(EvidenceError):
            validate_input("acv", {"confidence": "fact", "source": "x" * 20})

    def test_rejects_non_numeric_value(self):
        with self.assertRaises(EvidenceError):
            validate_input("acv", make(value="lots"))

    def test_rejects_boolean_value(self):
        with self.assertRaises(EvidenceError):
            validate_input("acv", make(value=True))

    def test_requires_a_known_confidence_level(self):
        with self.assertRaises(EvidenceError) as ctx:
            validate_input("acv", make(confidence="pretty sure"))
        self.assertIn("fact", str(ctx.exception))

    def test_requires_a_source(self):
        with self.assertRaises(EvidenceError):
            validate_input("acv", {"value": 1, "confidence": "fact"})

    def test_rejects_a_source_too_short_to_verify(self):
        with self.assertRaises(EvidenceError) as ctx:
            validate_input("acv", make(source="CRM"))
        self.assertIn("too vague", str(ctx.exception))


class TestWeaselDetection(unittest.TestCase):
    """The phrases that get business cases dismissed, rejected at the door."""

    def test_catches_common_unfalsifiable_sources(self):
        for source in (
            "industry standard",
            "Industry benchmark",
            "research shows this is typical",
            "best practice",
            "internal data",
            "Gartner",
            "analyst report",
            "estimated",
            "TBD",
            "assumed",
        ):
            with self.subTest(source=source):
                self.assertTrue(
                    weasel_phrases(source),
                    "%r should be flagged as unfalsifiable" % source,
                )

    def test_does_not_flag_specific_sources(self):
        for source in (
            "Zendesk ticket export, 2025-01-01 to 2025-12-31",
            "Fully loaded cost of $82,000 divided by 2,080 hours",
            "Three reference customers reported 14%, 19%, and 24%",
            "Q2 2026 CX operating review, slide 14",
        ):
            with self.subTest(source=source):
                self.assertFalse(
                    weasel_phrases(source),
                    "%r is specific and should pass" % source,
                )

    def test_validate_input_rejects_weasel_sources(self):
        with self.assertRaises(EvidenceError) as ctx:
            validate_input("rate", make(source="industry standard"))
        self.assertIn("unfalsifiable", str(ctx.exception))


class TestRangeRules(unittest.TestCase):
    def test_assumption_requires_a_range(self):
        with self.assertRaises(EvidenceError) as ctx:
            validate_input(
                "deflection",
                make(
                    value=0.2,
                    confidence="assumption",
                    source="Observed 14-24% across three reference customers",
                ),
            )
        self.assertIn("low", str(ctx.exception))

    def test_assumption_with_a_range_is_accepted(self):
        result = validate_input(
            "deflection",
            make(
                value=0.2,
                confidence="assumption",
                source="Observed 14-24% across three reference customers",
                low=0.14,
                high=0.24,
            ),
        )
        self.assertEqual(result.range, (0.14, 0.24))
        self.assertAlmostEqual(result.swing, 0.10)

    def test_fact_does_not_require_a_range(self):
        result = validate_input("acv", make())
        self.assertEqual(result.range, (100.0, 100.0))
        self.assertEqual(result.swing, 0.0)

    def test_rejects_inverted_range(self):
        with self.assertRaises(EvidenceError):
            validate_input(
                "r",
                make(confidence="assumption", low=10, high=1, value=5,
                     source="Bounded by the two observed extremes in FY25"),
            )

    def test_rejects_base_outside_its_own_range(self):
        with self.assertRaises(EvidenceError) as ctx:
            validate_input(
                "r",
                make(
                    value=50,
                    confidence="assumption",
                    low=1,
                    high=10,
                    source="Bounded by the two observed extremes in FY25",
                ),
            )
        self.assertIn("outside its own range", str(ctx.exception))


class TestGrading(unittest.TestCase):
    def test_all_facts_grades_a(self):
        result = grade_evidence([("fact", 100), ("fact", 50)])
        self.assertEqual(result["grade"], "A")
        self.assertEqual(result["share_fact"], 1.0)

    def test_all_assumptions_grades_f(self):
        result = grade_evidence([("assumption", 100)])
        self.assertEqual(result["grade"], "F")
        self.assertEqual(result["share_assumption"], 1.0)

    def test_inference_counts_half(self):
        result = grade_evidence([("inference", 100)])
        self.assertAlmostEqual(result["measured_share"], 0.5)
        self.assertEqual(result["grade"], "C")

    def test_even_thirds_lands_mid_scale(self):
        result = grade_evidence(
            [("fact", 100), ("inference", 100), ("assumption", 100)]
        )
        self.assertAlmostEqual(result["measured_share"], 0.5, places=6)
        self.assertEqual(result["grade"], "C")

    def test_weights_by_magnitude_not_count(self):
        """One large assumption must outweigh several trivial facts."""
        result = grade_evidence(
            [("fact", 1), ("fact", 1), ("assumption", 1000)]
        )
        self.assertEqual(result["grade"], "F")

    def test_uses_absolute_value_so_negatives_do_not_cancel(self):
        result = grade_evidence([("fact", -100), ("assumption", 100)])
        self.assertAlmostEqual(result["share_fact"], 0.5)

    def test_empty_grades_na(self):
        result = grade_evidence([])
        self.assertEqual(result["grade"], "n/a")

    def test_zero_value_grades_na(self):
        result = grade_evidence([("fact", 0)])
        self.assertEqual(result["grade"], "n/a")

    def test_headline_names_the_weakness_for_low_grades(self):
        result = grade_evidence([("assumption", 100)])
        self.assertIn("rests on assumptions", result["headline"])

    def test_rejects_unknown_confidence(self):
        with self.assertRaises(EvidenceError):
            grade_evidence([("vibes", 100)])


class TestWeakestConfidence(unittest.TestCase):
    def test_assumption_wins_over_fact(self):
        self.assertEqual(
            weakest_confidence(["fact", "assumption", "inference"]),
            "assumption",
        )

    def test_inference_wins_over_fact(self):
        self.assertEqual(weakest_confidence(["fact", "inference"]), "inference")

    def test_all_facts(self):
        self.assertEqual(weakest_confidence(["fact", "fact"]), "fact")

    def test_empty_defaults_to_weakest(self):
        self.assertEqual(weakest_confidence([]), "assumption")


if __name__ == "__main__":
    unittest.main()
