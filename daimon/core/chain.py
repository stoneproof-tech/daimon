# -*- coding: utf-8 -*-
"""process_block (the single consensus function), the block, the PoW and the chain.

process_block is used IDENTICALLY by mining and by validation. Validation is a full
replay from genesis: it rebuilds the state and checks PoW, linkage, receipts and the
state_hash of every block. Any tampering produces a divergence.

The "GENESIS" miner string, the header field names and MANIFESTO are consensus-
frozen. The (bool, message) diagnostics returned below are never serialized, so they
are in English.
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
    Apply a block to the previous state → (new_state, receipts).
    INVIOLABLE order: entropy → tx → emission → metabolism → reproduction → death.
    PURE function: same input ⇒ same output. No I/O, no floats.
    """
    state = prev_state.copy()
    receipts: list = []

    if is_genesis:
        # Genesis: no money created (fair launch, zero premine), only the manifesto.
        return state, receipts

    phase_entropy(state)                               # 1. ENTROPY
    phase_transactions(state, txs, receipts, index)    # 2. TRANSACTIONS
    phase_emission(state, miner)                       # 3. EMISSION
    phase_metabolism(state)                            # 4. METABOLISM
    phase_reproduction(state, receipts, index)         # 5. REPRODUCTION
    phase_death(state, receipts, index)                # 6. DEATH
    state.prune()
    return state, receipts


# ── Block & PoW ──────────────────────────────────────────────────────────────

def header_pow_hash(header: dict) -> str:
    return sha(canonical(header))


def pow_target(difficulty: int) -> int:
    """Max hash threshold for the given difficulty: a hash is valid if ≤ MAX_HASH//D."""
    return MAX_HASH // max(1, int(difficulty))


def satisfies_pow(header: dict) -> bool:
    """Check the PoW against the difficulty DECLARED in the header."""
    return int(header_pow_hash(header), 16) <= pow_target(header["difficulty"])


def next_difficulty(blocks: list) -> int:
    """
    DETERMINISTIC difficulty of the next block extending `blocks`.
    Unchanged except at RETARGET_INTERVAL boundaries, where it re-tunes toward
    TARGET_BLOCK_TIME seconds/block over the last window, clamped to RETARGET_CLAMP×.
    """
    last = blocks[-1]
    prev_diff = last["difficulty"]
    next_index = last["index"] + 1
    if next_index < RETARGET_INTERVAL or next_index % RETARGET_INTERVAL != 0:
        return prev_diff
    ref = blocks[-RETARGET_INTERVAL]                       # previous window boundary
    intervals = RETARGET_INTERVAL
    if ref["index"] == 0:
        # FIRST window: genesis carries GENESIS_TS, a FIXED epoch baked into the
        # protocol, NOT a real mining time. With a real clock `actual` would inflate
        # by years and crush difficulty to the clamp floor (an artifact). So we anchor
        # to block 1 and count only the truly timed intervals (block1→last), with
        # `expected` scaled accordingly.
        ref = blocks[1]
        intervals = last["index"] - ref["index"]          # = RETARGET_INTERVAL - 1
    actual = last["timestamp"] - ref["timestamp"]
    if actual <= 0:
        actual = 1
    expected = intervals * TARGET_BLOCK_TIME
    # Blocks too fast (actual < expected) ⇒ difficulty rises; too slow ⇒ it falls.
    new_diff = prev_diff * expected // actual
    lo, hi = prev_diff // RETARGET_CLAMP, prev_diff * RETARGET_CLAMP
    new_diff = max(lo, min(hi, new_diff))
    return max(1, new_diff)


def mine_nonce(header_wo_nonce: dict):
    """Proof-of-Work: find a nonce such that the hash satisfies the header's difficulty."""
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
        self.states: list = []  # states[i] = state AFTER block i
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
        """Mine a new block on top of the tip, using process_block (consensus logic)."""
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
        """Build a chain from a list of blocks (validating it by replay)."""
        ok, msg = cls.validate_chain(blocks)
        if not ok:
            raise ConsensusError(f"invalid chain: {msg}")
        bc = cls.__new__(cls)
        bc.blocks = [dict(b) for b in blocks]
        bc.states = bc._rebuild_states(bc.blocks)
        return bc

    @staticmethod
    def validate_chain(blocks: list):
        """Full replay: rebuild the state and check PoW, linkage, receipts, state_hash."""
        if not blocks or blocks[0]["index"] != 0:
            return False, "missing genesis block"
        g = blocks[0]
        if g.get("manifesto") != MANIFESTO:
            return False, "genesis manifesto tampered"
        if g["prev_hash"] != GENESIS_PREV:
            return False, "genesis prev_hash not null"
        if g.get("difficulty") != BASE_DIFFICULTY:
            return False, "genesis difficulty mismatch"
        if not satisfies_pow(g):
            return False, "invalid genesis PoW"
        gstate, greceipts = process_block(State(), 0, "GENESIS", [], is_genesis=True)
        if g["state_hash"] != gstate.hash():
            return False, "genesis state_hash mismatch"
        if canonical(g["receipts"]) != canonical(greceipts):
            return False, "genesis receipts tampered"

        state = gstate
        for i in range(1, len(blocks)):
            blk = blocks[i]
            prev = blocks[i - 1]
            if blk["index"] != i:
                return False, f"out-of-sequence index at block {i}"
            if blk["prev_hash"] != header_pow_hash(prev):
                return False, f"broken prev_hash at block {i} (chain tampered)"
            if blk.get("difficulty") != next_difficulty(blocks[:i]):
                return False, f"difficulty mismatch (retargeting) at block {i}"
            if not satisfies_pow(blk):
                return False, f"invalid PoW at block {i}"
            try:
                new_state, receipts = process_block(state, i, blk["miner"], blk["txs"])
            except ConsensusError as exc:
                return False, f"consensus violated at block {i}: {exc}"
            if canonical(receipts) != canonical(blk["receipts"]):
                return False, f"tampered receipts at block {i}"
            if new_state.hash() != blk["state_hash"]:
                return False, f"tampered state_hash at block {i} (state diverges from replay)"
            state = new_state
        return True, "chain valid"

    def is_valid(self):
        return self.validate_chain(self.blocks)

    @property
    def tip_hash(self) -> str:
        return header_pow_hash(self.blocks[-1])

    # ── P2P network support (Milestone 2) ───────────────────────────────────

    def add_external_block(self, block: dict):
        """
        Append a block received from the network IF it exactly extends the tip.
        Same consensus validation (PoW, linkage, replay, receipts, state_hash).
        Returns (ok, reason). Does not resolve forks: see maybe_replace_chain.
        """
        i = block["index"]
        if i != self.height + 1:
            return False, f"non-consecutive index (expected {self.height + 1}, got {i})"
        if block["prev_hash"] != self.tip_hash:
            return False, "prev_hash does not attach to tip (possible fork)"
        if block.get("difficulty") != next_difficulty(self.blocks):
            return False, "difficulty mismatch (retargeting)"
        if not satisfies_pow(block):
            return False, "invalid PoW"
        try:
            new_state, receipts = process_block(self.tip_state, i, block["miner"], block["txs"])
        except ConsensusError as exc:
            return False, f"consensus violated: {exc}"
        if canonical(receipts) != canonical(block["receipts"]):
            return False, "receipts mismatch"
        if new_state.hash() != block["state_hash"]:
            return False, "state_hash mismatch"
        self.blocks.append(block)
        self.states.append(new_state)
        return True, "ok"

    def _rebuild_states(self, blocks: list) -> list:
        """Rebuild the list of states by replaying the (already validated) blocks."""
        state = process_block(State(), 0, "GENESIS", [], is_genesis=True)[0]
        states = [state]
        for i in range(1, len(blocks)):
            blk = blocks[i]
            state, _ = process_block(state, i, blk["miner"], blk["txs"])
            states.append(state)
        return states

    def maybe_replace_chain(self, blocks: list):
        """
        LONGEST-CHAIN fork resolution: adopt `blocks` if it is strictly longer than
        the current one AND valid (full replay). Returns (adopted, reason).
        """
        if len(blocks) <= len(self.blocks):
            return False, "chain not longer than current"
        ok, msg = self.validate_chain(blocks)
        if not ok:
            return False, f"received chain invalid: {msg}"
        self.blocks = [dict(b) for b in blocks]
        self.states = self._rebuild_states(self.blocks)
        return True, f"adopted chain of {len(self.blocks)} blocks"
