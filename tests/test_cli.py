# -*- coding: utf-8 -*-
"""Test della CLI e del client di rete (Milestone 4).

Verifica: roundtrip del wallet su file, conversione DMN→gocce, e il flusso reale
usato dai comandi (fetch_chain → nonce → make_tx → push_tx → blocco) contro un
nodo in esecuzione.
"""

import asyncio
import subprocess
import sys

from daimon.config import DMN
from daimon.core import Wallet, Blockchain, make_tx, make_genome, daimon_id
from daimon.network import Node
from daimon.network.client import fetch_chain, push_tx
from daimon.cli import dmn_to_gocce, parse_connect, parse_peers


def test_wallet_roundtrip(tmp_path):
    path = tmp_path / "alice.wallet"
    w = Wallet()
    w.save(str(path))
    w2 = Wallet.load(str(path))
    assert w2.address == w.address
    assert w2.secret_hex == w.secret_hex


def test_dmn_to_gocce():
    assert dmn_to_gocce("5") == 5 * DMN
    assert dmn_to_gocce("5.250") == 5250
    assert dmn_to_gocce("0.001") == 1
    assert dmn_to_gocce("20") == 20 * DMN


def test_parse_helpers():
    assert parse_connect("127.0.0.1:9101") == ("127.0.0.1", 9101)
    assert parse_peers("127.0.0.1:1,host:2") == [("127.0.0.1", 1), ("host", 2)]
    assert parse_peers("") == []


def test_cli_wallet_new_subprocess(tmp_path):
    path = tmp_path / "w.wallet"
    r = subprocess.run([sys.executable, "-m", "daimon.cli", "wallet", "new", "--out", str(path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert path.exists()
    w = Wallet.load(str(path))
    assert w.address.startswith("usr_")


async def _flow():
    node = Node("N", port=0)
    await node.start()
    try:
        # Bootstrap: il nodo conia per finanziare il fondatore (= wallet del nodo).
        ts = 1_700_000_000
        for _ in range(6):
            ts += 60
            await node.mine_once(timestamp=ts)

        # Il client (come la CLI) scarica la catena e calcola il nonce.
        blocks = await fetch_chain("127.0.0.1", node.port)
        chain = Blockchain.from_blocks(blocks)
        founder = node.wallet
        nonce = chain.tip_state.nonces.get(founder.address, 0)

        # Costruisce una SPAWN e la immette via push_tx (come `daimon spawn`).
        g = make_genome("ORACLE_MATH", "Tutto è numero", "rigorosa", [])
        tx = make_tx(founder, "SPAWN",
                     {"name": "Pythia", "genome": g, "endowment": 30 * DMN, "royalty_bp": 1000}, nonce)
        await push_tx("127.0.0.1", node.port, tx)
        await asyncio.sleep(0.2)
        assert tx["sig"] in node.mempool, "la tx non è arrivata nella mempool del nodo"

        # Il nodo conia: il daimon deve comparire in catena.
        ts += 60
        await node.mine_once(timestamp=ts)
        assert daimon_id(g) in node.chain.tip_state.daimons
    finally:
        await node.stop()
        await asyncio.sleep(0.1)


def test_cli_flow_spawn_via_client():
    asyncio.run(_flow())
