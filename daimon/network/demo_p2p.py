# -*- coding: utf-8 -*-
"""Demo P2P: 3 nodi locali che convergono allo stesso state_hash.

    python -m daimon.network.demo_p2p

Mostra: handshake, sync iniziale, gossip di blocchi e transazioni, creazione di un
fork (due blocchi concorrenti alla stessa altezza) e sua risoluzione longest-chain.
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
    """Attende che tutti i nodi condividano lo stesso tip (e quindi lo stesso state_hash)."""
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
    # Ring: A→B→C→A. Ogni link è una connessione TCP, il gossip vi scorre in entrambi i versi.
    A = Node("A", port=9101, peers=[("127.0.0.1", 9102)])
    B = Node("B", port=9102, peers=[("127.0.0.1", 9103)])
    C = Node("C", port=9103, peers=[("127.0.0.1", 9101)])
    nodes = [A, B, C]

    _banner("AVVIO — 3 nodi in anello, handshake e sync")
    for n in nodes:
        await n.start()
    await asyncio.sleep(0.8)  # handshake + prime connessioni
    print(f"  Connessioni attive: A={len(A.writers)} B={len(B.writers)} C={len(C.writers)}")

    _banner("GOSSIP DI TRANSAZIONI — un daimon nasce via mempool condivisa")
    founder = A.wallet  # il fondatore vive sul nodo A
    # Prima il fondatore deve avere DMN: A conia qualche blocco (fair launch).
    ts = 1_700_000_000
    for _ in range(6):
        ts += 60
        await A.mine_once(timestamp=ts)
        await asyncio.sleep(0.15)
    await await_convergence(nodes)
    print(f"  Dopo il bootstrap di A: altezze A={A.chain.height} B={B.chain.height} C={C.chain.height}")

    # Il fondatore inietta una SPAWN su C: deve propagarsi nella mempool e finire in un blocco.
    g = make_genome("ORACLE_MATH", "Tutto è numero", "rigorosa", [])
    n = A.chain.tip_state.nonces.get(founder.address, 0)
    spawn_tx = make_tx(founder, "SPAWN", {"name": "Pythia", "genome": g,
                                          "endowment": 30 * DMN, "royalty_bp": 1000}, n)
    await C.gossip_tx(spawn_tx)  # immessa su C, deve raggiungere chi minerà
    await asyncio.sleep(0.5)
    print(f"  TX SPAWN immessa su C → in mempool: A={len(A.mempool)} B={len(B.mempool)} C={len(C.mempool)}")
    ts += 60
    await B.mine_once(timestamp=ts)  # B conia includendo la tx dalla mempool
    await await_convergence(nodes)
    alive = len(A.chain.tip_state.daimons)
    print(f"  Dopo il blocco di B: daimon vivi in catena = {alive} (atteso 1: Pythia)")

    _banner("FORK DELIBERATO — due blocchi concorrenti alla stessa altezza")
    h0 = A.chain.height
    # A e B coniano simultaneamente sul medesimo tip → fork all'altezza h0+1.
    ts += 60
    await asyncio.gather(A.mine_once(timestamp=ts), B.mine_once(timestamp=ts + 1))
    await asyncio.sleep(0.4)
    tips = {n.name: n.chain.tip_hash[:10] for n in nodes}
    print(f"  Fork in corso (altezza {h0+1}). Tip per nodo: {tips}")

    _banner("RISOLUZIONE LONGEST-CHAIN — una branch si allunga e vince")
    # C estende: la sua branch diventa strettamente più lunga → tutti la adottano.
    for _ in range(3):
        ts += 60
        await C.mine_once(timestamp=ts)
        await asyncio.sleep(0.3)
    converged = await await_convergence(nodes, timeout=10)

    _banner("ESITO")
    for nd in nodes:
        st = nd.chain.tip_state
        print(f"  {nd.name}: altezza={nd.chain.height}  tip={nd.chain.tip_hash[:16]}  "
              f"state_hash={st.hash()[:16]}  supply={fmt(st.supply())}")
    same_tip = len({nd.chain.tip_hash for nd in nodes}) == 1
    same_state = len({nd.chain.tip_state.hash() for nd in nodes}) == 1
    print(f"\n  Convergenza: {converged}  | stesso tip: {same_tip}  | stesso state_hash: {same_state}")
    for nd in nodes:
        ok, msg = nd.chain.is_valid()
        print(f"  Validazione {nd.name}: {ok} — {msg}")

    for nd in nodes:
        await nd.stop()
    print("\n  Πάντα ῥεῖ — tre nodi, una sola corrente.")


if __name__ == "__main__":
    asyncio.run(main())
