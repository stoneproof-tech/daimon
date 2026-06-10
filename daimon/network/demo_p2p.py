# -*- coding: utf-8 -*-
"""P2P demo: 3 local nodes converging to the same state_hash.

    python -m daimon.network.demo_p2p

Shows: handshake, initial sync, block and transaction gossip, creation of a fork
(two competing blocks at the same height) and its longest-chain resolution.
"""

import sys
import asyncio

from ..core import Wallet, make_tx, make_genome
from ..config import DMN, fmt
from .node import Node

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


async def await_convergence(nodes, timeout=8.0) -> bool:
    """Wait until all nodes share the same tip (hence the same state_hash)."""
    loop_deadline = timeout / 0.1
    i = 0
    while i < loop_deadline:
        tips = {n.chain.tip_hash for n in nodes}
        if len(tips) == 1:
            return True
        await asyncio.sleep(0.1)
        i += 1
    return False


def _banner(t):
    print("\n" + "═" * 78 + f"\n  {t}\n" + "═" * 78)


async def main() -> None:
    # Ring: A→B→C→A. Each link is a TCP connection; gossip flows both ways over it.
    A = Node("A", port=9101, peers=[("127.0.0.1", 9102)])
    B = Node("B", port=9102, peers=[("127.0.0.1", 9103)])
    C = Node("C", port=9103, peers=[("127.0.0.1", 9101)])
    nodes = [A, B, C]

    _banner("START — 3 nodes in a ring, handshake and sync")
    for n in nodes:
        await n.start()
    await asyncio.sleep(0.8)  # handshake + initial connections
    print(f"  Active connections: A={len(A.writers)} B={len(B.writers)} C={len(C.writers)}")

    _banner("TRANSACTION GOSSIP — a daimon is born via the shared mempool")
    founder = A.wallet  # the founder lives on node A
    # First the founder needs DMN: A mines some blocks (fair launch).
    ts = 1_700_000_000
    for _ in range(6):
        ts += 60
        await A.mine_once(timestamp=ts)
        await asyncio.sleep(0.15)
    await await_convergence(nodes)
    print(f"  After A's bootstrap: heights A={A.chain.height} B={B.chain.height} C={C.chain.height}")

    # The founder injects a SPAWN on C: it must propagate in the mempool and land in a block.
    g = make_genome("ORACLE_MATH", "All is number", "rigorous", [])
    n = A.chain.tip_state.nonces.get(founder.address, 0)
    spawn_tx = make_tx(founder, "SPAWN", {"name": "Pythia", "genome": g,
                                          "endowment": 30 * DMN, "royalty_bp": 1000}, n)
    await C.gossip_tx(spawn_tx)  # injected on C, must reach whoever mines
    await asyncio.sleep(0.5)
    print(f"  SPAWN tx injected on C → in mempool: A={len(A.mempool)} B={len(B.mempool)} C={len(C.mempool)}")
    ts += 60
    await B.mine_once(timestamp=ts)  # B mines, including the tx from the mempool
    await await_convergence(nodes)
    alive = len(A.chain.tip_state.daimons)
    print(f"  After B's block: living daimons on chain = {alive} (expected 1: Pythia)")

    _banner("DELIBERATE FORK — two competing blocks at the same height")
    h0 = A.chain.height
    # A and B mine simultaneously on the same tip → fork at height h0+1.
    ts += 60
    await asyncio.gather(A.mine_once(timestamp=ts), B.mine_once(timestamp=ts + 1))
    await asyncio.sleep(0.4)
    tips = {n.name: n.chain.tip_hash[:10] for n in nodes}
    print(f"  Fork in progress (height {h0+1}). Tip per node: {tips}")

    _banner("LONGEST-CHAIN RESOLUTION — one branch grows longer and wins")
    # C extends: its branch becomes strictly longer → everyone adopts it.
    for _ in range(3):
        ts += 60
        await C.mine_once(timestamp=ts)
        await asyncio.sleep(0.3)
    converged = await await_convergence(nodes, timeout=10)

    _banner("OUTCOME")
    for nd in nodes:
        st = nd.chain.tip_state
        print(f"  {nd.name}: height={nd.chain.height}  tip={nd.chain.tip_hash[:16]}  "
              f"state_hash={st.hash()[:16]}  supply={fmt(st.supply())}")
    same_tip = len({nd.chain.tip_hash for nd in nodes}) == 1
    same_state = len({nd.chain.tip_state.hash() for nd in nodes}) == 1
    print(f"\n  Converged: {converged}  | same tip: {same_tip}  | same state_hash: {same_state}")
    for nd in nodes:
        ok, msg = nd.chain.is_valid()
        print(f"  Validation {nd.name}: {ok} — {msg}")

    for nd in nodes:
        await nd.stop()
    print("\n  Πάντα ῥεῖ — three nodes, a single current.")


if __name__ == "__main__":
    asyncio.run(main())
