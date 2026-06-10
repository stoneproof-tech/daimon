# -*- coding: utf-8 -*-
"""Nodo P2P di DAIMON su asyncio — temprato per esposizione pubblica.

Responsabilità:
  * handshake e connessioni persistenti (inbound + outbound) verso i peer;
  * sync iniziale: alla connessione si scarica la catena più lunga;
  * gossip dei blocchi appena coniati/ricevuti e delle transazioni (mempool);
  * risoluzione dei fork con la regola LONGEST-CHAIN (delegata al core);
  * anti-entropia periodica (HELLO) per garantire la convergenza eventuale.

Difese (la porta del seed riceve traffico ostile dal giorno uno):
  * validazione rigorosa di OGNI messaggio prima che tocchi la chain;
  * tetti su dimensione messaggio, lunghezza catena, peer totali e per-IP, mempool;
  * rate limiting per connessione; timeout su handshake e su ogni lettura;
  * ban temporaneo dell'IP dopo N infrazioni; nessun input esterno fa crashare il nodo.

Tutte le mutazioni della catena passano da `process_block` (core), mai duplicato.
"""

import time
import asyncio

from ..core import Wallet, Blockchain, verify_tx_signature
from ..config import (
    ConsensusError,
    NET_MAX_MSG_BYTES, NET_MAX_CHAIN_BLOCKS, NET_MAX_PEERS, NET_MAX_CONN_PER_IP,
    NET_RATE_WINDOW, NET_RATE_MAX, NET_HANDSHAKE_TIMEOUT, NET_READ_TIMEOUT,
    NET_MAX_STRIKES, NET_BAN_SECONDS, NET_MAX_MEMPOOL,
)
from . import protocol as p


class Node:
    def __init__(self, name: str, host: str = "127.0.0.1", port: int = 0,
                 peers=(), wallet: Wallet | None = None, data_dir: str | None = None,
                 **limits):
        self.name = name
        self.host = host
        self.port = port
        self.peers = list(peers)
        self.wallet = wallet or Wallet()
        self.address = self.wallet.address
        self.chain = Blockchain()
        # Persistenza opzionale: store append-only su disco (vedi daimon/store.py).
        self.store = None
        if data_dir:
            from ..store import BlockStore
            self.store = BlockStore(f"{data_dir.rstrip('/')}/chain.jsonl")
        self.mempool: dict = {}
        self.writers: set = set()
        self.server = None
        self._lock = asyncio.Lock()
        self._running = False
        self._tasks: list = []

        # Parametri di sicurezza (sovrascrivibili dai test per esercitare i limiti).
        self.max_msg_bytes = limits.get("max_msg_bytes", NET_MAX_MSG_BYTES)
        self.max_chain_blocks = limits.get("max_chain_blocks", NET_MAX_CHAIN_BLOCKS)
        self.max_peers = limits.get("max_peers", NET_MAX_PEERS)
        self.max_conn_per_ip = limits.get("max_conn_per_ip", NET_MAX_CONN_PER_IP)
        self.rate_window = limits.get("rate_window", NET_RATE_WINDOW)
        self.rate_max = limits.get("rate_max", NET_RATE_MAX)
        self.handshake_timeout = limits.get("handshake_timeout", NET_HANDSHAKE_TIMEOUT)
        self.read_timeout = limits.get("read_timeout", NET_READ_TIMEOUT)
        self.max_strikes = limits.get("max_strikes", NET_MAX_STRIKES)
        self.ban_seconds = limits.get("ban_seconds", NET_BAN_SECONDS)
        self.max_mempool = limits.get("max_mempool", NET_MAX_MEMPOOL)

        self._conn_by_ip: dict = {}     # ip -> connessioni attive
        self._strikes: dict = {}        # ip -> infrazioni accumulate
        self._banned: dict = {}         # ip -> monotonic time di fine ban
        self.dropped = 0                # contatore di messaggi/connessioni rifiutati (osservabilità)

    # ── log ───────────────────────────────────────────────────────────────────
    def log(self, msg: str) -> None:
        print(f"  [{self.name}] {msg}")

    # ── avvio / arresto ───────────────────────────────────────────────────────
    async def start(self) -> None:
        # Carica e VALIDA la catena persistita PRIMA di servire (replay totale).
        if self.store is not None:
            from ..store import load_chain
            self.chain, info = load_chain(self.store)
            if info["loaded"]:
                self.log(f"catena ripristinata dal disco: {info['loaded']} blocchi "
                         f"(tip @ {self.chain.height})")
        self.server = await asyncio.start_server(
            self._on_inbound, self.host, self.port, limit=self.max_msg_bytes)
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

    # ── ban / rate ────────────────────────────────────────────────────────────
    def _is_banned(self, ip: str) -> bool:
        until = self._banned.get(ip)
        if until is None:
            return False
        if time.monotonic() >= until:
            self._banned.pop(ip, None)
            self._strikes.pop(ip, None)
            return False
        return True

    def _strike(self, ip: str, reason: str) -> None:
        n = self._strikes.get(ip, 0) + 1
        self._strikes[ip] = n
        self.dropped += 1
        if n >= self.max_strikes:
            self._banned[ip] = time.monotonic() + self.ban_seconds
            self.log(f"ban temporaneo di {ip} ({reason})")

    # ── connessioni ───────────────────────────────────────────────────────────
    async def _dial(self, host: str, port: int) -> None:
        while self._running:
            try:
                reader, writer = await asyncio.open_connection(host, port, limit=self.max_msg_bytes)
                await self._serve(reader, writer, outbound=True)
            except (ConnectionError, OSError):
                await asyncio.sleep(0.2)
            else:
                return
            if not self._running:
                return

    async def _on_inbound(self, reader, writer) -> None:
        await self._serve(reader, writer, outbound=False)

    async def _serve(self, reader, writer, outbound: bool) -> None:
        peer = writer.get_extra_info("peername")
        ip = peer[0] if peer else "?"

        # Filtri di ammissione: ban, tetto globale, tetto per-IP.
        if self._is_banned(ip) or len(self.writers) >= self.max_peers \
                or self._conn_by_ip.get(ip, 0) >= self.max_conn_per_ip:
            self.dropped += 1
            try:
                writer.close()
            except Exception:
                pass
            return

        self._conn_by_ip[ip] = self._conn_by_ip.get(ip, 0) + 1
        self.writers.add(writer)
        win_start = time.monotonic()
        win_count = 0
        first = True
        try:
            await self._send(writer, p.m_hello(self.chain.height, self.chain.tip_hash))
            while self._running:
                timeout = self.handshake_timeout if first else self.read_timeout
                try:
                    line = await asyncio.wait_for(reader.readline(), timeout)
                except asyncio.TimeoutError:
                    break
                except (ValueError, asyncio.LimitOverrunError):
                    self._strike(ip, "messaggio oltre il limite")  # riga troppo lunga
                    break
                except (ConnectionError, OSError):
                    break
                if not line:
                    break
                if len(line) > self.max_msg_bytes:
                    self._strike(ip, "messaggio troppo grande")
                    break
                first = False

                # Rate limiting per connessione (finestra scorrevole).
                now = time.monotonic()
                if now - win_start > self.rate_window:
                    win_start, win_count = now, 0
                win_count += 1
                if win_count > self.rate_max:
                    self._strike(ip, "flood")
                    break

                # Decode + validazione rigorosa PRIMA di toccare la chain.
                try:
                    msg = p.decode(line)
                    p.validate_message(msg, self.max_chain_blocks)
                except Exception:
                    self._strike(ip, "messaggio malformato")
                    break

                # Gestione: qualunque errore qui è trattato come infrazione, mai crash.
                try:
                    await self._handle(msg, writer)
                except Exception:
                    self._strike(ip, "errore di gestione")
                    break
        except (ConnectionError, OSError):
            pass
        finally:
            self.writers.discard(writer)
            self._conn_by_ip[ip] = max(0, self._conn_by_ip.get(ip, 1) - 1)
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
        while self._running:
            await asyncio.sleep(0.3)
            await self.broadcast(p.m_hello(self.chain.height, self.chain.tip_hash))

    # ── gestione messaggi ─────────────────────────────────────────────────────
    async def _handle(self, msg: dict, writer) -> None:
        t = msg["t"]
        if t == p.HELLO:
            if msg["height"] > self.chain.height or (
                    msg["height"] == self.chain.height and msg["tip"] != self.chain.tip_hash):
                await self._send(writer, p.m_getchain())
        elif t == p.GETCHAIN:
            await self._send(writer, p.m_chain(self.chain.blocks))
        elif t == p.CHAIN:
            await self._on_chain(msg["blocks"])
        elif t == p.BLOCK:
            await self._on_block(msg["block"], writer)
        elif t == p.TX:
            await self._on_tx(msg["tx"], writer)

    async def _on_chain(self, blocks: list) -> None:
        if not blocks:
            return
        async with self._lock:
            adopted, why = self.chain.maybe_replace_chain(blocks)
        if adopted:
            if self.store is not None:
                self.store.rewrite(self.chain.blocks[1:])  # fork adottato: riscrivi atomico
            self.log(f"sync: {why} (tip @ {self.chain.height})")
            self._purge_mempool()
            await self.broadcast(p.m_hello(self.chain.height, self.chain.tip_hash))

    async def _on_block(self, block: dict, writer) -> None:
        async with self._lock:
            ok, why = self.chain.add_external_block(block)
        if ok:
            if self.store is not None:
                self.store.append(block)
            self.log(f"blocco {block['index']} accettato dal gossip")
            self._purge_mempool()
            await self.broadcast(p.m_block(block), exclude=writer)
        else:
            if block["index"] >= self.chain.height + 1:
                await self._send(writer, p.m_getchain())

    async def _on_tx(self, tx: dict, writer) -> None:
        sig = tx.get("sig")
        if not sig or sig in self.mempool:
            return
        if len(self.mempool) >= self.max_mempool:
            self.dropped += 1
            return
        try:
            verify_tx_signature(tx)
        except ConsensusError:
            return
        self.mempool[sig] = tx
        await self.broadcast(p.m_tx(tx), exclude=writer)

    # ── mempool & mining ──────────────────────────────────────────────────────
    def submit_tx(self, tx: dict) -> None:
        sig = tx.get("sig")
        if sig and sig not in self.mempool and len(self.mempool) < self.max_mempool:
            self.mempool[sig] = tx

    async def gossip_tx(self, tx: dict) -> None:
        self.submit_tx(tx)
        await self.broadcast(p.m_tx(tx))

    def _select_txs(self) -> list:
        if not self.mempool:
            return []
        candidates = sorted(self.mempool.values(), key=lambda t: (t["from"], t["nonce"]))
        good: list = []
        from ..core import process_block
        for tx in candidates:
            try:
                process_block(self.chain.tip_state, self.chain.height + 1, self.address, good + [tx])
                good.append(tx)
            except ConsensusError:
                continue
        return good

    def _purge_mempool(self) -> None:
        included = set()
        for blk in self.chain.blocks:
            for tx in blk["txs"]:
                included.add(tx.get("sig"))
        self.mempool = {s: tx for s, tx in self.mempool.items() if s not in included}

    async def mine_once(self, timestamp=None) -> dict:
        async with self._lock:
            txs = self._select_txs()
            block = self.chain.mine_block(self.address, txs, timestamp=timestamp)
            if self.store is not None:
                self.store.append(block)
        self._purge_mempool()
        self.log(f"ho coniato il blocco {block['index']} ({len(txs)} tx) → gossip")
        await self.broadcast(p.m_block(block))
        return block
