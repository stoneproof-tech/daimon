# -*- coding: utf-8 -*-
"""Stato della catena e le sei fasi del blocco.

Lo stato è interamente intero e serializzabile in modo deterministico (state_hash).
Le sei fasi sono pure sullo `state` (mutazione in-place su una copia creata da
process_block). L'ORDINE in cui le chiama process_block è INVIOLABILE:
    entropia → transazioni → emissione → metabolismo → riproduzione → morte
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
        self.balances: dict = {}   # address -> gocce
        self.nonces: dict = {}      # address -> prossimo nonce atteso
        self.daimons: dict = {}     # id -> record vivo
        self.fossils: list = []     # daimon morti (in ordine di morte)
        self.notary: dict = {}      # daimon_id -> contatore NOTARY

    def copy(self) -> "State":
        return copy.deepcopy(self)

    def credit(self, addr: str, amount: int) -> None:
        if amount == 0:
            return
        self.balances[addr] = self.balances.get(addr, 0) + amount

    def debit(self, addr: str, amount: int) -> None:
        bal = self.balances.get(addr, 0)
        if bal < amount:
            raise ConsensusError(f"saldo insufficiente su {addr}: {bal} < {amount}")
        self.balances[addr] = bal - amount

    def prune(self) -> None:
        """Rimuove i saldi azzerati (mantiene lo stato canonico minimale)."""
        self.balances = {a: b for a, b in self.balances.items() if b != 0}

    def supply(self) -> int:
        return sum(self.balances.values())

    def hash(self) -> str:
        snap = {
            "bal": sorted(self.balances.items()),
            "non": sorted(self.nonces.items()),
            "dmn": [self.daimons[k] for k in sorted(self.daimons)],
            "fos": self.fossils,
            "not": sorted(self.notary.items()),
        }
        return sha(canonical(snap))


# ── Le sei fasi del blocco ──────────────────────────────────────────────────

def phase_entropy(state: State) -> None:
    """ENTROPIA (demurrage 2%): saldo ← saldo*98//100 su TUTTI i conti."""
    for addr in sorted(state.balances):
        state.balances[addr] = state.balances[addr] * DEMURRAGE_NUM // DEMURRAGE_DEN


def phase_transactions(state: State, txs: list, receipts: list, block_index: int) -> None:
    """TRANSAZIONI firmate: verifica firma+nonce e applica in ordine."""
    for tx in txs:
        verify_tx_signature(tx)
        expected_nonce = state.nonces.get(tx["from"], 0)
        if tx["nonce"] != expected_nonce:
            raise ConsensusError(
                f"nonce errato per {tx['from']}: atteso {expected_nonce}, ricevuto {tx['nonce']}")
        ttype = tx["type"]
        if ttype == "TRANSFER":
            apply_transfer(state, tx, receipts)
        elif ttype == "SPAWN":
            apply_spawn(state, tx, receipts, block_index)
        elif ttype == "TASK":
            apply_task(state, tx, receipts, block_index)
        else:
            raise ConsensusError(f"tipo transazione sconosciuto: {ttype}")
        state.nonces[tx["from"]] = expected_nonce + 1


def phase_emission(state: State, miner: str) -> None:
    """EMISSIONE: 50 DMN costanti al miner. È l'unica creazione di moneta."""
    state.credit(miner, EMISSION)


def phase_metabolism(state: State) -> None:
    """METABOLISMO: ogni daimon vivo brucia UPKEEP (1 DMN/blocco)."""
    for did in sorted(state.daimons):
        addr = state.daimons[did]["address"]
        bal = state.balances.get(addr, 0)
        pay = bal if bal < UPKEEP else UPKEEP
        if pay:
            state.balances[addr] = bal - pay  # bruciato


def _mutate_genome(parent: dict, parent_id: str) -> dict:
    """Mutazione DETERMINISTICA del genoma (nessun random)."""
    gen = parent["generation"] + 1
    motto = f"{parent['motto']} ·g{gen}·{parent_id[-4:]}"
    lineage = list(parent["lineage"]) + [parent_id]
    return make_genome(parent["mind"], motto, parent["indole"], lineage)


def phase_reproduction(state: State, receipts: list, block_index: int) -> None:
    """RIPRODUZIONE: saldo ≥ 50 DMN e ≥ 3 task ⇒ genera un figlio mutato."""
    for did in sorted(state.daimons):
        parent = state.daimons[did]
        addr = parent["address"]
        bal = state.balances.get(addr, 0)
        if bal < REPRO_BALANCE or parent["tasks"] < REPRO_TASKS:
            continue
        child_genome = _mutate_genome(parent, did)
        child_id = daimon_id(child_genome)
        if child_id in state.daimons or any(f["id"] == child_id for f in state.fossils):
            continue  # collisione improbabile: salta senza spendere
        # Il genitore paga: dote al figlio + spawn_fee bruciata.
        state.balances[addr] = bal - (CHILD_DOTE + SPAWN_FEE)
        parent["tasks"] = 0  # reset: serviranno nuovi task per riprodursi ancora
        child_addr = daimon_address(child_genome)
        state.credit(child_addr, CHILD_DOTE)
        child = {
            "id": child_id,
            "name": f"{parent['name']}·{parent['generation'] + 1}",
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
    """MORTE: saldo < 0.5 DMN ⇒ il daimon diventa FOSSILE (rimosso, dust bruciato)."""
    for did in sorted(state.daimons):
        daimon = state.daimons[did]
        addr = daimon["address"]
        bal = state.balances.get(addr, 0)
        if bal < DEATH_THRESHOLD:
            state.balances.pop(addr, None)  # dust bruciato
            fossil = dict(daimon)
            fossil["died"] = block_index
            fossil["last_balance"] = bal
            state.fossils.append(fossil)
            del state.daimons[did]
