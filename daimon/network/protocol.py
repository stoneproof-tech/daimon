# -*- coding: utf-8 -*-
"""DAIMON-P2P line protocol: newline-delimited JSON messages.

Transport: TCP/asyncio. Each message is one UTF-8 JSON line terminated by '\n'.
Message types:
  HELLO    {height, tip}        — handshake / anti-entropy heartbeat
  GETCHAIN {}                   — request for the full chain
  CHAIN    {blocks}             — response with the chain (for sync and fork resolution)
  BLOCK    {block}              — gossip of a new block
  TX       {tx}                 — gossip of a transaction for the mempool

The message tags and field names are the wire format (shared between nodes); the
ProtocolError texts are diagnostics only.
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
    """Malformed or hostile inbound message: the sender must be disconnected."""


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes) -> dict:
    return json.loads(line.decode("utf-8"))


# ── Strict validation of inbound messages ────────────────────────────────────
# Every message from the network passes here BEFORE touching the chain: type, shape
# and sizes. Anything that does not match the schema raises ProtocolError.

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
        raise ProtocolError(f"{what}: expected object")
    for key, ok in schema.items():
        if key not in obj:
            raise ProtocolError(f"{what}: missing field '{key}'")
        if not ok(obj[key]):
            raise ProtocolError(f"{what}: wrong type for '{key}'")


def validate_tx(tx) -> None:
    _check(tx, _TX_SCHEMA, "tx")


def validate_block(b) -> None:
    _check(b, _BLOCK_SCHEMA, "block")
    if len(b["txs"]) > NET_MAX_TXS_PER_BLOCK:
        raise ProtocolError("block: too many transactions")
    for tx in b["txs"]:
        validate_tx(tx)


def validate_message(msg, max_chain_blocks: int = NET_MAX_CHAIN_BLOCKS) -> str:
    """Validate a message's shape/types/sizes. Returns the type; raises ProtocolError."""
    if not isinstance(msg, dict):
        raise ProtocolError("message is not an object")
    t = msg.get("t")
    if t not in KNOWN_TYPES:
        raise ProtocolError(f"unknown type: {t!r}")
    if t == HELLO:
        if not _is_int(msg.get("height")) or msg["height"] < 0:
            raise ProtocolError("HELLO: invalid height")
        if not _is_str(msg.get("tip")):
            raise ProtocolError("HELLO: invalid tip")
    elif t == CHAIN:
        blocks = msg.get("blocks")
        if not isinstance(blocks, list):
            raise ProtocolError("CHAIN: blocks is not a list")
        if len(blocks) > max_chain_blocks:
            raise ProtocolError("CHAIN: chain too long")
        for b in blocks:
            validate_block(b)
    elif t == BLOCK:
        validate_block(msg.get("block"))
    elif t == TX:
        validate_tx(msg.get("tx"))
    # GETCHAIN has no fields
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
