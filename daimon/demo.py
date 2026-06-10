# -*- coding: utf-8 -*-
"""DAIMON 7-act demo. Separate from the consensus core.

    python -m daimon.demo
"""

import sys

from .config import (
    DMN, EMISSION, S_STAR, MANIFESTO, fmt,
)
from .core import Wallet, Blockchain, make_tx, make_genome, daimon_id, daimon_address
from .core.chain import mine_nonce

# Windows console: force UTF-8 for the Greek manifesto / symbols.
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


def _hr(title: str) -> None:
    print("\n" + "═" * 78)
    print(f"  {title}")
    print("═" * 78)


def _census(chain: Blockchain) -> None:
    st = chain.tip_state
    print(f"  Chain height  : {chain.height} blocks")
    print(f"  Tip difficulty: {chain.blocks[-1]['difficulty']} (retargeting every N blocks)")
    print(f"  Total supply  : {fmt(st.supply())}   (S* = {fmt(S_STAR)})")
    pct = st.supply() * 100 // S_STAR if S_STAR else 0
    print(f"  Convergence   : {pct}% of S*")
    print(f"  Living daimons: {len(st.daimons)}    Fossils: {len(st.fossils)}")
    if st.daimons:
        print("  ── living ──")
        for did in sorted(st.daimons):
            d = st.daimons[did]
            bal = st.balances.get(d["address"], 0)
            print(f"    {d['name']:<14} [{d['mind']:<11}] gen{d['generation']} "
                  f"tasks={d['tasks']} royalty={d['royalty_bp']/100:.0f}% balance={fmt(bal)}")
    if st.fossils:
        print("  ── fossils ──")
        for f in st.fossils:
            print(f"    † {f['name']:<14} [{f['mind']:<11}] gen{f['generation']} "
                  f"born@{f['born']} died@{f['died']} last_balance={fmt(f['last_balance'])}")


def demo() -> None:
    chain = Blockchain()

    _hr("ACT I — FAIR LAUNCH (genesis, zero premine)")
    print("  Manifesto engraved in genesis:\n")
    print("   «" + MANIFESTO + "»\n")
    print(f"  Supply at genesis: {fmt(chain.tip_state.supply())}  → no pre-existing coin.")
    print(f"  Theoretical equilibrium S* = R/r = {fmt(EMISSION)} / 0.02 = {fmt(S_STAR)}")

    founder = Wallet()
    ts = 1_700_000_000
    for _ in range(8):
        ts += 60
        chain.mine_block(founder.address, [], timestamp=ts)
    print(f"\n  The founder mined 8 blocks. Founder balance: "
          f"{fmt(chain.tip_state.balances.get(founder.address, 0))}")

    _hr("ACT II — BIRTH OF THE DAIMONS (SPAWN, immutable genome)")
    g_pythia = make_genome("ORACLE_MATH", "All is number", "rigorous", [])
    g_mnemo  = make_genome("NOTARY", "What is engraved remains", "meticulous", [])
    g_hermes = make_genome("SCRIBE", "I carry words between worlds", "ironic", [])
    n = chain.tip_state.nonces.get(founder.address, 0)
    spawn_txs = [
        make_tx(founder, "SPAWN", {"name": "Pythia", "genome": g_pythia,
                                   "endowment": 30 * DMN, "royalty_bp": 1000}, n),
        make_tx(founder, "SPAWN", {"name": "Mnemo", "genome": g_mnemo,
                                   "endowment": 30 * DMN, "royalty_bp": 1500}, n + 1),
        make_tx(founder, "SPAWN", {"name": "Hermes", "genome": g_hermes,
                                   "endowment": 20 * DMN, "royalty_bp": 1000}, n + 2),
    ]
    ts += 60
    blk = chain.mine_block(founder.address, spawn_txs, timestamp=ts)
    for r in blk["receipts"]:
        if r["k"] == "SPAWN":
            print(f"  ✦ Born {r['name']:<8} [{r['mind']:<11}] id={r['id']}  endowment={fmt(r['endowment'])}")
    pid, mid, hid = daimon_id(g_pythia), daimon_id(g_mnemo), daimon_id(g_hermes)

    _hr("ACT III — PAID WORK (TASK, deterministic minds)")
    jobs = [(pid, "2**10 + 24"), (mid, "contract-alpha:2026-06-10"), (hid, "welcome to the river")]
    for did, work in jobs:
        n = chain.tip_state.nonces.get(founder.address, 0)
        tx = make_tx(founder, "TASK", {"daimon": did, "payload": work, "payment": 12 * DMN}, n)
        ts += 60
        blk = chain.mine_block(founder.address, [tx], timestamp=ts)
        r = [r for r in blk["receipts"] if r["k"] == "TASK"][0]
        print(f"  → {r['mind']:<11} '{work}'")
        print(f"      result: {r['result']}")
        print(f"      payment={fmt(r['payment'])}  royalty→creator={fmt(r['royalty'])}  net→daimon={fmt(r['net'])}")

    _hr("ACT IV — REPRODUCTION OF PYTHIA (≥50 DMN and ≥3 tasks ⇒ mutated child)")
    born_child = None
    for k in range(12):
        n = chain.tip_state.nonces.get(founder.address, 0)
        tx = make_tx(founder, "TASK", {"daimon": pid, "payload": f"{3+k}*{7+k}", "payment": 30 * DMN}, n)
        ts += 60
        blk = chain.mine_block(founder.address, [tx], timestamp=ts)
        births = [r for r in blk["receipts"] if r["k"] == "BIRTH"]
        if births:
            born_child = births[0]
            print(f"  ✦✦ Pythia reproduces at block {blk['index']}: "
                  f"born {born_child['name']} (gen{born_child['gen']}) id={born_child['child']}")
            break
    if not born_child:
        print("  (reproduction did not happen within the demo's attempts)")

    _hr("ACT V — DEATH OF HERMES BY STARVATION (balance < 0.5 DMN ⇒ FOSSIL)")
    print("  Hermes receives no more work: demurrage + metabolism drain it.")
    print(f"  Hermes' initial balance: {fmt(chain.tip_state.balances.get(daimon_address(g_hermes), 0))}")
    died_at = None
    for _ in range(120):
        ts += 60
        blk = chain.mine_block(founder.address, [], timestamp=ts)
        if any(f["id"] == hid for f in chain.tip_state.fossils):
            died_at = blk["index"]
            break
    if died_at:
        foss = [f for f in chain.tip_state.fossils if f["id"] == hid][0]
        print(f"  † Hermes dies at block {died_at} (last balance {fmt(foss['last_balance'])}) → FOSSIL.")
    else:
        print("  (Hermes still alive after the demo window)")

    _hr("ACT VI — CENSUS")
    _census(chain)

    _hr("ACT VII — TAMPERING DETECTED + CONVERGENCE TO S*")
    ok, msg = chain.is_valid()
    print(f"  Validation (full replay): {ok} — {msg}")

    import copy as _copy
    forged = _copy.deepcopy(chain.blocks)
    victim = 11
    forged[victim]["receipts"][0]["result"] = "TAMPERED"
    nonce, _ = mine_nonce({k: v for k, v in forged[victim].items() if k != "nonce"})
    forged[victim]["nonce"] = nonce  # PoW valid again: the header "looks" authentic
    ok2, msg2 = Blockchain.validate_chain(forged)
    print(f"  Block {victim} receipt forged + PoW re-mined → {ok2} — {msg2}")

    print("\n  Mining empty blocks until the supply converges to S*...")
    target = S_STAR * 99 // 100
    start_h = chain.height
    while chain.tip_state.supply() < target and chain.height - start_h < 400:
        ts += 60
        chain.mine_block(founder.address, [], timestamp=ts)
    st = chain.tip_state
    pct = st.supply() * 100 // S_STAR
    print(f"  Height: {chain.height} blocks  |  Supply: {fmt(st.supply())}  =  {pct}% of S*")
    print(f"  (S* = {fmt(S_STAR)} — inert matter evaporates, equilibrium emerges from physics.)")

    ok3, msg3 = chain.is_valid()
    print(f"\n  Final validation: {ok3} — {msg3}")
    _hr("END — Πάντα ῥεῖ")


if __name__ == "__main__":
    demo()
