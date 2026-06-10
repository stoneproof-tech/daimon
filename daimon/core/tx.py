# -*- coding: utf-8 -*-
"""Genome, daimon identity and transaction handlers.

Handlers operate in-place on a `State` passed as argument (no State import: avoids
cycles). Types: TRANSFER, SPAWN, TASK. Signature+nonce verification lives in
`state.phase_transactions`; the economic logic of each type lives here.

Receipt keys/values (`k`, "TRANSFER"/"SPAWN"/"TASK", field names) and record fields
are consensus-visible (engraved into receipts/state) and must not change. The
ConsensusError messages below are diagnostics only (never serialized), so they are
in English.
"""

from .crypto import canonical, sha
from .minds import run_mind
from ..config import (
    ConsensusError, KNOWN_MINDS,
    SPAWN_FEE, MIN_ENDOWMENT, THINK_COST, ROYALTY_MAX_BP,
)


# ── Genome & identity (derived ONLY from the genome: no human key) ───────────

def make_genome(mind: str, motto: str, indole: str, lineage: list) -> dict:
    return {"mind": mind, "motto": motto, "indole": indole, "lineage": list(lineage)}


def daimon_id(genome: dict) -> str:
    return "DMN_" + sha(canonical(genome))[:16]


def daimon_address(genome: dict) -> str:
    return "dmn_" + sha("addr:" + canonical(genome))[:24]


# ── Transaction handlers ─────────────────────────────────────────────────────

def apply_transfer(state, tx: dict, receipts: list) -> None:
    p = tx["payload"]
    to, amount = p["to"], int(p["amount"])
    if amount <= 0:
        raise ConsensusError("TRANSFER: non-positive amount")
    state.debit(tx["from"], amount)
    state.credit(to, amount)
    receipts.append({"k": "TRANSFER", "from": tx["from"], "to": to, "amount": amount})


def apply_spawn(state, tx: dict, receipts: list, block_index: int) -> None:
    p = tx["payload"]
    genome = p["genome"]
    endowment = int(p["endowment"])
    royalty_bp = int(p["royalty_bp"])
    if endowment < MIN_ENDOWMENT:
        raise ConsensusError("SPAWN: endowment below minimum")
    if not (0 <= royalty_bp <= ROYALTY_MAX_BP):
        raise ConsensusError("SPAWN: royalty out of range [0, 5000] bp")
    if not all(k in genome for k in ("mind", "motto", "indole", "lineage")):
        raise ConsensusError("SPAWN: malformed genome")
    if genome["mind"] not in KNOWN_MINDS:
        raise ConsensusError("SPAWN: unknown mind")

    did = daimon_id(genome)
    if did in state.daimons or any(f["id"] == did for f in state.fossils):
        raise ConsensusError("SPAWN: genome already exists (id collision)")

    addr = daimon_address(genome)
    # The creator pays: spawn_fee burned + endowment transferred to the child.
    state.debit(tx["from"], SPAWN_FEE + endowment)
    state.credit(addr, endowment)  # spawn_fee NOT re-credited: burned.

    record = {
        "id": did,
        "name": p.get("name", did),
        "address": addr,
        "mind": genome["mind"],
        "motto": genome["motto"],
        "indole": genome["indole"],
        "lineage": list(genome["lineage"]),
        "creator": tx["from"],
        "royalty_bp": royalty_bp,
        "tasks": 0,
        "generation": len(genome["lineage"]),
        "born": block_index,
    }
    state.daimons[did] = record
    receipts.append({"k": "SPAWN", "id": did, "name": record["name"],
                     "mind": record["mind"], "addr": addr, "endowment": endowment})


def apply_task(state, tx: dict, receipts: list, block_index: int) -> None:
    p = tx["payload"]
    did = p["daimon"]
    payment = int(p["payment"])
    work = str(p["payload"])
    if did not in state.daimons:
        raise ConsensusError("TASK: daimon nonexistent or dead")
    daimon = state.daimons[did]
    royalty = payment * daimon["royalty_bp"] // 10000
    if payment < royalty + THINK_COST:
        raise ConsensusError("TASK: payment too low to cover royalty + think_cost")
    net = payment - royalty - THINK_COST

    state.debit(tx["from"], payment)          # the requester pays the full amount
    state.credit(daimon["creator"], royalty)   # royalty to the creator
    state.credit(daimon["address"], net)       # net to the daimon
    # THINK_COST burned (not re-credited to anyone).

    counter = state.notary.get(did, 0) + 1
    result = run_mind(daimon, work, block_index, counter)
    if daimon["mind"] == "NOTARY":
        state.notary[did] = counter
    daimon["tasks"] += 1

    receipts.append({"k": "TASK", "daimon": did, "mind": daimon["mind"],
                     "input": work, "result": result, "payment": payment,
                     "royalty": royalty, "net": net})
