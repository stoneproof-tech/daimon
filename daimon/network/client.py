# -*- coding: utf-8 -*-
"""Lightweight client to a running DAIMON node (used by the CLI).

Reuses the P2P protocol: connects over TCP and either downloads the chain
(GETCHAIN/CHAIN) or injects a transaction (TX) into the node's mempool, which the
node gossips.
"""

import asyncio

from . import protocol as p
from ..config import NET_MAX_MSG_BYTES

# Same reason as the node: a CHAIN message is one JSON line that can exceed asyncio's
# default 64 KB limit on long chains. Aligned with the node's cap.
STREAM_LIMIT = NET_MAX_MSG_BYTES


async def fetch_chain(host: str, port: int, timeout: float = 15.0) -> list:
    """Download the full chain from the node. Returns the list of blocks."""
    reader, writer = await asyncio.open_connection(host, port, limit=STREAM_LIMIT)
    try:
        writer.write(p.encode(p.m_getchain()))
        await writer.drain()
        while True:
            line = await asyncio.wait_for(reader.readline(), timeout)
            if not line:
                return []
            msg = p.decode(line)
            if msg.get("t") == p.CHAIN:
                return msg.get("blocks", [])
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass


async def push_tx(host: str, port: int, tx: dict, settle: float = 0.4) -> None:
    """Inject a transaction into the node (which adds it to the mempool and gossips it)."""
    reader, writer = await asyncio.open_connection(host, port, limit=STREAM_LIMIT)
    try:
        writer.write(p.encode(p.m_tx(tx)))
        await writer.drain()
        await asyncio.sleep(settle)  # let it propagate before closing
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
