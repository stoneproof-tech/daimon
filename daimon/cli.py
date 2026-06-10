# -*- coding: utf-8 -*-
"""DAIMON CLI.

    daimon wallet new   --out alice.wallet
    daimon wallet show  --wallet alice.wallet
    daimon node         --port 9101 --peers 127.0.0.1:9102 --mine 2 --wallet alice.wallet
    daimon census       --connect 127.0.0.1:9101
    daimon transfer     --connect 127.0.0.1:9101 --wallet alice.wallet --to <addr> --amount 5
    daimon spawn        --connect 127.0.0.1:9101 --wallet alice.wallet --name Pythia \
                        --mind ORACLE_MATH --motto "All is number" --indole rigorous \
                        --endowment 30 --royalty 1000
    daimon task         --connect 127.0.0.1:9101 --wallet alice.wallet \
                        --daimon DMN_xxxx --payload "2**10+24" --payment 12

Commands that send transactions or read state connect to a running node and use the
P2P protocol (GETCHAIN for state, TX to inject).
"""

import sys
import asyncio
import argparse

from .config import DMN, fmt, S_STAR, KNOWN_MINDS
from .core import Wallet, Blockchain, make_tx, make_genome, daimon_id
from .network import Node
from .network.client import fetch_chain, push_tx

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ── utilities ────────────────────────────────────────────────────────────────

def parse_connect(s: str):
    host, port = s.rsplit(":", 1)
    return host, int(port)


def parse_peers(s: str):
    if not s:
        return []
    return [parse_connect(x.strip()) for x in s.split(",") if x.strip()]


def dmn_to_drops(s: str) -> int:
    """Convert an amount in DMN (e.g. '5' or '5.250') into integer drops."""
    s = str(s).strip()
    if "." in s:
        intpart, frac = s.split(".", 1)
        frac = (frac + "000")[:3]
        return (int(intpart or "0")) * DMN + int(frac or "0")
    return int(s) * DMN


async def _build_chain(connect: str) -> Blockchain:
    host, port = parse_connect(connect)
    blocks = await fetch_chain(host, port)
    if not blocks:
        raise SystemExit(f"no chain received from {connect} (node running?)")
    return Blockchain.from_blocks(blocks)


def _nonce_of(chain: Blockchain, addr: str) -> int:
    return chain.tip_state.nonces.get(addr, 0)


# ── commands ─────────────────────────────────────────────────────────────────

def cmd_wallet_new(args):
    w = Wallet()
    w.save(args.out)
    print(f"wallet created → {args.out}")
    print(f"  address: {w.address}")
    print("  (keep this file safe: it holds the private key; it is in .gitignore)")


def cmd_wallet_show(args):
    w = Wallet.load(args.wallet)
    print(f"address: {w.address}")


def cmd_census(args):
    chain = asyncio.run(_build_chain(args.connect))
    st = chain.tip_state
    print(f"── CENSUS @ {args.connect} ──")
    print(f"  height       : {chain.height}")
    print(f"  tip hash     : {chain.tip_hash}")
    print(f"  state_hash   : {st.hash()}")
    print(f"  difficulty   : {chain.blocks[-1]['difficulty']}")
    print(f"  supply       : {fmt(st.supply())}  ({st.supply()*100//S_STAR if S_STAR else 0}% of S*)")
    print(f"  living daimon: {len(st.daimons)}   fossils: {len(st.fossils)}")
    for did in sorted(st.daimons):
        d = st.daimons[did]
        bal = st.balances.get(d["address"], 0)
        print(f"    {d['name']:<14} [{d['mind']:<11}] gen{d['generation']} "
              f"tasks={d['tasks']} roy={d['royalty_bp']/100:.0f}% balance={fmt(bal)}  {did}")
    for f in st.fossils:
        print(f"    † {f['name']:<14} [{f['mind']:<11}] died@{f['died']}  {f['id']}")


def _submit(connect: str, wallet: Wallet, ttype: str, payload: dict):
    chain = asyncio.run(_build_chain(connect))
    nonce = _nonce_of(chain, wallet.address)
    tx = make_tx(wallet, ttype, payload, nonce)
    host, port = parse_connect(connect)
    asyncio.run(push_tx(host, port, tx))
    print(f"{ttype} injected (nonce {nonce}, sig {tx['sig'][:16]}…) → mempool of {connect}")
    print("  it will be included in the next block mined by the network.")


def cmd_transfer(args):
    w = Wallet.load(args.wallet)
    _submit(args.connect, w, "TRANSFER",
            {"to": args.to, "amount": dmn_to_drops(args.amount)})


def cmd_spawn(args):
    w = Wallet.load(args.wallet)
    if args.mind not in KNOWN_MINDS:
        raise SystemExit(f"unknown mind: {args.mind} (allowed: {', '.join(KNOWN_MINDS)})")
    genome = make_genome(args.mind, args.motto, args.indole, [])
    print(f"  expected daimon id: {daimon_id(genome)}")
    _submit(args.connect, w, "SPAWN",
            {"name": args.name, "genome": genome,
             "endowment": dmn_to_drops(args.endowment), "royalty_bp": int(args.royalty)})


def cmd_task(args):
    w = Wallet.load(args.wallet)
    _submit(args.connect, w, "TASK",
            {"daimon": args.daimon, "payload": args.payload, "payment": dmn_to_drops(args.payment)})


def cmd_explorer(args):
    from .explorer import run as explorer_run
    explorer_run(args.connect, args.demo, args.host, args.port)


def cmd_node(args):
    async def run():
        wallet = Wallet.load(args.wallet) if args.wallet else Wallet()
        node = Node(args.name, args.host, args.port, parse_peers(args.peers),
                    wallet, data_dir=args.data_dir)
        await node.start()
        print(f"node '{node.name}' listening on {node.host}:{node.port}")
        print(f"  miner address: {node.address}")
        if args.data_dir:
            print(f"  data persisted in: {args.data_dir}  (tip @ {node.chain.height})")
        if args.peers:
            print(f"  peers: {args.peers}")
        if args.mine:
            print(f"  mining every {args.mine}s")

            async def miner():
                while True:
                    await asyncio.sleep(args.mine)
                    try:
                        await node.mine_once()
                    except Exception as exc:  # noqa: BLE001
                        print(f"  [mining] error: {exc}")
            # IMPORTANT: keep a reference to the task, otherwise the GC may collect it
            # and mining never starts (asyncio.create_task footgun).
            node._tasks.append(asyncio.create_task(miner()))
        else:
            print("  mining OFF (relay only)")
        await asyncio.Event().wait()  # runs until interrupted

    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nnode stopped.")


# ── parser ───────────────────────────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="daimon", description="DAIMON blockchain CLI")
    sub = ap.add_subparsers(dest="cmd", required=True)

    w = sub.add_parser("wallet", help="wallet management").add_subparsers(dest="wcmd", required=True)
    wn = w.add_parser("new", help="create a new wallet")
    wn.add_argument("--out", default="daimon.wallet")
    wn.set_defaults(func=cmd_wallet_new)
    ws = w.add_parser("show", help="show a wallet's address")
    ws.add_argument("--wallet", required=True)
    ws.set_defaults(func=cmd_wallet_show)

    nd = sub.add_parser("node", help="start a node")
    nd.add_argument("--name", default="node")
    nd.add_argument("--host", default="127.0.0.1")
    nd.add_argument("--port", type=int, default=9101)
    nd.add_argument("--peers", default="", help="comma-separated list of host:port")
    nd.add_argument("--mine", type=float, default=0, help="mine a block every N seconds (0=off, relay only)")
    nd.add_argument("--wallet", default=None, help="miner wallet (ephemeral otherwise)")
    nd.add_argument("--data-dir", default=None, help="chain persistence directory (JSONL)")
    nd.set_defaults(func=cmd_node)

    cs = sub.add_parser("census", help="census of daimons from the node")
    cs.add_argument("--connect", required=True)
    cs.set_defaults(func=cmd_census)

    tr = sub.add_parser("transfer", help="send DMN to an address")
    tr.add_argument("--connect", required=True)
    tr.add_argument("--wallet", required=True)
    tr.add_argument("--to", required=True)
    tr.add_argument("--amount", required=True, help="amount in DMN (e.g. 5 or 5.250)")
    tr.set_defaults(func=cmd_transfer)

    sp = sub.add_parser("spawn", help="spawn a daimon")
    sp.add_argument("--connect", required=True)
    sp.add_argument("--wallet", required=True)
    sp.add_argument("--name", required=True)
    sp.add_argument("--mind", required=True, help=f"one of: {', '.join(KNOWN_MINDS)}")
    sp.add_argument("--motto", required=True)
    sp.add_argument("--indole", required=True)
    sp.add_argument("--endowment", default="30", help="endowment in DMN (min 20)")
    sp.add_argument("--royalty", type=int, default=1000, help="royalty in basis points (≤5000)")
    sp.set_defaults(func=cmd_spawn)

    tk = sub.add_parser("task", help="assign a task to a daimon")
    tk.add_argument("--connect", required=True)
    tk.add_argument("--wallet", required=True)
    tk.add_argument("--daimon", required=True, help="daimon id (DMN_…)")
    tk.add_argument("--payload", required=True)
    tk.add_argument("--payment", default="12", help="payment in DMN")
    tk.set_defaults(func=cmd_task)

    ex = sub.add_parser("explorer", help="start the web block explorer")
    ex.add_argument("--connect", default=None, help="host:port of a node (otherwise --demo)")
    ex.add_argument("--demo", action="store_true", help="in-memory sample chain")
    ex.add_argument("--host", default="127.0.0.1")
    ex.add_argument("--port", type=int, default=8080)
    ex.set_defaults(func=cmd_explorer)

    return ap


def main(argv=None):
    ap = build_parser()
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
