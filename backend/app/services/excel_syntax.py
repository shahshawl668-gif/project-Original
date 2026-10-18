"""Excel-style spellings for the expression boxes.

Payroll people write formulas the way they do in a spreadsheet::

    IF(basic <= 25000, MIN((basic + special_allowance) * 12%, 3000), basic * 12%)
    =ROUNDUP(gross * 0.75%, 0)
    AND(esic_wage > 0, esic_wage <= esic_ceiling)

Both evaluators (``formula_eval.evaluate_formula`` and
``config_service.safe_eval_expr``) walk a whitelisted Python AST, and Python
rejects most of that: ``if`` is a reserved word, ``12%`` is not a number, ``=``
is assignment. This module **only rewrites the text** into the Python subset the
sandboxes already evaluate. It evaluates nothing, it adds no capability, and
whatever it emits still has to pass the same allow-lists — so the escape and
denial-of-service tests keep their meaning.

What it accepts, beyond the Python forms that always worked:

* function names in any case, ``IF`` / ``AND`` / ``OR`` as functions, ``=`` and
  ``<>`` for comparison, ``^`` for power, a leading ``=``;
* ``12%`` (percent) — a ``%`` is a percent sign unless an operand follows it, in
  which case it is still the remainder operator;
* field names ignoring case, spaces and underscores: ``special_allowance``,
  ``Special Allowance`` and ``[Special Allowance]`` are one field;
* Python's own ``a if cond else b``, ``and`` / ``or`` / ``not`` keep working.

Mistakes get a message a payroll user can act on: the unclosed bracket and where
it is, an unknown field with a "did you mean", an unknown function likewise.
"""
from __future__ import annotations

import difflib
import re
from collections.abc import Iterable


class ExpressionSyntaxError(ValueError):
    """The expression cannot be read. ``position`` is 1-based when known."""

    def __init__(self, message: str, position: int | None = None):
        super().__init__(message)
        self.position = position


_TOKEN = re.compile(
    r"""
    (?P<ws>\s+)
  | (?P<number>\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+)
  | (?P<string>'[^'\n]*'|"[^"\n]*")
  | (?P<field>\[[^\[\]\n]+\])
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<op>\*\*|//|<=|>=|==|!=|<>|[-+*/%^(),<>=])
    """,
    re.VERBOSE,
)

# Function spellings that differ from the name the evaluators know.
FUNCTION_ALIASES = {"if": "iff", "and": "and_", "or": "or_", "ceiling": "ceil"}

# After an operand, a "%" followed by one of these is a percent sign.
_AFTER_PERCENT = {")", ",", "+", "-", "*", "/", "**", "//", "^", "<", "<=", ">", ">=", "=", "==", "!=", "<>", "%"}
_WORD_OPERATORS = {"and", "or", "not", "if", "else"}


def normalise_name(name: str) -> str:
    """Field-name key: lower case, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", str(name).lower())


def _tokens(expression: str) -> list[tuple[str, str, int]]:
    out: list[tuple[str, str, int]] = []
    pos = 0
    while pos < len(expression):
        m = _TOKEN.match(expression, pos)
        if not m:
            raise ExpressionSyntaxError(
                f"Unexpected character '{expression[pos]}' at position {pos + 1}. "
                "Use only numbers, field names, + - * / ^ %, comparisons, brackets and commas.",
                pos + 1,
            )
        if m.lastgroup != "ws":
            out.append((m.lastgroup or "", m.group(), pos))
        pos = m.end()
    return out


def _check_brackets(tokens: list[tuple[str, str, int]]) -> None:
    opened: list[int] = []
    for kind, text, pos in tokens:
        if kind != "op":
            continue
        if text == "(":
            opened.append(pos)
        elif text == ")":
            if not opened:
                raise ExpressionSyntaxError(
                    f"There is a ')' at position {pos + 1} with no matching '('", pos + 1)
            opened.pop()
    if opened:
        n_open = sum(1 for k, t, _ in tokens if k == "op" and t == "(")
        n_close = sum(1 for k, t, _ in tokens if k == "op" and t == ")")
        raise ExpressionSyntaxError(
            f"{len(opened)} opening '(' {'is' if len(opened) == 1 else 'are'} never closed "
            f"({n_open} '(' but only {n_close} ')'). The last unclosed '(' is at position "
            f"{opened[-1] + 1}.",
            opened[-1] + 1,
        )


def translate(expression: str, variables: Iterable[str] | None = None) -> str:
    """Rewrite an Excel-style expression as the Python subset the sandboxes evaluate.

    ``variables`` are the names the caller will supply. When given, a bare name
    is matched to one of them ignoring case, spaces and underscores, and a name
    that matches none is reported here with a suggestion. When ``None`` names
    are passed through untouched and left for the evaluator to judge.
    """
    text = expression.strip()
    if text.startswith("="):
        text = " " + text[1:]
    tokens = _tokens(text)
    _check_brackets(tokens)

    index = {normalise_name(v): v for v in variables} if variables is not None else None
    known = set(variables) if variables is not None else set()

    def resolve(name: str, pos: int) -> str:
        if index is None or name in known:
            return name
        hit = index.get(normalise_name(name))
        if hit is not None:
            return hit
        near = difflib.get_close_matches(normalise_name(name), list(index), n=3, cutoff=0.6)
        hint = (f" Did you mean: {', '.join(index[n] for n in near)}?" if near
                else (f" Available fields: {', '.join(sorted(index.values())[:15])}"
                      f"{'…' if len(index) > 15 else ''}." if index else ""))
        raise ExpressionSyntaxError(f"Unknown field '{name}' at position {pos + 1}.{hint}", pos + 1)

    out: list[str] = []
    stack: list[tuple[int, int | None]] = []  # (index of "(", index of its function name or None)
    prev_operand = False
    last_start = 0
    pending_func: int | None = None

    for i, (kind, tok, pos) in enumerate(tokens):
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        next_is_paren = bool(nxt and nxt[0] == "op" and nxt[1] == "(")

        if kind in ("number", "string"):
            out.append(tok)
            last_start, prev_operand, pending_func = len(out) - 1, True, None
        elif kind == "field":
            out.append(resolve(tok[1:-1].strip(), pos))
            last_start, prev_operand, pending_func = len(out) - 1, True, None
        elif kind == "ident":
            low = tok.lower()
            if low in ("true", "false"):
                out.append("True" if low == "true" else "False")
                last_start, prev_operand, pending_func = len(out) - 1, True, None
            elif low in _WORD_OPERATORS and not (low in ("if", "and", "or") and not prev_operand and next_is_paren):
                out.append(low)  # Python's own and / or / not / if / else
                prev_operand, pending_func = False, None
            elif next_is_paren:
                out.append(FUNCTION_ALIASES.get(low, low))
                pending_func, prev_operand = len(out) - 1, False
            else:
                out.append(resolve(tok, pos))
                last_start, prev_operand, pending_func = len(out) - 1, True, None
        else:  # operator
            if tok == "(":
                stack.append((len(out), pending_func))
                out.append("(")
                prev_operand = False
            elif tok == ")":
                open_idx, func_idx = stack.pop()
                out.append(")")
                last_start = func_idx if func_idx is not None else open_idx
                prev_operand = True
            elif tok == "%":
                after = nxt is None or (nxt[0] == "op" and nxt[1] in _AFTER_PERCENT) or \
                    (nxt[0] == "ident" and nxt[1].lower() in ("and", "or", "if", "else"))
                if prev_operand and after:  # 12%  ->  (12 / 100)
                    out.insert(last_start, "(")
                    out.append("/ 100 )")
                else:
                    out.append("%")
                    prev_operand = False
            else:
                out.append({"^": "**", "=": "==", "<>": "!="}.get(tok, tok))
                prev_operand = False
            pending_func = None
    return " ".join(out)
