# -*- coding: utf-8 -*-
"""Sicurezza di rete e fuzzing del nodo (pre-esposizione pubblica).

Il nodo deve: validare ogni messaggio prima che tocchi la chain, reggere input
ostili (byte casuali, JSON malformati, messaggi giganti, flood) senza MAI crashare
e mantenendo la chain integra, applicare rate limiting e ban temporaneo per IP.
"""

import json
import asyncio
import pytest

from daimon.network import protocol as p
from daimon.network.protocol import ProtocolError, validate_message
from daimon.network import Node
from daimon.network.client import fetch_chain


# ── Validazione del protocollo (unit) ────────────────────────────────────────

def test_validate_rifiuta_non_oggetto():
    with pytest.raises(ProtocolError):
        validate_message([1, 2, 3])
    with pytest.raises(ProtocolError):
        validate_message("ciao")


def test_validate_rifiuta_tipo_sconosciuto():
    with pytest.raises(ProtocolError):
        validate_message({"t": "EVIL"})
    with pytest.raises(ProtocolError):
        validate_message({"nope": 1})


def test_validate_hello_malformato():
    with pytest.raises(ProtocolError):
        validate_message({"t": "HELLO"})                       # campi mancanti
    with pytest.raises(ProtocolError):
        validate_message({"t": "HELLO", "height": -1, "tip": "x"})
    with pytest.raises(ProtocolError):
        validate_message({"t": "HELLO", "height": "alto", "tip": "x"})
    # valido
    assert validate_message({"t": "HELLO", "height": 0, "tip": "x"}) == "HELLO"


def test_validate_chain_troppo_lunga():
    msg = {"t": "CHAIN", "blocks": [{} for _ in range(5)]}
    with pytest.raises(ProtocolError):
        validate_message(msg, max_chain_blocks=3)


def test_validate_block_e_tx_malformati():
    with pytest.raises(ProtocolError):
        validate_message({"t": "BLOCK", "block": {"index": "no"}})
    with pytest.raises(ProtocolError):
        validate_message({"t": "TX", "tx": {"type": "TRANSFER"}})  # mancano campi
    # bool non è int valido per i campi interi
    with pytest.raises(ProtocolError):
        validate_message({"t": "HELLO", "height": True, "tip": "x"})


# ── Helper di rete grezza ────────────────────────────────────────────────────

async def _raw(port, payloads, consume_hello=True, settle=0.25):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    if consume_hello:
        try:
            await asyncio.wait_for(reader.readline(), 2)
        except Exception:
            pass
    for pl in payloads:
        writer.write(pl if isinstance(pl, (bytes, bytearray)) else pl.encode())
        await writer.drain()
    await asyncio.sleep(settle)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass


def _node_ok(node) -> bool:
    ok, _ = node.chain.is_valid()
    return node._running and ok


# ── Spazzatura: il nodo non crasha e resta servibile ─────────────────────────

async def _garbage_scenario():
    node = Node("S", port=0)
    await node.start()
    try:
        # Bytes casuali, JSON malformato, righe non-JSON, messaggio valido-ma-vuoto.
        await _raw(node.port, [
            b"\x00\xff\x10garbage non testuale\n",
            b"{ json rotto :::\n",
            b'"una stringa json valida ma non un messaggio"\n',
            b"{}\n",
            b'{"t":"NOPE"}\n',
        ])
        assert _node_ok(node), "il nodo non deve crashare per input ostile"

        # Dopo la spazzatura, un client legittimo è ancora servito.
        blocks = await fetch_chain("127.0.0.1", node.port)
        assert isinstance(blocks, list) and len(blocks) == 1   # solo la genesi
        assert node.dropped >= 1
    finally:
        await node.stop()
        await asyncio.sleep(0.05)


def test_garbage_non_crasha_e_resta_servibile():
    asyncio.run(_garbage_scenario())


# ── Messaggio gigante: rifiutato dal limite di dimensione ─────────────────────

async def _oversize_scenario():
    node = Node("S", port=0, max_msg_bytes=4096)  # limite piccolo per il test
    await node.start()
    try:
        # 64 KB senza newline: supera il buffer di lettura → rifiuto, niente crash.
        await _raw(node.port, [b"x" * 65536])
        assert _node_ok(node)
        assert node.dropped >= 1
    finally:
        await node.stop()
        await asyncio.sleep(0.05)


def test_messaggio_gigante_rifiutato():
    asyncio.run(_oversize_scenario())


# ── Flood: rate limiting → strike → ban temporaneo dell'IP ───────────────────

async def _flood_scenario():
    node = Node("S", port=0, rate_max=5, rate_window=30.0, max_strikes=2, ban_seconds=30.0)
    await node.start()
    try:
        hello = p.encode(p.m_hello(0, "x"))
        # Due tornate di flood: ogni tornata supera il rate → 1 strike; alla 2ª, ban.
        for _ in range(2):
            await _raw(node.port, [hello] * 40)
        assert node._is_banned("127.0.0.1"), "l'IP che flooda dev'essere bannato"
        assert _node_ok(node)
        # Una nuova connessione dall'IP bannato viene rifiutata (chiusa subito).
        before = node.dropped
        await _raw(node.port, [hello], consume_hello=False)
        assert node.dropped > before
    finally:
        await node.stop()
        await asyncio.sleep(0.05)


def test_flood_porta_al_ban():
    asyncio.run(_flood_scenario())


# ── Assalto totale su una catena viva: resta in piedi e integra ──────────────

async def _assault_scenario():
    node = Node("S", port=0)
    await node.start()
    try:
        ts = 1_700_000_000
        for _ in range(5):
            ts += 60
            await node.mine_once(timestamp=ts)
        h_before = node.chain.height

        # Mix ostile assortito.
        giant_chain = json.dumps({"t": "CHAIN", "blocks": [{} for _ in range(10)]}).encode() + b"\n"
        await _raw(node.port, [
            b"\xde\xad\xbe\xef\n",
            b"{\n",
            giant_chain,                                   # blocchi malformati
            p.encode({"t": "BLOCK", "block": {"index": "x"}}),
            p.encode({"t": "TX", "tx": {"type": "x"}}),
            b"non json affatto\n",
        ])
        assert _node_ok(node), "chain non integra dopo l'assalto"
        assert node.chain.height >= h_before

        # Il nodo conia ancora regolarmente.
        ts += 60
        await node.mine_once(timestamp=ts)
        assert node.chain.height == h_before + 1
        ok, msg = node.chain.is_valid()
        assert ok, msg
    finally:
        await node.stop()
        await asyncio.sleep(0.05)


def test_nodo_sopravvive_assalto_con_chain_integra():
    asyncio.run(_assault_scenario())


# ── Le difese non rompono il percorso buono: due nodi convergono ancora ──────

async def _good_path_scenario():
    A = Node("A", port=0)
    B = Node("B", port=0)
    await A.start()
    await B.start()
    B._tasks.append(asyncio.create_task(B._dial("127.0.0.1", A.port)))
    await asyncio.sleep(0.6)
    try:
        ts = 1_700_000_000
        for _ in range(4):
            ts += 60
            await A.mine_once(timestamp=ts)
        for _ in range(60):
            if A.chain.tip_hash == B.chain.tip_hash:
                break
            await asyncio.sleep(0.1)
        assert A.chain.tip_hash == B.chain.tip_hash, "i nodi devono ancora convergere"
    finally:
        await A.stop()
        await B.stop()
        await asyncio.sleep(0.05)


def test_difese_non_rompono_la_convergenza():
    asyncio.run(_good_path_scenario())
