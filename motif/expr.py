"""Safe maths expressions for graphs, e.g. "sin(2*x) / 2".

We never call Python's eval() on untrusted text directly. Instead we parse the
expression into an AST and only allow a short whitelist of node types, names and
functions. Anything else (attribute access, imports, lambdas, strings...) is
rejected with a message the AI model can act on.
"""

from __future__ import annotations

import ast
import math
from typing import Callable

FUNCTIONS: dict[str, Callable[..., float]] = {
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "sinh": math.sinh, "cosh": math.cosh, "tanh": math.tanh,
    "exp": math.exp, "log": math.log, "sqrt": math.sqrt, "abs": abs,
    "floor": math.floor, "ceil": math.ceil, "min": min, "max": max,
}
CONSTANTS = {"pi": math.pi, "e": math.e, "tau": math.tau}
VARIABLES = {"x"}

_ALLOWED_NODES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call, ast.Name, ast.Load, ast.Constant,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.USub, ast.UAdd,
)


class ExprError(ValueError):
    pass


def compile_expr(src: str) -> Callable[[float], float]:
    """Return f(x) for the expression, or raise ExprError explaining the problem."""
    src = src.replace("^", "**")  # people (and models) often write x^2
    try:
        tree = ast.parse(src, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"could not parse expression {src!r}: {exc.msg}") from None

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExprError(f"'{type(node).__name__}' is not allowed in expressions")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise ExprError("only numbers are allowed as constants")
        if isinstance(node, ast.Name) and node.id not in FUNCTIONS | CONSTANTS and node.id not in VARIABLES:
            raise ExprError(
                f"unknown name '{node.id}'. Use x, {', '.join(CONSTANTS)} and functions "
                f"{', '.join(FUNCTIONS)}"
            )
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
                raise ExprError("only the built-in maths functions can be called")

    code = compile(tree, "<expr>", "eval")
    env = {"__builtins__": {}, **FUNCTIONS, **CONSTANTS}

    def f(x: float) -> float:
        try:
            v = eval(code, env, {"x": x})  # noqa: S307 - AST is whitelisted above
            return float(v)
        except (ValueError, ZeroDivisionError, OverflowError, TypeError):
            return math.nan

    return f
