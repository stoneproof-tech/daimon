# -*- coding: utf-8 -*-
"""DAIMON consensus constants and parameters.

Everything in drops (integers). 1 DMN = 1000 drops. No floats in consensus.
These values are part of consensus: changing them changes the chain.
"""

DMN = 1000  # drops per 1 DMN

# ── Proof-of-Work + difficulty retargeting (Milestone 3) ────────────────────
# Difficulty is an integer D ≥ 1: a block is valid if int(hash,16) ≤ MAX_HASH//D.
# D = 4096 is equivalent to "3 hex zeros" (target = 2^256 / 4096 = 2^244), the
# starting difficulty. Retargeting re-tunes D every RETARGET_INTERVAL blocks toward
# TARGET_BLOCK_TIME seconds/block, with a bounded adjustment factor (4x clamp).
MAX_HASH          = 1 << 256
BASE_DIFFICULTY   = 4096       # genesis difficulty (≈ 3 hex zeros)
RETARGET_INTERVAL = 10         # retarget difficulty every N blocks
TARGET_BLOCK_TIME = 60         # desired seconds/block
RETARGET_CLAMP    = 4          # difficulty cannot vary more than 4x per window

EMISSION       = 50 * DMN     # constant emission to the miner per block (no halving, no cap)
DEMURRAGE_NUM  = 98           # entropy: balance ← balance * 98 // 100 each block, on every account
DEMURRAGE_DEN  = 100

# ── Daimon lifecycle ────────────────────────────────────────────────────────
SPAWN_FEE       = 5 * DMN     # burned at a daimon's birth
MIN_ENDOWMENT   = 20 * DMN    # minimum endowment at birth
THINK_COST      = 2 * DMN     # burned per TASK
UPKEEP          = 1 * DMN     # metabolism: burned each block per living daimon
DEATH_THRESHOLD = DMN // 2    # 0.5 DMN: below this threshold the daimon dies (FOSSIL)

REPRO_BALANCE  = 50 * DMN     # reproduction: minimum balance
REPRO_TASKS    = 3            # reproduction: minimum tasks performed
CHILD_DOTE     = 25 * DMN     # endowment transferred to the child
ROYALTY_MAX_BP = 5000         # maximum royalty: 50% in basis points

# ── Genesis ─────────────────────────────────────────────────────────────────
GENESIS_PREV = "0" * 64
# Launch epoch engraved in genesis (Unix). Gives a realistic time reference to the
# first retargeting window (otherwise skewed by a timestamp of 0).
GENESIS_TS = 1_700_000_000
# CONSENSUS-FROZEN: the genesis manifesto is a consensus rule. Changing a single byte
# forks the chain. NEVER translate or edit it. (Meaning is glossed in the README.)
MANIFESTO = (
    "Πάντα ῥεῖ — nessuno si bagna due volte nello stesso fiume. "
    "Qui la materia inerte evapora e solo ciò che lavora persiste. "
    "Wörgl 1932 → Daimon 2026. Fair launch: nessun emittente, solo la sorgente."
)

# Theoretical supply equilibrium: S* = R / r = EMISSION / (1 - DEMURRAGE_NUM/DEMURRAGE_DEN).
S_STAR = (EMISSION * DEMURRAGE_DEN) // (DEMURRAGE_DEN - DEMURRAGE_NUM)  # = 2500 DMN in drops

# Minds recognized by the protocol.
KNOWN_MINDS = ("ORACLE_MATH", "NOTARY", "SCRIBE")

# ── Network: node security limits (the seed's port receives hostile traffic) ──
# Defensive, not consensus: a node may tighten these without breaking the network.
NET_MAX_MSG_BYTES     = 32 * 1024 * 1024  # cap on a single line/message (anti-OOM)
NET_MAX_CHAIN_BLOCKS  = 50_000            # max blocks accepted in a CHAIN message
NET_MAX_TXS_PER_BLOCK = 10_000            # max txs in a received block
NET_MAX_PEERS         = 256               # max simultaneous connections (total)
NET_MAX_CONN_PER_IP   = 64                # max simultaneous connections from one IP
NET_RATE_WINDOW       = 10.0              # rate-limiting window (s) per connection
NET_RATE_MAX          = 300               # max messages per window per connection
NET_HANDSHAKE_TIMEOUT = 10.0             # s within which the first message must arrive
NET_READ_TIMEOUT      = 30.0             # s of inactivity after which the connection closes
NET_MAX_STRIKES       = 5                 # strikes per IP before a temporary ban
NET_BAN_SECONDS       = 60.0             # duration of an IP's temporary ban
NET_MAX_MEMPOOL       = 10_000           # max txs kept in the mempool


class ConsensusError(Exception):
    """Consensus-rule violation: the block is invalid."""


def fmt(drops: int) -> str:
    """Format drops → DMN for printing (NOT used in consensus)."""
    sign = "-" if drops < 0 else ""
    g = abs(int(drops))
    return f"{sign}{g // DMN}.{g % DMN:03d} DMN"
