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

HELLO = "HELLO"
GETCHAIN = "GETCHAIN"
CHAIN = "CHAIN"
BLOCK = "BLOCK"
TX = "TX"


def encode(msg: dict) -> bytes:
    return (json.dumps(msg, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def decode(line: bytes) -> dict:
    return json.loads(line.decode("utf-8"))


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
