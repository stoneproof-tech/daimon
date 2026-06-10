# -*- coding: utf-8 -*-
"""Menti deterministiche dei daimon — `run_mind` è PURA: nessun I/O, nessun float
non controllato. Stesso input ⇒ stesso output (requisito di consenso).

- ORACLE_MATH: mini-eval aritmetico via AST con whitelist (niente nomi/chiamate,
  esponente ≤ 16, lunghezza ≤ 80, divisione INTERA).
- NOTARY: contatore incrementale + sha256 del payload + numero di blocco.
- SCRIBE: payload in maiuscolo + motto + indole.
"""

import ast

from .crypto import sha

_AST_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a // b if b != 0 else None,   # divisione INTERA (determinismo)
    ast.FloorDiv: lambda a, b: a // b if b != 0 else None,
    ast.Mod: lambda a, b: a % b if b != 0 else None,
}


def _eval_ast(node):
    """Valuta un nodo AST aritmetico. Solo costanti intere e operatori in whitelist."""
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("solo costanti intere ammesse")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval_ast(node.operand)
        return +v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Pow):
            exp = _eval_ast(node.right)
            if abs(exp) > 16:
                raise ValueError("esponente troppo grande (max 16)")
            return _eval_ast(node.left) ** exp
        op_type = type(node.op)
        if op_type in _AST_BINOPS:
            res = _AST_BINOPS[op_type](_eval_ast(node.left), _eval_ast(node.right))
            if res is None:
                raise ValueError("divisione per zero")
            return res
    raise ValueError("operazione non consentita")


def mind_oracle_math(payload: str) -> str:
    if len(payload) > 80:
        return "ERR: espressione troppo lunga"
    try:
        return str(_eval_ast(ast.parse(payload, mode="eval")))
    except Exception as exc:  # noqa: BLE001 — la mente non deve mai crashare il blocco
        return f"ERR: {exc}"


def mind_notary(payload: str, counter: int, block_index: int) -> str:
    return f"ATTO #{counter} · blk{block_index} · {sha(payload)[:16]}"


def mind_scribe(payload: str, motto: str, indole: str) -> str:
    return f"{payload.upper()} — {motto} [{indole}]"


def run_mind(daimon: dict, payload: str, block_index: int, notary_counter: int) -> str:
    """Esecuzione PURA e deterministica della mente del daimon."""
    mind = daimon["mind"]
    if mind == "ORACLE_MATH":
        return mind_oracle_math(payload)
    if mind == "NOTARY":
        return mind_notary(payload, notary_counter, block_index)
    if mind == "SCRIBE":
        return mind_scribe(payload, daimon["motto"], daimon["indole"])
    return "ERR: mente sconosciuta"
