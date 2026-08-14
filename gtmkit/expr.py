"""A deliberately small, safe arithmetic expression evaluator.

Business-case drivers are written as readable formulas — ``tickets_per_year *
deflection_rate * cost_per_ticket`` — so that a reviewer can audit the logic
without reading Python. Evaluating those with :func:`eval` would hand arbitrary
code execution to whatever JSON file the agent was pointed at, which is exactly
the kind of footgun this pack exists to avoid.

So instead we parse to an AST and walk a whitelist. Anything outside basic
arithmetic, comparison, a handful of named functions, and the supplied
variables is a hard error.
"""

from __future__ import annotations

import ast
import math
from typing import Any, Dict, Mapping

__all__ = ["FUNCTIONS", "ExpressionError", "evaluate"]


class ExpressionError(ValueError):
    """Raised for malformed, unsafe, or unresolvable expressions."""


#: Functions a formula author may call. Kept small on purpose: every addition
#: is a new surface a malicious or careless spec file could reach for.
FUNCTIONS = {
    "min": min,
    "max": max,
    "abs": abs,
    "round": round,
    "floor": math.floor,
    "ceil": math.ceil,
    "sqrt": math.sqrt,
}

_ALLOWED_BINOPS = (
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
)

_ALLOWED_UNARYOPS = (ast.UAdd, ast.USub)

_ALLOWED_COMPARE = (
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
)


def evaluate(expression: str, variables: Mapping[str, float]) -> float:
    """Evaluate ``expression`` against ``variables`` and return a float.

    Raises :class:`ExpressionError` with an actionable message on anything
    unsupported — including an undefined variable, which is far more often a
    typo in a driver formula than a deliberate omission.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise ExpressionError("formula must be a non-empty string")

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(
            "could not parse formula %r: %s" % (expression, exc.msg)
        ) from exc

    value = _eval_node(tree.body, variables, expression)
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if not isinstance(value, (int, float)):
        raise ExpressionError(
            "formula %r produced a %s, expected a number"
            % (expression, type(value).__name__)
        )
    return float(value)


def _eval_node(node: ast.AST, variables: Mapping[str, float], src: str) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
            return node.value
        raise ExpressionError(
            "only numeric literals are allowed in formulas, found %r" % (node.value,)
        )

    if isinstance(node, ast.Name):
        if node.id in variables:
            return variables[node.id]
        if node.id in FUNCTIONS:
            raise ExpressionError(
                "%r is a function and must be called, e.g. %s(...)" % (node.id, node.id)
            )
        known = ", ".join(sorted(variables)) or "(none defined)"
        raise ExpressionError(
            "unknown variable %r in formula %r. Defined inputs: %s"
            % (node.id, src, known)
        )

    if isinstance(node, ast.BinOp):
        if not isinstance(node.op, _ALLOWED_BINOPS):
            raise ExpressionError(
                "operator %s is not allowed in formulas" % type(node.op).__name__
            )
        left = _eval_node(node.left, variables, src)
        right = _eval_node(node.right, variables, src)
        try:
            return _apply_binop(node.op, left, right)
        except ZeroDivisionError:
            raise ExpressionError(
                "division by zero in formula %r — check the denominator input" % src
            )

    if isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _ALLOWED_UNARYOPS):
            raise ExpressionError(
                "unary operator %s is not allowed" % type(node.op).__name__
            )
        operand = _eval_node(node.operand, variables, src)
        return operand if isinstance(node.op, ast.UAdd) else -operand

    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, variables, src)
        for op, comparator in zip(node.ops, node.comparators):
            if not isinstance(op, _ALLOWED_COMPARE):
                raise ExpressionError(
                    "comparison %s is not allowed" % type(op).__name__
                )
            right = _eval_node(comparator, variables, src)
            if not _apply_compare(op, left, right):
                return False
            left = right
        return True

    if isinstance(node, ast.IfExp):
        # Ternaries are genuinely useful for tiered logic:
        #   seats * (rate_high if seats > 500 else rate_low)
        test = _eval_node(node.test, variables, src)
        branch = node.body if test else node.orelse
        return _eval_node(branch, variables, src)

    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise ExpressionError("only direct function calls are allowed")
        name = node.func.id
        if name not in FUNCTIONS:
            allowed = ", ".join(sorted(FUNCTIONS))
            raise ExpressionError("unknown function %r. Allowed: %s" % (name, allowed))
        if node.keywords:
            raise ExpressionError("keyword arguments are not supported in formulas")
        args = [_eval_node(arg, variables, src) for arg in node.args]
        try:
            return FUNCTIONS[name](*args)
        except TypeError as exc:
            raise ExpressionError(
                "bad arguments to %s() in formula %r: %s" % (name, src, exc)
            ) from exc

    raise ExpressionError(
        "expression element %s is not allowed in formulas" % type(node).__name__
    )


def _apply_binop(op: ast.AST, left: Any, right: Any) -> Any:
    if isinstance(op, ast.Add):
        return left + right
    if isinstance(op, ast.Sub):
        return left - right
    if isinstance(op, ast.Mult):
        return left * right
    if isinstance(op, ast.Div):
        return left / right
    if isinstance(op, ast.FloorDiv):
        return left // right
    if isinstance(op, ast.Mod):
        return left % right
    if isinstance(op, ast.Pow):
        # Guard against a spec file pinning the CPU with 9 ** 9 ** 9.
        if abs(right) > 64:
            raise ExpressionError(
                "exponent %r is too large; business-case formulas should not "
                "need powers above 64" % (right,)
            )
        return left**right
    raise ExpressionError("unsupported operator %s" % type(op).__name__)


def _apply_compare(op: ast.AST, left: Any, right: Any) -> bool:
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    if isinstance(op, ast.Lt):
        return left < right
    if isinstance(op, ast.LtE):
        return left <= right
    if isinstance(op, ast.Gt):
        return left > right
    if isinstance(op, ast.GtE):
        return left >= right
    raise ExpressionError("unsupported comparison %s" % type(op).__name__)


def referenced_names(expression: str) -> Dict[str, None]:
    """Return the variable names a formula depends on, preserving order.

    Used by the spec validator to catch inputs that are declared but never
    used — usually a sign the formula was edited and the ledger was not.
    """
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(
            "could not parse formula %r: %s" % (expression, exc.msg)
        ) from exc
    names: Dict[str, None] = {}

    def visit(node: ast.AST) -> None:
        # Depth-first in source order. ``ast.walk`` is breadth-first, which
        # would report ``a + b * c`` as (a, c, b) — harmless for the missing
        # and unused checks, but the error messages built from this list read
        # as noise when they do not follow the formula the author wrote.
        if isinstance(node, ast.Name) and node.id not in FUNCTIONS:
            names[node.id] = None
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(tree)
    return names
