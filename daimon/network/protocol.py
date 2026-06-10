# -*- coding: utf-8 -*-
"""Protocollo di linea di DAIMON-P2P: messaggi JSON delimitati da newline.

Trasporto: TCP/asyncio. Ogni messaggio è una riga JSON UTF-8 terminata da '\n'.
Tipi di messaggio:
  HELLO    {height, tip}        — handshake / heartbeat anti-entropia
  GETCHAIN {}                   — richiesta della catena completa
  CHAIN    {blocks}             — risposta con la catena (per sync e fork-resolution)
  BLOCK    {block}              — gossip di un nuovo blocco
  TX       {tx}                 — gossip di una transazione per la mempool
"""

import json

from ..config import NET_MAX_CHAIN_BLOCKS, NET_MAX_TXS_PER_BLOCK

HELLO = "HELLO"
GETCHAIN = "GETCHAIN"
CHAIN = "CHAIN"
BLOCK = "BLOCK"
TX = "TX"

KNOWN_TYPES = (HELLO, GETCHAIN, CHAIN, BLOCK, TX)


class ProtocolError(Exception):
    """Messaggio in ingresso malformato o ostile: il mittente va disconnesso."""


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes) -> dict:
    return json.loads(line.decode("utf-8"))


# ── Validazione rigorosa dei messaggi in ingresso ────────────────────────────
# Ogni messaggio dalla rete passa di qui PRIMA di toccare la chain: tipi, forma e
# dimensioni. Tutto ciò che non rispetta lo schema solleva ProtocolError.

def _is_int(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)

def _is_str(x) -> bool:
    return isinstance(x, str)

_BLOCK_SCHEMA = {
    "index": _is_int, "timestamp": _is_int, "prev_hash": _is_str, "miner": _is_str,
    "txs": lambda x: isinstance(x, list), "receipts": lambda x: isinstance(x, list),
    "state_hash": _is_str, "difficulty": _is_int, "nonce": _is_int,
}
_TX_SCHEMA = {
    "type": _is_str, "from": _is_str, "nonce": _is_int,
    "payload": lambda x: isinstance(x, dict), "pubkey": _is_str, "sig": _is_str,
}


def _check(obj, schema, what: str) -> None:
    if not isinstance(obj, dict):
        raise ProtocolError(f"{what}: atteso oggetto")
    for key, ok in schema.items():
        if key not in obj:
            raise ProtocolError(f"{what}: campo mancante '{key}'")
        if not ok(obj[key]):
            raise ProtocolError(f"{what}: tipo errato per '{key}'")


def validate_tx(tx) -> None:
    _check(tx, _TX_SCHEMA, "tx")


def validate_block(b) -> None:
    _check(b, _BLOCK_SCHEMA, "blocco")
    if len(b["txs"]) > NET_MAX_TXS_PER_BLOCK:
        raise ProtocolError("blocco: troppe transazioni")
    for tx in b["txs"]:
        validate_tx(tx)


def validate_message(msg, max_chain_blocks: int = NET_MAX_CHAIN_BLOCKS) -> str:
    """Valida forma/tipi/dimensioni di un messaggio. Ritorna il tipo; solleva ProtocolError."""
    if not isinstance(msg, dict):
        raise ProtocolError("messaggio non è un oggetto")
    t = msg.get("t")
    if t not in KNOWN_TYPES:
        raise ProtocolError(f"tipo sconosciuto: {t!r}")
    if t == HELLO:
        if not _is_int(msg.get("height")) or msg["height"] < 0:
            raise ProtocolError("HELLO: height non valido")
        if not _is_str(msg.get("tip")):
            raise ProtocolError("HELLO: tip non valido")
    elif t == CHAIN:
        blocks = msg.get("blocks")
        if not isinstance(blocks, list):
            raise ProtocolError("CHAIN: blocks non è una lista")
        if len(blocks) > max_chain_blocks:
            raise ProtocolError("CHAIN: catena troppo lunga")
        for b in blocks:
            validate_block(b)
    elif t == BLOCK:
        validate_block(msg.get("block"))
    elif t == TX:
        validate_tx(msg.get("tx"))
    # GETCHAIN non ha campi
    return t


def m_hello(height: int, tip: str) -> dict:
    return {"t": HELLO, "height": height, "tip": tip}


def m_getchain() -> dict:
    return {"t": GETCHAIN}


def m_chain(blocks: list) -> dict:
    return {"t": CHAIN, "blocks": blocks}


def m_block(block: dict) -> dict:
    return {"t": BLOCK, "block": block}


def m_tx(tx: dict) -> dict:
    return {"t": TX, "tx": tx}
