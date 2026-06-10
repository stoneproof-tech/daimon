# -*- coding: utf-8 -*-
"""Minimal DAIMON block explorer (stdlib only).

Shows: chain overview and blocks, daimon genomes, genealogy trees (living +
fossils), fossils and royalties. Rendering is made of PURE functions of the
`Blockchain`, so it is testable without a server.

    daimon explorer --connect 127.0.0.1:9101     # reads from a running node
    daimon explorer --demo                        # in-memory sample chain
    python -m daimon.explorer --demo --port 8080
"""

import sys
import html
import asyncio
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .config import S_STAR, fmt, DMN
from .core import Wallet, Blockchain, make_tx, make_genome, daimon_id
from .core.chain import header_pow_hash

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ══════════════════════════════════════════════════════════════════════════════
#  Sample chain (for --demo and tests): births, work, reproduction, death
# ══════════════════════════════════════════════════════════════════════════════

def build_sample_chain() -> Blockchain:
    chain = Blockchain()
    founder = Wallet()
    ts = 1_700_000_000

    def mine(txs=None):
        nonlocal ts
        ts += 60
        return chain.mine_block(founder.address, txs or [], timestamp=ts)

    for _ in range(8):
        mine()

    def nonce():
        return chain.tip_state.nonces.get(founder.address, 0)

    g_p = make_genome("ORACLE_MATH", "All is number", "rigorous", [])
    g_m = make_genome("NOTARY", "What is engraved remains", "meticulous", [])
    g_h = make_genome("SCRIBE", "I carry words between worlds", "ironic", [])
    mine([
        make_tx(founder, "SPAWN", {"name": "Pythia", "genome": g_p, "endowment": 30 * DMN, "royalty_bp": 1000}, nonce()),
        make_tx(founder, "SPAWN", {"name": "Mnemo", "genome": g_m, "endowment": 30 * DMN, "royalty_bp": 1500}, nonce() + 1),
        make_tx(founder, "SPAWN", {"name": "Hermes", "genome": g_h, "endowment": 20 * DMN, "royalty_bp": 1000}, nonce() + 2),
    ])
    pid, hid = daimon_id(g_p), daimon_id(g_h)
    # Work for Mnemo and reproduction of Pythia (well-paid tasks).
    mine([make_tx(founder, "TASK", {"daimon": daimon_id(g_m), "payload": "act-1", "payment": 12 * DMN}, nonce())])
    for k in range(12):
        mine([make_tx(founder, "TASK", {"daimon": pid, "payload": f"{3+k}*{7+k}", "payment": 30 * DMN}, nonce())])
        if any(r["k"] == "BIRTH" for r in chain.blocks[-1]["receipts"]):
            break
    # Hermes starves to death.
    for _ in range(120):
        mine()
        if any(f["id"] == hid for f in chain.tip_state.fossils):
            break
    return chain


# ══════════════════════════════════════════════════════════════════════════════
#  Rendering (pure functions of the Blockchain)
# ══════════════════════════════════════════════════════════════════════════════

_CSS = """
body{font-family:system-ui,Segoe UI,sans-serif;margin:0;background:#0e1116;color:#d7dde5}
header{background:#161b22;padding:14px 24px;border-bottom:1px solid #283040}
header a{color:#7ee0c0;text-decoration:none;margin-right:18px;font-weight:600}
header .t{color:#9aa4b2;margin-right:24px;font-weight:700;letter-spacing:.5px}
main{padding:24px;max-width:1100px;margin:auto}
h1,h2{color:#e8eef6} h2{border-bottom:1px solid #283040;padding-bottom:6px;margin-top:30px}
table{border-collapse:collapse;width:100%;margin:10px 0}
th,td{border:1px solid #283040;padding:6px 10px;text-align:left;font-size:14px}
th{background:#161b22;color:#9aa4b2}
tr:nth-child(even){background:#11161d}
.k{color:#7ee0c0}.dim{color:#9aa4b2}.warn{color:#e0a07e}
.card{background:#11161d;border:1px solid #283040;border-radius:8px;padding:14px 18px;display:inline-block;margin:6px 14px 6px 0}
.card b{font-size:22px;color:#e8eef6}
code{color:#bcd0ff;font-size:13px}
ul.tree{list-style:none}ul.tree li{margin:4px 0;border-left:1px solid #283040;padding-left:14px}
.mono{font-family:Consolas,monospace}
.q{color:#7e8aa0;font-style:italic}
"""

_MINDS_GLYPH = {"ORACLE_MATH": "🔢", "NOTARY": "📜", "SCRIBE": "✒️"}


def _esc(x) -> str:
    return html.escape(str(x))


def _page(body: str, title: str = "DAIMON Explorer") -> str:
    nav = ('<header><span class="t">⟁ DAIMON</span>'
           '<a href="/">Overview</a><a href="/daimons">Daimons</a>'
           '<a href="/genealogy">Genealogy</a><a href="/fossils">Fossils</a></header>')
    return (f"<!doctype html><html lang='en'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>{_esc(title)}</title><style>{_CSS}</style></head>"
            f"<body>{nav}<main>{body}</main></body></html>")


def _records(chain: Blockchain) -> dict:
    """Map id → record for living and fossil daimons (for genealogy and links)."""
    st = chain.tip_state
    recs = {}
    for did, d in st.daimons.items():
        recs[did] = {**d, "alive": True}
    for f in st.fossils:
        recs[f["id"]] = {**f, "alive": False}
    return recs


def render_index(chain: Blockchain) -> str:
    st = chain.tip_state
    tip = chain.blocks[-1]
    pct = st.supply() * 100 // S_STAR if S_STAR else 0
    cards = (
        f'<div class="card">height<br><b>{chain.height}</b></div>'
        f'<div class="card">difficulty<br><b>{tip["difficulty"]}</b></div>'
        f'<div class="card">supply<br><b>{_esc(fmt(st.supply()))}</b><br>'
        f'<span class="dim">{pct}% of S* ({_esc(fmt(S_STAR))})</span></div>'
        f'<div class="card">living daimons<br><b>{len(st.daimons)}</b></div>'
        f'<div class="card">fossils<br><b>{len(st.fossils)}</b></div>'
    )
    rows = []
    for blk in reversed(chain.blocks[-25:]):
        kinds = ", ".join(sorted({r["k"] for r in blk["receipts"]})) or "—"
        rows.append(
            f"<tr><td><a class='k' href='/block?i={blk['index']}'>#{blk['index']}</a></td>"
            f"<td class='mono dim'>{_esc(header_pow_hash(blk)[:18])}…</td>"
            f"<td>{len(blk['txs'])}</td><td class='dim'>{_esc(kinds)}</td>"
            f"<td class='mono dim'>{_esc(blk['miner'][:16])}</td></tr>")
    body = (
        '<h1>Overview</h1><p class="q">"Only what works persists."</p>'
        f'{cards}'
        '<h2>Latest blocks</h2><table><tr><th>block</th><th>hash</th><th>tx</th>'
        '<th>events</th><th>miner</th></tr>' + "".join(rows) + "</table>")
    return _page(body)


def render_block(chain: Blockchain, i: int) -> str:
    if i < 0 or i >= len(chain.blocks):
        return _page(f"<h1>Block {i}</h1><p class='warn'>Nonexistent.</p>")
    blk = chain.blocks[i]
    head = (
        f"<h1>Block #{blk['index']}</h1>"
        f"<table>"
        f"<tr><th>hash</th><td class='mono'>{_esc(header_pow_hash(blk))}</td></tr>"
        f"<tr><th>prev_hash</th><td class='mono dim'>{_esc(blk['prev_hash'])}</td></tr>"
        f"<tr><th>state_hash</th><td class='mono dim'>{_esc(blk['state_hash'])}</td></tr>"
        f"<tr><th>timestamp</th><td>{_esc(blk['timestamp'])}</td></tr>"
        f"<tr><th>difficulty</th><td>{_esc(blk['difficulty'])}</td></tr>"
        f"<tr><th>nonce</th><td>{_esc(blk['nonce'])}</td></tr>"
        f"<tr><th>miner</th><td class='mono'>{_esc(blk['miner'])}</td></tr>"
        f"</table>")
    if blk.get("manifesto"):
        head += f"<h2>Manifesto</h2><p class='q'>{_esc(blk['manifesto'])}</p>"
    rrows = []
    for r in blk["receipts"]:
        detail = {k: v for k, v in r.items() if k != "k"}
        rrows.append(f"<tr><td class='k'>{_esc(r['k'])}</td>"
                     f"<td class='mono'>{_esc(detail)}</td></tr>")
    receipts = ("<h2>Receipts</h2><table><tr><th>type</th><th>detail</th></tr>"
                + ("".join(rrows) or "<tr><td colspan=2 class='dim'>none</td></tr>") + "</table>")
    return _page(head + receipts, f"Block {i}")


def render_daimons(chain: Blockchain) -> str:
    st = chain.tip_state
    rows = []
    for did in sorted(st.daimons):
        d = st.daimons[did]
        bal = st.balances.get(d["address"], 0)
        glyph = _MINDS_GLYPH.get(d["mind"], "•")
        rows.append(
            f"<tr><td>{glyph} <b>{_esc(d['name'])}</b><br>"
            f"<code>{_esc(did)}</code></td>"
            f"<td>{_esc(d['mind'])}</td>"
            f"<td class='q'>\"{_esc(d['motto'])}\"<br><span class='dim'>{_esc(d['indole'])}</span></td>"
            f"<td>gen {d['generation']}</td><td>{d['tasks']}</td>"
            f"<td>{d['royalty_bp']/100:.0f}%</td><td>{_esc(fmt(bal))}</td></tr>")
    body = ("<h1>Living daimons</h1>"
            "<table><tr><th>genome</th><th>mind</th><th>indole</th><th>gen</th>"
            "<th>tasks</th><th>royalty</th><th>balance</th></tr>"
            + ("".join(rows) or "<tr><td colspan=7 class='dim'>none</td></tr>") + "</table>")
    return _page(body, "Daimons")


def render_genealogy(chain: Blockchain) -> str:
    recs = _records(chain)
    children: dict = {}
    roots = []
    for did, r in recs.items():
        lineage = r.get("lineage", [])
        parent = lineage[-1] if lineage else None
        if parent and parent in recs:
            children.setdefault(parent, []).append(did)
        else:
            roots.append(did)

    def node_html(did: str) -> str:
        r = recs[did]
        glyph = _MINDS_GLYPH.get(r["mind"], "•")
        status = "" if r["alive"] else " <span class='warn'>† fossil</span>"
        label = (f"{glyph} <b>{_esc(r['name'])}</b> "
                 f"<span class='dim'>gen{r['generation']} · {r['royalty_bp']/100:.0f}% · "
                 f"<code>{_esc(did)}</code></span>{status}")
        kids = children.get(did, [])
        inner = ""
        if kids:
            inner = "<ul class='tree'>" + "".join(f"<li>{node_html(k)}</li>" for k in sorted(kids)) + "</ul>"
        return label + inner

    forest = "".join(f"<li>{node_html(r)}</li>" for r in sorted(roots))
    body = ("<h1>Genealogy trees</h1>"
            "<p class='dim'>Every reproduction mutates the genome (motto + lineage): "
            "id and address change, but the lineage stays tracked.</p>"
            + (f"<ul class='tree'>{forest}</ul>" if forest else "<p class='dim'>no daimon</p>"))
    return _page(body, "Genealogy")


def render_fossils(chain: Blockchain) -> str:
    foss = chain.tip_state.fossils
    rows = []
    for f in foss:
        glyph = _MINDS_GLYPH.get(f["mind"], "•")
        rows.append(
            f"<tr><td>† {glyph} <b>{_esc(f['name'])}</b><br><code>{_esc(f['id'])}</code></td>"
            f"<td>{_esc(f['mind'])}</td><td>gen {f['generation']}</td>"
            f"<td>{f['born']}</td><td>{f['died']}</td>"
            f"<td>{_esc(fmt(f['last_balance']))}</td></tr>")
    body = ("<h1>Fossils</h1><p class='q'>\"Inert matter evaporates.\"</p>"
            "<table><tr><th>genome</th><th>mind</th><th>gen</th><th>born</th>"
            "<th>died</th><th>last balance</th></tr>"
            + ("".join(rows) or "<tr><td colspan=6 class='dim'>no fossil</td></tr>") + "</table>")
    return _page(body, "Fossils")


def route(chain: Blockchain, path: str, query: dict) -> str:
    if path == "/" or path == "":
        return render_index(chain)
    if path == "/daimons":
        return render_daimons(chain)
    if path == "/genealogy":
        return render_genealogy(chain)
    if path == "/fossils":
        return render_fossils(chain)
    if path == "/block":
        try:
            i = int(query.get("i", ["-1"])[0])
        except ValueError:
            i = -1
        return render_block(chain, i)
    return _page("<h1>404</h1><p class='warn'>Nonexistent page.</p>")


# ══════════════════════════════════════════════════════════════════════════════
#  HTTP server
# ══════════════════════════════════════════════════════════════════════════════

def _make_handler(chain_provider):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            try:
                chain = chain_provider()
                page = route(chain, parsed.path, parse_qs(parsed.query))
                data = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            except Exception as exc:  # noqa: BLE001
                data = _page(f"<h1>Error</h1><p class='warn'>{_esc(exc)}</p>").encode("utf-8")
                self.send_response(500)
                self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):  # silence the default logging
            pass
    return Handler


def serve(chain_provider, host: str = "127.0.0.1", port: int = 8080) -> None:
    httpd = ThreadingHTTPServer((host, port), _make_handler(chain_provider))
    print(f"explorer at http://{host}:{port}  (Ctrl+C to stop)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nexplorer stopped.")
        httpd.shutdown()


def run(connect: str | None, demo: bool, host: str, port: int) -> None:
    if demo or not connect:
        chain = build_sample_chain()
        print(f"sample chain: {chain.height} blocks, "
              f"{len(chain.tip_state.daimons)} living, {len(chain.tip_state.fossils)} fossils")
        serve(lambda: chain, host, port)
    else:
        from .network.client import fetch_chain
        host_n, port_n = connect.rsplit(":", 1)

        def provider():
            blocks = asyncio.run(fetch_chain(host_n, int(port_n)))
            return Blockchain.from_blocks(blocks)
        serve(provider, host, port)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="daimon-explorer", description="DAIMON block explorer")
    ap.add_argument("--connect", default=None, help="host:port of a running node")
    ap.add_argument("--demo", action="store_true", help="use an in-memory sample chain")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    args = ap.parse_args(argv)
    run(args.connect, args.demo, args.host, args.port)


if __name__ == "__main__":
    main()
