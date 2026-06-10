# -*- coding: utf-8 -*-
"""Chain state and the six block phases.

State is entirely integer and deterministically serializable (state_hash). The six
phases are pure over `state` (in-place mutation on a copy created by process_block).
The ORDER in which process_block calls them is INVIOLABLE:
    entropy → transactions → emission → metabolism → reproduction → death

CONSENSUS-FROZEN: the state-hash snapshot keys, the receipt keys/values, the record
fields, and the mutated-motto/child-name formats below all feed the chain state and
ids — they must never change. Only docstrings/comments and the (non-serialized)
ConsensusError diagnostics are in English.
"""

import copy

from .crypto import canonical, sha, verify_tx_signature
from .tx import apply_transfer, apply_spawn, apply_task, make_genome, daimon_id, daimon_address
from ..config import (
    ConsensusError,
    DEMURRAGE_NUM, DEMURRAGE_DEN, EMISSION, UPKEEP, DEATH_THRESHOLD,
    REPRO_BALANCE, REPRO_TASKS, CHILD_DOTE, SPAWN_FEE,
)


class State:
    def __init__(self):
        self.balances: dict = {}   # address -> drops
        self.nonces: dict = {}      # address -> next expected nonce
        self.daimons: dict = {}     # id -> living record
        self.fossils: list = []     # dead daimons (in order of death)
        self.notary: dict = {}      # daimon_id -> NOTARY counter

    def copy(self) -> "State":
        return copy.deepcopy(self)

    def credit(self, addr: str, amount: int) -> None:
        if amount == 0:
            return
        self.balances[addr] = self.balances.get(addr, 0) + amount

    def debit(self, addr: str, amount: int) -> None:
        bal = self.balances.get(addr, 0)
        if bal < amount:
            raise ConsensusError(f"insufficient balance on {addr}: {bal} < {amount}")
        self.balances[addr] = bal - amount

    def prune(self) -> None:
        """Remove zeroed balances (keeps the canonical state minimal)."""
        self.balances = {a: b for a, b in self.balances.items() if b != 0}

    def supply(self) -> int:
        return sum(self.balances.values())

    def hash(self) -> str:
        # Snapshot keys are consensus-frozen (they define state_hash).
        snap = {
            "bal": sorted(self.balances.items()),
            "non": sorted(self.nonces.items()),
            "dmn": [self.daimons[k] for k in sorted(self.daimons)],
            "fos": self.fossils,
            "not": sorted(self.notary.items()),
        }
        return sha(canonical(snap))


# ── The six block phases ─────────────────────────────────────────────────────

def phase_entropy(state: State) -> None:
    """ENTROPY (demurrage 2%): balance ← balance*98//100 on EVERY account."""
    for addr in sorted(state.balances):
        state.balances[addr] = state.balances[addr] * DEMURRAGE_NUM // DEMURRAGE_DEN


def phase_transactions(state: State, txs: list, receipts: list, block_index: int) -> None:
    """TRANSACTIONS (signed): verify signature+nonce and apply in order."""
    for tx in txs:
        verify_tx_signature(tx)
        expected_nonce = state.nonces.get(tx["from"], 0)
        if tx["nonce"] != expected_nonce:
            raise ConsensusError(
                f"wrong nonce for {tx['from']}: expected {expected_nonce}, got {tx['nonce']}")
        ttype = tx["type"]
        if ttype == "TRANSFER":
            apply_transfer(state, tx, receipts)
        elif ttype == "SPAWN":
            apply_spawn(state, tx, receipts, block_index)
        elif ttype == "TASK":
            apply_task(state, tx, receipts, block_index)
        else:
            raise ConsensusError(f"unknown transaction type: {ttype}")
        state.nonces[tx["from"]] = expected_nonce + 1


def phase_emission(state: State, miner: str) -> None:
    """EMISSION: a constant 50 DMN to the miner. The only creation of money."""
    state.credit(miner, EMISSION)


def phase_metabolism(state: State) -> None:
    """METABOLISM: every living daimon burns UPKEEP (1 DMN/block)."""
    for did in sorted(state.daimons):
        addr = state.daimons[did]["address"]
        bal = state.balances.get(addr, 0)
        pay = bal if bal < UPKEEP else UPKEEP
        if pay:
            state.balances[addr] = bal - pay  # burned


def _mutate_genome(parent: dict, parent_id: str) -> dict:
    """DETERMINISTIC genome mutation (no randomness).

    The motto format below is CONSENSUS-FROZEN: it becomes part of the child genome,
    hence the child's id and address. Do not change it.
    """
    gen = parent["generation"] + 1
    motto = f"{parent['motto']} ·g{gen}·{parent_id[-4:]}"  # frozen format
    lineage = list(parent["lineage"]) + [parent_id]
    return make_genome(parent["mind"], motto, parent["indole"], lineage)


def phase_reproduction(state: State, receipts: list, block_index: int) -> None:
    """REPRODUCTION: balance ≥ 50 DMN and ≥ 3 tasks ⇒ spawn a mutated child."""
    for did in sorted(state.daimons):
        parent = state.daimons[did]
        addr = parent["address"]
        bal = state.balances.get(addr, 0)
        if bal < REPRO_BALANCE or parent["tasks"] < REPRO_TASKS:
            continue
        child_genome = _mutate_genome(parent, did)
        child_id = daimon_id(child_genome)
        if child_id in state.daimons or any(f["id"] == child_id for f in state.fossils):
            continue  # unlikely collision: skip without spending
        # The parent pays: endowment to the child + spawn_fee burned.
        state.balances[addr] = bal - (CHILD_DOTE + SPAWN_FEE)
        parent["tasks"] = 0  # reset: new tasks are needed to reproduce again
        child_addr = daimon_address(child_genome)
        state.credit(child_addr, CHILD_DOTE)
        child = {
            "id": child_id,
            "name": f"{parent['name']}·{parent['generation'] + 1}",  # frozen format
            "address": child_addr,
            "mind": child_genome["mind"],
            "motto": child_genome["motto"],
            "indole": child_genome["indole"],
            "lineage": child_genome["lineage"],
            "creator": parent["creator"],
            "royalty_bp": parent["royalty_bp"],
            "tasks": 0,
            "generation": parent["generation"] + 1,
            "born": block_index,
        }
        state.daimons[child_id] = child
        receipts.append({"k": "BIRTH", "parent": did, "child": child_id,
                         "name": child["name"], "gen": child["generation"]})


def phase_death(state: State, receipts: list, block_index: int) -> None:
    """DEATH: balance < 0.5 DMN ⇒ the daimon becomes a FOSSIL (removed, dust burned)."""
    for did in sorted(state.daimons):
        daimon = state.daimons[did]
        addr = daimon["address"]
        bal = state.balances.get(addr, 0)
        if bal < DEATH_THRESHOLD:
            state.balances.pop(addr, None)  # dust burned
            fossil = dict(daimon)
            fossil["died"] = block_index
            fossil["last_balance"] = bal
            state.fossils.append(fossil)
            del state.daimons[did]
