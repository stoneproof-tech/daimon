# -*- coding: utf-8 -*-
"""Persistenza della catena su disco (store JSONL append-only).

Verifica: roundtrip store↔catena, equivalenza dopo riavvio del nodo (stesso
state_hash), recupero da coda corrotta, tolleranza a scrittura parziale,
troncamento all'ultimo blocco valido su blocco manomesso, e tenuta della rete
in periodi senza mining (seed solo-relay).
"""

import json
import asyncio

from daimon.config import DMN
from daimon.core import Wallet, Blockchain, make_tx, make_genome, daimon_id
from daimon.store import BlockStore, load_chain
from daimon.network import Node


# ── Helper ───────────────────────────────────────────────────────────────────

def _make_chain(n_blocks=6, with_spawn=True):
    chain = Blockchain()
    founder = Wallet()
    ts = 1_700_000_000
    for _ in range(n_blocks):
        ts += 60
        chain.mine_block(founder.address, [], timestamp=ts)
    if with_spawn:
        g = make_genome("ORACLE_MATH", "Tutto è numero", "rigorosa", [])
        nonce = chain.tip_state.nonces.get(founder.address, 0)
        tx = make_tx(founder, "SPAWN", {"name": "Pythia", "genome": g,
                                        "endowment": 30 * DMN, "royalty_bp": 1000}, nonce)
        chain.mine_block(founder.address, [tx], timestamp=ts + 60)
    return chain


def _persist(store, chain):
    for blk in chain.blocks[1:]:   # esclude la genesi
        store.append(blk)


# ── Roundtrip e equivalenza ──────────────────────────────────────────────────

def test_store_roundtrip_stesso_state_hash(tmp_path):
    chain = _make_chain()
    store = BlockStore(str(tmp_path / "chain.jsonl"))
    _persist(store, chain)
    loaded, info = load_chain(store)
    assert info["loaded"] == len(chain.blocks) - 1
    assert info["dropped"] == 0 and info["truncated_at"] is None
    assert loaded.height == chain.height
    assert loaded.tip_state.hash() == chain.tip_state.hash()
    ok, msg = loaded.is_valid()
    assert ok, msg


def test_rewrite_atomico_equivale(tmp_path):
    chain = _make_chain(4, with_spawn=False)
    store = BlockStore(str(tmp_path / "chain.jsonl"))
    store.rewrite(chain.blocks[1:])
    raw, dropped = store.load_raw()
    assert dropped == 0
    assert len(raw) == len(chain.blocks) - 1
    loaded, _ = load_chain(store)
    assert loaded.tip_state.hash() == chain.tip_state.hash()


# ── Robustezza in lettura ────────────────────────────────────────────────────

def test_coda_corrotta_troncata(tmp_path):
    chain = _make_chain(5, with_spawn=False)
    path = str(tmp_path / "chain.jsonl")
    store = BlockStore(path)
    _persist(store, chain)
    # Appendo una riga di spazzatura (JSON illeggibile) in coda.
    with open(path, "ab") as f:
        f.write(b"{ questo non e json valido :::\n")
    loaded, info = load_chain(store)
    assert info["dropped"] >= 1
    assert loaded.height == chain.height        # il prefisso valido è intatto
    assert loaded.tip_state.hash() == chain.tip_state.hash()
    # Lo store è stato ripulito: ora rilegge senza scarti.
    _, dropped2 = store.load_raw()
    assert dropped2 == 0


def test_scrittura_parziale_tollerata(tmp_path):
    chain = _make_chain(5, with_spawn=False)
    path = str(tmp_path / "chain.jsonl")
    store = BlockStore(path)
    _persist(store, chain)
    # Simulo una scrittura parziale: mezza riga JSON SENZA newline finale.
    with open(path, "ab") as f:
        f.write(b'{"index":99,"timestamp":1,"prev_ha')
    loaded, info = load_chain(store)
    assert info["dropped"] >= 1
    assert loaded.height == chain.height
    assert loaded.tip_state.hash() == chain.tip_state.hash()


def test_blocco_manomesso_tronca_all_ultimo_valido(tmp_path):
    chain = _make_chain(6, with_spawn=False)
    path = str(tmp_path / "chain.jsonl")
    store = BlockStore(path)
    # Persisto fino all'indice 4, poi appendo un blocco 5 MANOMESSO (JSON valido,
    # consenso no): il replay in load_chain deve troncare al 4.
    good = chain.blocks[1:5]          # indici 1..4
    for blk in good:
        store.append(blk)
    tampered = dict(chain.blocks[5])
    tampered["state_hash"] = "deadbeef"
    store.append(tampered)
    loaded, info = load_chain(store)
    assert info["truncated_at"] is not None
    assert loaded.height == 4
    ok, msg = loaded.is_valid()
    assert ok, msg
    # Dopo il troncamento lo store contiene solo il prefisso valido.
    raw, _ = store.load_raw()
    assert len(raw) == 4


# ── Riavvio del nodo: la catena sopravvive ───────────────────────────────────

async def _restart_scenario(data_dir):
    node = Node("A", port=0, data_dir=data_dir)
    await node.start()
    ts = 1_700_000_000
    for _ in range(5):
        ts += 60
        await node.mine_once(timestamp=ts)
    # SPAWN incluso, per avere stato non banale.
    g = make_genome("NOTARY", "Ciò che è inciso resta", "meticolosa", [])
    nonce = node.chain.tip_state.nonces.get(node.address, 0)
    tx = make_tx(node.wallet, "SPAWN", {"name": "Mnemo", "genome": g,
                                        "endowment": 30 * DMN, "royalty_bp": 1500}, nonce)
    await node.gossip_tx(tx)
    ts += 60
    await node.mine_once(timestamp=ts)
    h, tip, sh = node.chain.height, node.chain.tip_hash, node.chain.tip_state.hash()
    daimons = len(node.chain.tip_state.daimons)
    await node.stop()
    await asyncio.sleep(0.1)

    # Riavvio: nuovo Node, stessa data-dir.
    node2 = Node("A-restart", port=0, data_dir=data_dir)
    await node2.start()
    try:
        assert node2.chain.height == h, "altezza non conservata dopo il riavvio"
        assert node2.chain.tip_hash == tip, "tip diverso dopo il riavvio"
        assert node2.chain.tip_state.hash() == sh, "state_hash diverso dopo il riavvio"
        assert len(node2.chain.tip_state.daimons) == daimons
        ok, msg = node2.chain.is_valid()
        assert ok, msg
    finally:
        await node2.stop()
        await asyncio.sleep(0.05)


def test_riavvio_nodo_conserva_catena(tmp_path):
    asyncio.run(_restart_scenario(str(tmp_path / "seed")))


# ── La rete regge i periodi senza mining (seed solo-relay) ───────────────────

async def _relay_only_scenario():
    seed = Node("seed", port=0)            # NON mina (nessuno chiama mine_once)
    miner = Node("miner", port=0)
    await seed.start()
    await miner.start()
    miner._tasks.append(asyncio.create_task(miner._dial("127.0.0.1", seed.port)))
    await asyncio.sleep(0.6)
    try:
        # Il miner conia qualche blocco: il seed (relay) li riceve e si allinea.
        ts = 1_700_000_000
        for _ in range(4):
            ts += 60
            await miner.mine_once(timestamp=ts)
        for _ in range(60):
            if seed.chain.tip_hash == miner.chain.tip_hash:
                break
            await asyncio.sleep(0.1)
        assert seed.chain.tip_hash == miner.chain.tip_hash, "il seed non si è allineato"

        # Periodo SENZA mining: nessuno conia; la rete deve restare su e coerente.
        await asyncio.sleep(1.5)
        assert seed._running and miner._running
        assert seed.chain.tip_hash == miner.chain.tip_hash
        ok, _ = seed.chain.is_valid()
        assert ok
    finally:
        await seed.stop()
        await miner.stop()
        await asyncio.sleep(0.05)


def test_rete_regge_senza_mining():
    asyncio.run(_relay_only_scenario())
