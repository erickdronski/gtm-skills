"""Tests for the formula evaluator.

The security tests matter more than the arithmetic ones. This evaluator runs
against JSON files that an agent may have written from a web page, a customer
email, or a PDF — untrusted input by any reasonable definition. Every test in
:class:`TestRefusesUnsafeInput` corresponds to something ``eval()`` would have
cheerfully executed.
"""

import unittest

from gtmkit.expr import ExpressionError, evaluate, referenced_names


class TestArithmetic(unittest.TestCase):
    def test_basic_multiplication(self):
        self.assertEqual(evaluate("a * b", {"a": 3, "b": 4}), 12.0)

    def test_operator_precedence(self):
        self.assertEqual(evaluate("2 + 3 * 4", {}), 14.0)

    def test_parentheses(self):
        self.assertEqual(evaluate("(2 + 3) * 4", {}), 20.0)

    def test_realistic_driver_formula(self):
        variables = {
            "tickets_per_year": 124800,
            "deflection_rate": 0.18,
            "cost_per_ticket": 12.81,
        }
        result = evaluate(
            "tickets_per_year * deflection_rate * cost_per_ticket", variables
        )
        # 124800 * 0.18 = 22464; 22464 * 12.81 = 287763.84
        self.assertAlmostEqual(result, 287763.84, places=2)

    def test_complement_pattern(self):
        result = evaluate(
            "volume * (1 - deflection) * unit",
            {"volume": 1000, "deflection": 0.25, "unit": 2},
        )
        self.assertAlmostEqual(result, 1500.0)

    def test_unary_minus(self):
        self.assertEqual(evaluate("-x", {"x": 5}), -5.0)

    def test_allowed_functions(self):
        self.assertEqual(evaluate("min(a, b)", {"a": 3, "b": 7}), 3.0)
        self.assertEqual(evaluate("max(a, b)", {"a": 3, "b": 7}), 7.0)
        self.assertEqual(evaluate("round(x)", {"x": 3.6}), 4.0)
        self.assertEqual(evaluate("sqrt(x)", {"x": 16}), 4.0)

    def test_ternary_for_tiered_logic(self):
        formula = "seats * (rate_high if seats > 500 else rate_low)"
        self.assertEqual(
            evaluate(formula, {"seats": 600, "rate_high": 2, "rate_low": 5}),
            1200.0,
        )
        self.assertEqual(
            evaluate(formula, {"seats": 100, "rate_high": 2, "rate_low": 5}),
            500.0,
        )

    def test_comparison_returns_number(self):
        self.assertEqual(evaluate("a > b", {"a": 2, "b": 1}), 1.0)
        self.assertEqual(evaluate("a > b", {"a": 1, "b": 2}), 0.0)


class TestRefusesUnsafeInput(unittest.TestCase):
    """Each of these would execute under eval(). None may execute here."""

    def test_rejects_imports(self):
        with self.assertRaises(ExpressionError):
            evaluate("__import__('os')", {})

    def test_rejects_attribute_access(self):
        with self.assertRaises(ExpressionError):
            evaluate("x.__class__", {"x": 1})

    def test_rejects_dunder_traversal(self):
        with self.assertRaises(ExpressionError):
            evaluate("().__class__.__bases__", {})

    def test_rejects_subscripting(self):
        with self.assertRaises(ExpressionError):
            evaluate("x[0]", {"x": 1})

    def test_rejects_unknown_functions(self):
        with self.assertRaises(ExpressionError) as ctx:
            evaluate("open('/etc/passwd')", {})
        self.assertIn("unknown function", str(ctx.exception))

    def test_rejects_lambda(self):
        with self.assertRaises(ExpressionError):
            evaluate("(lambda: 1)()", {})

    def test_rejects_string_literals(self):
        with self.assertRaises(ExpressionError):
            evaluate("'a' * 3", {})

    def test_rejects_walrus_and_assignment(self):
        with self.assertRaises(ExpressionError):
            evaluate("x = 1", {})

    def test_caps_exponent_to_prevent_cpu_exhaustion(self):
        with self.assertRaises(ExpressionError) as ctx:
            evaluate("9 ** 9999", {})
        self.assertIn("too large", str(ctx.exception))

    def test_rejects_keyword_arguments(self):
        with self.assertRaises(ExpressionError):
            evaluate("round(x, ndigits=2)", {"x": 1.234})


class TestErrorMessages(unittest.TestCase):
    def test_unknown_variable_lists_what_is_defined(self):
        with self.assertRaises(ExpressionError) as ctx:
            evaluate("tickets * rate", {"tickets": 10})
        message = str(ctx.exception)
        self.assertIn("rate", message)
        self.assertIn("tickets", message)

    def test_division_by_zero_is_actionable(self):
        with self.assertRaises(ExpressionError) as ctx:
            evaluate("a / b", {"a": 1, "b": 0})
        self.assertIn("denominator", str(ctx.exception))

    def test_syntax_error_names_the_formula(self):
        with self.assertRaises(ExpressionError) as ctx:
            evaluate("a * * b", {"a": 1, "b": 2})
        self.assertIn("could not parse", str(ctx.exception))

    def test_empty_formula_rejected(self):
        with self.assertRaises(ExpressionError):
            evaluate("   ", {})

    def test_function_used_as_bare_name(self):
        with self.assertRaises(ExpressionError) as ctx:
            evaluate("min", {})
        self.assertIn("must be called", str(ctx.exception))


class TestReferencedNames(unittest.TestCase):
    def test_extracts_variables_and_skips_functions(self):
        names = referenced_names("min(a, b) * c")
        self.assertEqual(set(names), {"a", "b", "c"})

    def test_deduplicates(self):
        names = referenced_names("a + a + b")
        self.assertEqual(list(names), ["a", "b"])

    def test_raises_on_bad_syntax(self):
        with self.assertRaises(ExpressionError):
            referenced_names("a +")


if __name__ == "__main__":
    unittest.main()
