# -*- coding: utf-8 -*-
"""Chain persistence: append-only on-disk store (JSONL), atomic writes.

Format: one block per JSON line (UTF-8), in index order, from genesis+1 onward (the
genesis is deterministic and rebuilt by the code, never serialized). The typical
path on the server is /var/lib/daimon/chain.jsonl.

Guarantees:
  * appending a block = one line, with flush + fsync (durable).
  * full replacement (on an adopted fork) = write to a temp file + fsync +
    atomic os.replace.
  * on read, a corrupted tail or a partial write (last line without a newline, or
    unreadable JSON) is dropped: the valid prefix is kept.

`load_chain` rebuilds a Blockchain validating EVERY block by full replay (via
add_external_block): a block that does not attach/validate truncates the chain there.
"""

import os
import json

from .core import Blockchain


class BlockStore:
    def __init__(self, path: str):
        self.path = path
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)

    # ── writing ───────────────────────────────────────────────────────────────
    def append(self, block: dict) -> None:
        """Append a block as a single JSON line, with fsync (durable)."""
        line = (json.dumps(block, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with open(self.path, "ab") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())

    def rewrite(self, blocks: list) -> None:
        """Atomically rewrite the whole store (for adopted forks / cleanup)."""
        tmp = self.path + ".tmp"
        with open(tmp, "wb") as f:
            for b in blocks:
                f.write((json.dumps(b, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)  # atomic on the same filesystem

    # ── reading ───────────────────────────────────────────────────────────────
    def load_raw(self):
        """
        Read the raw blocks from the file. Tolerates a corrupted tail / partial write:
        returns (syntactically_valid_blocks, dropped_line_count).
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
                dropped += 1            # last line without a newline = partial write
                break
            try:
                blocks.append(json.loads(seg.decode("utf-8")))
            except Exception:
                dropped += 1            # unreadable JSON: drop from here on
                break
        return blocks, dropped


def load_chain(store: BlockStore):
    """
    Rebuild a Blockchain from the store, validating EVERY block by full replay.
    Returns (chain, info) with info = {'loaded', 'dropped', 'truncated_at'}.
    If anything was dropped/truncated, rewrites the store to the valid prefix.
    """
    chain = Blockchain()
    raw, dropped = store.load_raw()
    truncated_at = None
    loaded = 0
    for blk in raw:
        ok, why = chain.add_external_block(blk)
        if not ok:
            truncated_at = blk.get("index") if isinstance(blk, dict) else None
            print(f"  [store] invalid block ({why}): truncating the chain at block "
                  f"{chain.height} (valid).")
            break
        loaded += 1
    if dropped or truncated_at is not None:
        if dropped:
            print(f"  [store] {dropped} corrupted/partial trailing line(s): dropped.")
        store.rewrite(chain.blocks[1:])  # excludes genesis; cleans the file
    return chain, {"loaded": loaded, "dropped": dropped, "truncated_at": truncated_at}
