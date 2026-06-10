# -*- coding: utf-8 -*-
"""process_block (unica funzione di consenso), il blocco, il PoW e la catena.

process_block è usata IDENTICA dal mining e dalla validazione. La validazione è un
replay totale dalla genesi: ricostruisce lo stato e verifica PoW, linkage,
ricevute e state_hash di ogni blocco. Qualunque manomissione produce divergenza.
"""

import time

from .crypto import canonical, sha
from .state import (
    State,
    phase_entropy, phase_transactions, phase_emission,
    phase_metabolism, phase_reproduction, phase_death,
)
from ..config import (
    GENESIS_PREV, GENESIS_TS, MANIFESTO, ConsensusError,
    MAX_HASH, BASE_DIFFICULTY, RETARGET_INTERVAL, TARGET_BLOCK_TIME, RETARGET_CLAMP,
)


def process_block(prev_state: State, index: int, miner: str, txs: list,
                  is_genesis: bool = False):
    """
    Applica un blocco allo stato precedente → (nuovo_stato, ricevute).
    Ordine INVIOLABILE: entropia → tx → emissione → metabolismo → riproduzione → morte.
    Funzione PURA: stesso input ⇒ stesso output. Nessun I/O, nessun float.
    """
    state = prev_state.copy()
    receipts: list = []

    if is_genesis:
        # Genesi: nessuna moneta creata (fair launch, zero premine), solo il manifesto.
        return state, receipts

    phase_entropy(state)                               # 1. ENTROPIA
    phase_transactions(state, txs, receipts, index)    # 2. TRANSAZIONI
    phase_emission(state, miner)                       # 3. EMISSIONE
    phase_metabolism(state)                            # 4. METABOLISMO
    phase_reproduction(state, receipts, index)         # 5. RIPRODUZIONE
    phase_death(state, receipts, index)                # 6. MORTE
    state.prune()
    return state, receipts


# ── Blocco & PoW ────────────────────────────────────────────────────────────

def header_pow_hash(header: dict) -> str:
    return sha(canonical(header))


def pow_target(difficulty: int) -> int:
    """Soglia massima dell'hash per la difficoltà data: hash valido se ≤ MAX_HASH//D."""
    return MAX_HASH // max(1, int(difficulty))


def satisfies_pow(header: dict) -> bool:
    """Verifica la PoW rispetto alla difficoltà DICHIARATA nell'header."""
    return int(header_pow_hash(header), 16) <= pow_target(header["difficulty"])


def next_difficulty(blocks: list) -> int:
    """
    Difficoltà DETERMINISTICA del prossimo blocco che estende `blocks`.
    Invariata tranne ai confini di RETARGET_INTERVAL, dove si riadatta puntando a
    TARGET_BLOCK_TIME secondi/blocco sull'ultima finestra, con clamp a RETARGET_CLAMP×.
    """
    last = blocks[-1]
    prev_diff = last["difficulty"]
    next_index = last["index"] + 1
    if next_index < RETARGET_INTERVAL or next_index % RETARGET_INTERVAL != 0:
        return prev_diff
    ref = blocks[-RETARGET_INTERVAL]                       # confine precedente della finestra
    actual = last["timestamp"] - ref["timestamp"]
    if actual <= 0:
        actual = 1
    expected = RETARGET_INTERVAL * TARGET_BLOCK_TIME
    # Blocchi troppo veloci (actual < expected) ⇒ difficoltà sale; troppo lenti ⇒ scende.
    new_diff = prev_diff * expected // actual
    lo, hi = prev_diff // RETARGET_CLAMP, prev_diff * RETARGET_CLAMP
    new_diff = max(lo, min(hi, new_diff))
    return max(1, new_diff)


def mine_nonce(header_wo_nonce: dict):
    """Proof-of-Work: trova nonce tale che l'hash soddisfi la difficoltà dell'header."""
    target = pow_target(header_wo_nonce["difficulty"])
    nonce = 0
    while True:
        header = dict(header_wo_nonce)
        header["nonce"] = nonce
        h = header_pow_hash(header)
        if int(h, 16) <= target:
            return nonce, h
        nonce += 1


class Blockchain:
    def __init__(self):
        self.blocks: list = []
        self.states: list = []  # states[i] = stato DOPO il blocco i
        self._build_genesis()

    def _build_genesis(self) -> None:
        state, receipts = process_block(State(), 0, "GENESIS", [], is_genesis=True)
        hdr = {
            "index": 0, "timestamp": GENESIS_TS, "prev_hash": GENESIS_PREV, "miner": "GENESIS",
            "txs": [], "receipts": receipts, "state_hash": state.hash(),
            "difficulty": BASE_DIFFICULTY, "manifesto": MANIFESTO,
        }
        hdr["nonce"], _ = mine_nonce(hdr)
        self.blocks.append(hdr)
        self.states.append(state)

    @property
    def tip_state(self) -> State:
        return self.states[-1]

    @property
    def height(self) -> int:
        return self.blocks[-1]["index"]

    def mine_block(self, miner_addr: str, txs: list | None = None, timestamp=None) -> dict:
        """Conia un nuovo blocco sopra il tip, usando process_block (logica di consenso)."""
        txs = txs or []
        index = self.height + 1
        prev = self.blocks[-1]
        new_state, receipts = process_block(self.tip_state, index, miner_addr, txs)
        hdr = {
            "index": index,
            "timestamp": int(timestamp if timestamp is not None else time.time()),
            "prev_hash": header_pow_hash(prev),
            "miner": miner_addr,
            "txs": txs,
            "receipts": receipts,
            "state_hash": new_state.hash(),
            "difficulty": next_difficulty(self.blocks),
        }
        hdr["nonce"], _ = mine_nonce(hdr)
        self.blocks.append(hdr)
        self.states.append(new_state)
        return hdr

    @classmethod
    def from_blocks(cls, blocks: list) -> "Blockchain":
        """Costruisce una catena da una lista di blocchi (validandola col replay)."""
        ok, msg = cls.validate_chain(blocks)
        if not ok:
            raise ConsensusError(f"catena non valida: {msg}")
        bc = cls.__new__(cls)
        bc.blocks = [dict(b) for b in blocks]
        bc.states = bc._rebuild_states(bc.blocks)
        return bc

    @staticmethod
    def validate_chain(blocks: list):
        """Replay totale: ricostruisce lo stato e verifica PoW, linkage, ricevute, state_hash."""
        if not blocks or blocks[0]["index"] != 0:
            return False, "manca il blocco di genesi"
        g = blocks[0]
        if g.get("manifesto") != MANIFESTO:
            return False, "manifesto di genesi manomesso"
        if g["prev_hash"] != GENESIS_PREV:
            return False, "prev_hash di genesi non nullo"
        if g.get("difficulty") != BASE_DIFFICULTY:
            return False, "difficoltà di genesi non conforme"
        if not satisfies_pow(g):
            return False, "PoW di genesi non valida"
        gstate, greceipts = process_block(State(), 0, "GENESIS", [], is_genesis=True)
        if g["state_hash"] != gstate.hash():
            return False, "state_hash di genesi non corrisponde"
        if canonical(g["receipts"]) != canonical(greceipts):
            return False, "ricevute di genesi manomesse"

        state = gstate
        for i in range(1, len(blocks)):
            blk = blocks[i]
            prev = blocks[i - 1]
            if blk["index"] != i:
                return False, f"indice fuori sequenza al blocco {i}"
            if blk["prev_hash"] != header_pow_hash(prev):
                return False, f"prev_hash spezzato al blocco {i} (catena manomessa)"
            if blk.get("difficulty") != next_difficulty(blocks[:i]):
                return False, f"difficoltà non conforme al retargeting al blocco {i}"
            if not satisfies_pow(blk):
                return False, f"PoW non valida al blocco {i}"
            try:
                new_state, receipts = process_block(state, i, blk["miner"], blk["txs"])
            except ConsensusError as exc:
                return False, f"consenso violato al blocco {i}: {exc}"
            if canonical(receipts) != canonical(blk["receipts"]):
                return False, f"ricevute manomesse al blocco {i}"
            if new_state.hash() != blk["state_hash"]:
                return False, f"state_hash manomesso al blocco {i} (stato divergente dal replay)"
            state = new_state
        return True, "catena integra"

    def is_valid(self):
        return self.validate_chain(self.blocks)

    @property
    def tip_hash(self) -> str:
        return header_pow_hash(self.blocks[-1])

    # ── Supporto alla rete P2P (Milestone 2) ────────────────────────────────

    def add_external_block(self, block: dict):
        """
        Accoda un blocco ricevuto dalla rete SE estende esattamente il tip.
        Stessa validazione del consenso (PoW, linkage, replay, ricevute, state_hash).
        Ritorna (ok, motivo). Non risolve fork: per quello vedi maybe_replace_chain.
        """
        i = block["index"]
        if i != self.height + 1:
            return False, f"indice non consecutivo (atteso {self.height + 1}, ricevuto {i})"
        if block["prev_hash"] != self.tip_hash:
            return False, "prev_hash non aggancia il tip (possibile fork)"
        if block.get("difficulty") != next_difficulty(self.blocks):
            return False, "difficoltà non conforme al retargeting"
        if not satisfies_pow(block):
            return False, "PoW non valida"
        try:
            new_state, receipts = process_block(self.tip_state, i, block["miner"], block["txs"])
        except ConsensusError as exc:
            return False, f"consenso violato: {exc}"
        if canonical(receipts) != canonical(block["receipts"]):
            return False, "ricevute non corrispondono"
        if new_state.hash() != block["state_hash"]:
            return False, "state_hash non corrisponde"
        self.blocks.append(block)
        self.states.append(new_state)
        return True, "ok"

    def _rebuild_states(self, blocks: list) -> list:
        """Ricostruisce la lista degli stati replay-ando i blocchi (già validati)."""
        state = process_block(State(), 0, "GENESIS", [], is_genesis=True)[0]
        states = [state]
        for i in range(1, len(blocks)):
            blk = blocks[i]
            state, _ = process_block(state, i, blk["miner"], blk["txs"])
            states.append(state)
        return states

    def maybe_replace_chain(self, blocks: list):
        """
        Risoluzione fork LONGEST-CHAIN: adotta `blocks` se è strettamente più lunga
        della corrente ED è valida (replay totale). Ritorna (adottata, motivo).
        """
        if len(blocks) <= len(self.blocks):
            return False, "catena non più lunga della corrente"
        ok, msg = self.validate_chain(blocks)
        if not ok:
            return False, f"catena ricevuta non valida: {msg}"
        self.blocks = [dict(b) for b in blocks]
        self.states = self._rebuild_states(self.blocks)
        return True, f"adottata catena di {len(self.blocks)} blocchi"
