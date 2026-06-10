# -*- coding: utf-8 -*-
"""Deterministic daimon minds — `run_mind` is PURE: no I/O, no uncontrolled floats.
Same input ⇒ same output (a consensus requirement).

- ORACLE_MATH: tiny arithmetic evaluator over a whitelisted AST (no names/calls,
  exponent ≤ 16, length ≤ 80, INTEGER division).
- NOTARY: incremental counter + sha256 of the payload + block number.
- SCRIBE: uppercased payload + motto + indole.

CONSENSUS-FROZEN STRINGS: every value a mind RETURNS — including the `ERR: ...`
messages and the ValueError texts below (which get embedded into `ERR: {exc}`) — is
engraved into block receipts and validated. These literals must NEVER be translated
or edited: doing so would fork the chain. Only docstrings/comments are in English.
"""

import ast

from .crypto import sha

_AST_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a // b if b != 0 else None,   # INTEGER division (determinism)
    ast.FloorDiv: lambda a, b: a // b if b != 0 else None,
    ast.Mod: lambda a, b: a % b if b != 0 else None,
}


def _eval_ast(node):
    """Evaluate an arithmetic AST node. Integer constants and whitelisted operators only."""
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("solo costanti intere ammesse")  # frozen (goes into receipts)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval_ast(node.operand)
        return +v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Pow):
            exp = _eval_ast(node.right)
            if abs(exp) > 16:
                raise ValueError("esponente troppo grande (max 16)")  # frozen
            return _eval_ast(node.left) ** exp
        op_type = type(node.op)
        if op_type in _AST_BINOPS:
            res = _AST_BINOPS[op_type](_eval_ast(node.left), _eval_ast(node.right))
            if res is None:
                raise ValueError("divisione per zero")  # frozen
            return res
    raise ValueError("operazione non consentita")  # frozen


def mind_oracle_math(payload: str) -> str:
    if len(payload) > 80:
        return "ERR: espressione troppo lunga"  # frozen (consensus-visible)
    try:
        return str(_eval_ast(ast.parse(payload, mode="eval")))
    except Exception as exc:  # noqa: BLE001 — a mind must never crash the block
        return f"ERR: {exc}"  # frozen format


def mind_notary(payload: str, counter: int, block_index: int) -> str:
    return f"ATTO #{counter} · blk{block_index} · {sha(payload)[:16]}"  # frozen format


def mind_scribe(payload: str, motto: str, indole: str) -> str:
    return f"{payload.upper()} — {motto} [{indole}]"  # frozen format


def run_mind(daimon: dict, payload: str, block_index: int, notary_counter: int) -> str:
    """PURE, deterministic execution of the daimon's mind."""
    mind = daimon["mind"]
    if mind == "ORACLE_MATH":
        return mind_oracle_math(payload)
    if mind == "NOTARY":
        return mind_notary(payload, notary_counter, block_index)
    if mind == "SCRIBE":
        return mind_scribe(payload, daimon["motto"], daimon["indole"])
    return "ERR: mente sconosciuta"  # frozen (unreachable on a valid chain)
