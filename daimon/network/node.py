# -*- coding: utf-8 -*-
"""Nodo P2P di DAIMON su asyncio.

Responsabilità:
  * handshake e connessioni persistenti (inbound + outbound) verso i peer;
  * sync iniziale: alla connessione si scarica la catena più lunga;
  * gossip dei blocchi appena coniati/ricevuti e delle transazioni (mempool);
  * risoluzione dei fork con la regola LONGEST-CHAIN (delegata al core);
  * anti-entropia periodica (HELLO) per garantire la convergenza eventuale.

Tutte le mutazioni della catena passano da `process_block` (core), mai duplicato.
Un lock serializza le mutazioni di stato del nodo: il consenso resta deterministico.
"""

import asyncio

from ..core import Wallet, Blockchain, verify_tx_signature, process_block
from ..core.chain import header_pow_hash
from ..config import ConsensusError
from . import protocol as p


class Node:
    def __init__(self, name: str, host: str = "127.0.0.1", port: int = 0,
                 peers=(), wallet: Wallet | None = None):
        self.name = name
        self.host = host
        self.port = port
        self.peers = list(peers)            # [(host, port), ...] da contattare
        self.wallet = wallet or Wallet()
        self.address = self.wallet.address
        self.chain = Blockchain()
        self.mempool: dict = {}             # sig -> tx in attesa
        self.writers: set = set()           # StreamWriter attivi (peer connessi)
        self.server = None
        self._lock = asyncio.Lock()         # serializza le mutazioni della catena
        self._running = False
        self._tasks: list = []

    # ── log leggero ──────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        print(f"  [{self.name}] {msg}")

    # ── avvio / arresto ───────────────────────────────────────────────────────
    async def start(self) -> None:
        self.server = await asyncio.start_server(self._on_inbound, self.host, self.port)
        # se port==0, recupera quella assegnata dal SO
        self.port = self.server.sockets[0].getsockname()[1]
        self._running = True
        for (h, pt) in self.peers:
            self._tasks.append(asyncio.create_task(self._dial(h, pt)))
        self._tasks.append(asyncio.create_task(self._heartbeat()))

    async def stop(self) -> None:
        self._running = False
        for t in self._tasks:
            t.cancel()
        if self.server:
            self.server.close()
            try:
                await self.server.wait_closed()
            except Exception:
                pass
        for w in list(self.writers):
            try:
                w.close()
            except Exception:
                pass

    # ── connessioni ───────────────────────────────────────────────────────────
    async def _dial(self, host: str, port: int) -> None:
        while self._running:
            try:
                reader, writer = await asyncio.open_connection(host, port)
                await self._serve(reader, writer, outbound=True)
            except (ConnectionError, OSError):
                await asyncio.sleep(0.2)  # peer non ancora pronto: riprova
            else:
                return
            if not self._running:
                return

    async def _on_inbound(self, reader, writer) -> None:
        await self._serve(reader, writer, outbound=False)

    async def _serve(self, reader, writer, outbound: bool) -> None:
        self.writers.add(writer)
        try:
            await self._send(writer, p.m_hello(self.chain.height, self.chain.tip_hash))
            while self._running:
                line = await reader.readline()
                if not line:
                    break
                try:
                    msg = p.decode(line)
                except Exception:
                    continue
                await self._handle(msg, writer)
        except (ConnectionError, OSError):
            pass
        finally:
            self.writers.discard(writer)
            try:
                writer.close()
            except Exception:
                pass

    # ── invio ─────────────────────────────────────────────────────────────────
    async def _send(self, writer, msg: dict) -> None:
        try:
            writer.write(p.encode(msg))
            await writer.drain()
        except (ConnectionError, OSError):
            self.writers.discard(writer)

    async def broadcast(self, msg: dict, exclude=None) -> None:
        for w in list(self.writers):
            if w is exclude:
                continue
            await self._send(w, msg)

    async def _heartbeat(self) -> None:
        """Anti-entropia: annuncia periodicamente l'altezza → convergenza eventuale."""
        while self._running:
            await asyncio.sleep(0.3)
            await self.broadcast(p.m_hello(self.chain.height, self.chain.tip_hash))

    # ── gestione messaggi ─────────────────────────────────────────────────────
    async def _handle(self, msg: dict, writer) -> None:
        t = msg.get("t")
        if t == p.HELLO:
            # Se il peer è più avanti (o è in fork a pari/maggiore altezza), chiedi la catena.
            if msg.get("height", 0) > self.chain.height or (
                    msg.get("height", 0) == self.chain.height and msg.get("tip") != self.chain.tip_hash):
                await self._send(writer, p.m_getchain())
        elif t == p.GETCHAIN:
            await self._send(writer, p.m_chain(self.chain.blocks))
        elif t == p.CHAIN:
            await self._on_chain(msg.get("blocks", []))
        elif t == p.BLOCK:
            await self._on_block(msg.get("block"), writer)
        elif t == p.TX:
            await self._on_tx(msg.get("tx"), writer)

    async def _on_chain(self, blocks: list) -> None:
        if not blocks:
            return
        async with self._lock:
            adopted, why = self.chain.maybe_replace_chain(blocks)
        if adopted:
            self.log(f"sync: {why} (tip @ {self.chain.height})")
            self._purge_mempool()
            await self.broadcast(p.m_hello(self.chain.height, self.chain.tip_hash))

    async def _on_block(self, block: dict, writer) -> None:
        if not block:
            return
        async with self._lock:
            ok, why = self.chain.add_external_block(block)
        if ok:
            self.log(f"blocco {block['index']} accettato dal gossip")
            self._purge_mempool()
            await self.broadcast(p.m_block(block), exclude=writer)  # propaga
        else:
            # Non aggancia il tip: possibile fork o gap → chiedi la catena completa.
            if block["index"] >= self.chain.height + 1:
                await self._send(writer, p.m_getchain())

    async def _on_tx(self, tx: dict, writer) -> None:
        if not tx:
            return
        sig = tx.get("sig")
        if not sig or sig in self.mempool:
            return
        try:
            verify_tx_signature(tx)
        except ConsensusError:
            return
        self.mempool[sig] = tx
        await self.broadcast(p.m_tx(tx), exclude=writer)  # propaga la tx

    # ── mempool & mining ──────────────────────────────────────────────────────
    def submit_tx(self, tx: dict) -> None:
        """API locale: inserisce una tx nella mempool (sarà poi gossipata al prossimo giro)."""
        sig = tx.get("sig")
        if sig and sig not in self.mempool:
            self.mempool[sig] = tx

    async def gossip_tx(self, tx: dict) -> None:
        self.submit_tx(tx)
        await self.broadcast(p.m_tx(tx))

    def _select_txs(self) -> list:
        """Sceglie un sottoinsieme di tx della mempool applicabili al tip (in ordine nonce)."""
        if not self.mempool:
            return []
        candidates = sorted(self.mempool.values(), key=lambda t: (t["from"], t["nonce"]))
        good: list = []
        for tx in candidates:
            try:
                process_block(self.chain.tip_state, self.chain.height + 1, self.address, good + [tx])
                good.append(tx)
            except ConsensusError:
                continue
        return good

    def _purge_mempool(self) -> None:
        """Rimuove dalla mempool le tx già incluse in catena."""
        included = set()
        for blk in self.chain.blocks:
            for tx in blk["txs"]:
                included.add(tx.get("sig"))
        self.mempool = {s: tx for s, tx in self.mempool.items() if s not in included}

    async def mine_once(self, timestamp=None) -> dict:
        """Conia un blocco con le tx selezionate dalla mempool e lo diffonde in gossip."""
        async with self._lock:
            txs = self._select_txs()
            block = self.chain.mine_block(self.address, txs, timestamp=timestamp)
        self._purge_mempool()
        self.log(f"ho coniato il blocco {block['index']} ({len(txs)} tx) → gossip")
        await self.broadcast(p.m_block(block))
        return block
