# -*- coding: utf-8 -*-
"""Persistenza della catena: store append-only su disco (JSONL), scritture atomiche.

Formato: un blocco per riga JSON (UTF-8), in ordine di indice, dalla genesi+1 in poi
(la genesi è deterministica e ricostruita dal codice, non si serializza). Il percorso
tipico sul server è /var/lib/daimon/chain.jsonl.

Garanzie:
  * append di un blocco = una riga, con flush + fsync (durevole).
  * sostituzione completa (su fork adottato) = scrittura su file temporaneo + fsync +
    os.replace atomico.
  * in lettura, una coda corrotta o una scrittura parziale (ultima riga senza newline,
    o JSON illeggibile) viene scartata: si conserva il prefisso valido.

`load_chain` ricostruisce una Blockchain validando OGNI blocco col replay totale
(via add_external_block): un blocco che non aggancia/valida tronca la catena lì.
"""

import os
import json

from .core import Blockchain


class BlockStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    # ── scrittura ─────────────────────────────────────────────────────────────
    def append(self, block: dict) -> None:
        """Accoda un blocco come singola riga JSON, con fsync (durevole)."""
        line = (json.dumps(block, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with open(self.path, "ab") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def rewrite(self, blocks: list) -> None:
        """Riscrive l'intero store in modo atomico (per fork adottati / pulizia)."""
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            for b in blocks:
                f.write((json.dumps(b, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)  # atomico sullo stesso filesystem

    # ── lettura ───────────────────────────────────────────────────────────────
    def load_raw(self):
        """
        Legge i blocchi grezzi dal file. Tollera coda corrotta / scrittura parziale:
        ritorna (blocchi_validi_per_sintassi, n_righe_scartate).
        """
        if not os.path.exists(self.path):
            return [], 0
        with open(self.path, "rb") as f:
            raw = f.read()
        if not raw:
            return [], 0
        ends_nl = raw.endswith(b"\n")
        segments = raw.split(b"\n")
        blocks, dropped = [], 0
        for i, seg in enumerate(segments):
            if seg == b"":
                continue
            is_last_segment = (i == len(segments) - 1)
            if is_last_segment and not ends_nl:
                dropped += 1            # ultima riga senza newline = scrittura parziale
                break
            try:
                blocks.append(json.loads(seg.decode("utf-8")))
            except Exception:
                dropped += 1            # JSON illeggibile: scarta da qui in poi
                break
        return blocks, dropped


def load_chain(store: BlockStore):
    """
    Ricostruisce una Blockchain dallo store, validando OGNI blocco col replay totale.
    Ritorna (chain, info) con info = {'loaded', 'dropped', 'truncated_at'}.
    Se qualcosa è stato scartato/troncato, riscrive lo store sul prefisso valido.
    """
    chain = Blockchain()
    raw, dropped = store.load_raw()
    truncated_at = None
    loaded = 0
    for blk in raw:
        ok, why = chain.add_external_block(blk)
        if not ok:
            truncated_at = blk.get("index") if isinstance(blk, dict) else None
            print(f"  [store] blocco non valido ({why}): tronco la catena al blocco "
                  f"{chain.height} (valido).")
            break
        loaded += 1
    if dropped or truncated_at is not None:
        if dropped:
            print(f"  [store] {dropped} riga/e in coda corrotte o parziali: scartate.")
        store.rewrite(chain.blocks[1:])  # esclude la genesi; ripulisce il file
    return chain, {"loaded": loaded, "dropped": dropped, "truncated_at": truncated_at}
