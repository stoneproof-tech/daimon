# -*- coding: utf-8 -*-
"""Test d'integrazione della rete P2P (Milestone 2).

Verifica su 3 nodi locali: sync iniziale, gossip di blocchi, propagazione di una
transazione via mempool condivisa, e convergenza allo stesso state_hash dopo un
fork risolto con la regola longest-chain. Usa porte effimere (port=0).
"""

import asyncio
import pytest

from daimon.config import DMN
from daimon.core import make_tx, make_genome
from daimon.network import Node


async def _ring(*nodes):
    """Avvia i nodi e li collega in anello su porte effimere."""
    for nd in nodes:
        await nd.start()
    # ring: nodes[i] dial nodes[i+1]
    for i, nd in enumerate(nodes):
        nxt = nodes[(i + 1) % len(nodes)]
        nd._tasks.append(asyncio.create_task(nd._dial("127.0.0.1", nxt.port)))
    await asyncio.sleep(0.8)


async def _converged(nodes, timeout=10.0) -> bool:
    for _ in range(int(timeout / 0.1)):
        if len({n.chain.tip_hash for n in nodes}) == 1:
            return True
        await asyncio.sleep(0.1)
    return False


async def _scenario():
    A = Node("A", port=0)
    B = Node("B", port=0)
    C = Node("C", port=0)
    nodes = [A, B, C]
    await _ring(A, B, C)
    try:
        assert all(len(n.writers) >= 1 for n in nodes), "nodi non connessi"

        # Bootstrap: A conia 6 blocchi (fair launch), gossip → tutti allineati.
        ts = 1_700_000_000
        for _ in range(6):
            ts += 60
            await A.mine_once(timestamp=ts)
            await asyncio.sleep(0.12)
        assert await _converged(nodes), "no convergenza dopo il bootstrap"

        # Una SPAWN immessa su C deve propagarsi e finire in un blocco coniato da B.
        founder = A.wallet
        g = make_genome("ORACLE_MATH", "Tutto è numero", "rigorosa", [])
        n = A.chain.tip_state.nonces.get(founder.address, 0)
        tx = make_tx(founder, "SPAWN", {"name": "Pythia", "genome": g,
                                        "endowment": 30 * DMN, "royalty_bp": 1000}, n)
        await C.gossip_tx(tx)
        await asyncio.sleep(0.5)
        assert tx["sig"] in A.mempool and tx["sig"] in B.mempool, "tx non propagata in mempool"
        ts += 60
        await B.mine_once(timestamp=ts)
        assert await _converged(nodes), "no convergenza dopo il blocco con tx"
        assert len(A.chain.tip_state.daimons) == 1, "Pythia non risulta nata in catena"

        # Fork deliberato: A e B coniano alla stessa altezza, poi C allunga e vince.
        ts += 60
        await asyncio.gather(A.mine_once(timestamp=ts), B.mine_once(timestamp=ts + 1))
        await asyncio.sleep(0.4)
        for _ in range(3):
            ts += 60
            await C.mine_once(timestamp=ts)
            await asyncio.sleep(0.3)

        assert await _converged(nodes, timeout=12), "i nodi non sono convergenti dopo il fork"
        tip_hashes = {n.chain.tip_hash for n in nodes}
        state_hashes = {n.chain.tip_state.hash() for n in nodes}
        assert len(tip_hashes) == 1, "tip divergenti"
        assert len(state_hashes) == 1, "state_hash divergenti"
        for nd in nodes:
            ok, msg = nd.chain.is_valid()
            assert ok, f"catena {nd.name} non valida: {msg}"
    finally:
        for nd in nodes:
            await nd.stop()
        await asyncio.sleep(0.1)


def test_tre_nodi_convergono():
    asyncio.run(_scenario())
