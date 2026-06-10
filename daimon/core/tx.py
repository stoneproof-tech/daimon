# -*- coding: utf-8 -*-
"""Genoma, identità dei daimon e handler delle transazioni.

Gli handler operano in-place su uno `State` passato come argomento (nessun import
di State: evita cicli). Tipi: TRANSFER, SPAWN, TASK. La verifica firma+nonce è in
`state.phase_transactions`; qui sta la logica economica di ciascun tipo.
"""

from .crypto import canonical, sha
from .minds import run_mind
from ..config import (
    ConsensusError, KNOWN_MINDS,
    SPAWN_FEE, MIN_ENDOWMENT, THINK_COST, ROYALTY_MAX_BP,
)


# ── Genoma & identità (derivata SOLO dal genoma: nessuna chiave umana) ───────

def make_genome(mind: str, motto: str, indole: str, lineage: list) -> dict:
    return {"mind": mind, "motto": motto, "indole": indole, "lineage": list(lineage)}


def daimon_id(genome: dict) -> str:
    return "DMN_" + sha(canonical(genome))[:16]


def daimon_address(genome: dict) -> str:
    return "dmn_" + sha("addr:" + canonical(genome))[:24]


# ── Handler delle transazioni ───────────────────────────────────────────────

def apply_transfer(state, tx: dict, receipts: list) -> None:
    p = tx["payload"]
    to, amount = p["to"], int(p["amount"])
    if amount <= 0:
        raise ConsensusError("TRANSFER: importo non positivo")
    state.debit(tx["from"], amount)
    state.credit(to, amount)
    receipts.append({"k": "TRANSFER", "from": tx["from"], "to": to, "amount": amount})


def apply_spawn(state, tx: dict, receipts: list, block_index: int) -> None:
    p = tx["payload"]
    genome = p["genome"]
    endowment = int(p["endowment"])
    royalty_bp = int(p["royalty_bp"])
    if endowment < MIN_ENDOWMENT:
        raise ConsensusError("SPAWN: dote sotto il minimo")
    if not (0 <= royalty_bp <= ROYALTY_MAX_BP):
        raise ConsensusError("SPAWN: royalty fuori range [0, 5000] bp")
    if not all(k in genome for k in ("mind", "motto", "indole", "lineage")):
        raise ConsensusError("SPAWN: genoma malformato")
    if genome["mind"] not in KNOWN_MINDS:
        raise ConsensusError("SPAWN: mente sconosciuta")

    did = daimon_id(genome)
    if did in state.daimons or any(f["id"] == did for f in state.fossils):
        raise ConsensusError("SPAWN: genoma già esistente (id collisione)")

    addr = daimon_address(genome)
    # Il creatore paga: spawn_fee bruciata + dote trasferita al figlio.
    state.debit(tx["from"], SPAWN_FEE + endowment)
    state.credit(addr, endowment)  # spawn_fee NON ricreditata: bruciata.

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
        raise ConsensusError("TASK: daimon inesistente o morto")
    daimon = state.daimons[did]
    royalty = payment * daimon["royalty_bp"] // 10000
    if payment < royalty + THINK_COST:
        raise ConsensusError("TASK: pagamento insufficiente a coprire royalty + think_cost")
    net = payment - royalty - THINK_COST

    state.debit(tx["from"], payment)          # il committente paga l'intero
    state.credit(daimon["creator"], royalty)   # royalty al creatore
    state.credit(daimon["address"], net)       # netto al daimon
    # THINK_COST bruciato (non ricreditato a nessuno).

    counter = state.notary.get(did, 0) + 1
    result = run_mind(daimon, work, block_index, counter)
    if daimon["mind"] == "NOTARY":
        state.notary[did] = counter
    daimon["tasks"] += 1

    receipts.append({"k": "TASK", "daimon": did, "mind": daimon["mind"],
                     "input": work, "result": result, "payment": payment,
                     "royalty": royalty, "net": net})
