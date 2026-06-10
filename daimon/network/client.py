# -*- coding: utf-8 -*-
"""Client leggero verso un nodo DAIMON in esecuzione (usato dalla CLI).

Riusa il protocollo P2P: si connette via TCP, scarica la catena (GETCHAIN/CHAIN)
oppure immette una transazione (TX) nella mempool del nodo, che la gossipa.
"""

import asyncio

from . import protocol as p


async def fetch_chain(host: str, port: int, timeout: float = 5.0) -> list:
    """Scarica la catena completa dal nodo. Ritorna la lista dei blocchi."""
    reader, writer = await asyncio.open_connection(host, port)
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
    """Immette una transazione nel nodo (che la aggiunge alla mempool e la gossipa)."""
    reader, writer = await asyncio.open_connection(host, port)
    try:
        writer.write(p.encode(p.m_tx(tx)))
        await writer.drain()
        await asyncio.sleep(settle)  # lascia propagare prima di chiudere
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
