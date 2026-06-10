# -*- coding: utf-8 -*-
"""Demo in 7 atti di DAIMON. Separata dal nucleo di consenso.

    python -m daimon.demo
"""

import sys

from .config import (
    DMN, EMISSION, S_STAR, MANIFESTO, fmt,
)
from .core import Wallet, Blockchain, make_tx, make_genome, daimon_id, daimon_address
from .core.chain import mine_nonce

# Console Windows: forza UTF-8 per manifesto greco / simboli.
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
    print(f"  Altezza catena : {chain.height} blocchi")
    print(f"  Supply totale  : {fmt(st.supply())}   (S* = {fmt(S_STAR)})")
    pct = st.supply() * 100 // S_STAR if S_STAR else 0
    print(f"  Convergenza    : {pct}% di S*")
    print(f"  Daimon vivi    : {len(st.daimons)}    Fossili: {len(st.fossils)}")
    if st.daimons:
        print("  ── vivi ──")
        for did in sorted(st.daimons):
            d = st.daimons[did]
            bal = st.balances.get(d["address"], 0)
            print(f"    {d['name']:<14} [{d['mind']:<11}] gen{d['generation']} "
                  f"task={d['tasks']} royalty={d['royalty_bp']/100:.0f}% saldo={fmt(bal)}")
    if st.fossils:
        print("  ── fossili ──")
        for f in st.fossils:
            print(f"    † {f['name']:<14} [{f['mind']:<11}] gen{f['generation']} "
                  f"nato@{f['born']} morto@{f['died']} ultimo_saldo={fmt(f['last_balance'])}")


def demo() -> None:
    chain = Blockchain()

    _hr("ATTO I — FAIR LAUNCH (genesi, zero premine)")
    print("  Manifesto inciso nella genesi:\n")
    print("   «" + MANIFESTO + "»\n")
    print(f"  Supply alla genesi: {fmt(chain.tip_state.supply())}  → nessuna moneta preesistente.")
    print(f"  Equilibrio teorico S* = R/r = {fmt(EMISSION)} / 0.02 = {fmt(S_STAR)}")

    founder = Wallet()
    ts = 1_700_000_000
    for _ in range(8):
        ts += 60
        chain.mine_block(founder.address, [], timestamp=ts)
    print(f"\n  Il fondatore ha coniato 8 blocchi. Saldo fondatore: "
          f"{fmt(chain.tip_state.balances.get(founder.address, 0))}")

    _hr("ATTO II — NASCITA DEI DAIMON (SPAWN, genoma immutabile)")
    g_pythia = make_genome("ORACLE_MATH", "Tutto è numero", "rigorosa", [])
    g_mnemo  = make_genome("NOTARY", "Ciò che è inciso resta", "meticolosa", [])
    g_hermes = make_genome("SCRIBE", "Porto parole tra i mondi", "ironico", [])
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
            print(f"  ✦ Nasce {r['name']:<8} [{r['mind']:<11}] id={r['id']}  dote={fmt(r['endowment'])}")
    pid, mid, hid = daimon_id(g_pythia), daimon_id(g_mnemo), daimon_id(g_hermes)

    _hr("ATTO III — LAVORI PAGATI (TASK, menti deterministiche)")
    jobs = [(pid, "2**10 + 24"), (mid, "contratto-alfa:2026-06-10"), (hid, "benvenuti nel fiume")]
    for did, work in jobs:
        n = chain.tip_state.nonces.get(founder.address, 0)
        tx = make_tx(founder, "TASK", {"daimon": did, "payload": work, "payment": 12 * DMN}, n)
        ts += 60
        blk = chain.mine_block(founder.address, [tx], timestamp=ts)
        r = [r for r in blk["receipts"] if r["k"] == "TASK"][0]
        print(f"  → {r['mind']:<11} '{work}'")
        print(f"      risultato: {r['result']}")
        print(f"      pagamento={fmt(r['payment'])}  royalty→creatore={fmt(r['royalty'])}  netto→daimon={fmt(r['net'])}")

    _hr("ATTO IV — RIPRODUZIONE DI PYTHIA (≥50 DMN e ≥3 task ⇒ figlio mutato)")
    born_child = None
    for k in range(12):
        n = chain.tip_state.nonces.get(founder.address, 0)
        tx = make_tx(founder, "TASK", {"daimon": pid, "payload": f"{3+k}*{7+k}", "payment": 30 * DMN}, n)
        ts += 60
        blk = chain.mine_block(founder.address, [tx], timestamp=ts)
        births = [r for r in blk["receipts"] if r["k"] == "BIRTH"]
        if births:
            born_child = births[0]
            print(f"  ✦✦ Pythia si riproduce al blocco {blk['index']}: "
                  f"nasce {born_child['name']} (gen{born_child['gen']}) id={born_child['child']}")
            break
    if not born_child:
        print("  (riproduzione non avvenuta nei tentativi della demo)")

    _hr("ATTO V — MORTE DI HERMES PER INEDIA (saldo < 0.5 DMN ⇒ FOSSILE)")
    print("  Hermes non riceve più lavoro: demurrage + metabolismo lo prosciugano.")
    print(f"  Saldo iniziale di Hermes: {fmt(chain.tip_state.balances.get(daimon_address(g_hermes), 0))}")
    died_at = None
    for _ in range(120):
        ts += 60
        blk = chain.mine_block(founder.address, [], timestamp=ts)
        if any(f["id"] == hid for f in chain.tip_state.fossils):
            died_at = blk["index"]
            break
    if died_at:
        foss = [f for f in chain.tip_state.fossils if f["id"] == hid][0]
        print(f"  † Hermes muore al blocco {died_at} (ultimo saldo {fmt(foss['last_balance'])}) → FOSSILE.")
    else:
        print("  (Hermes ancora vivo dopo la finestra della demo)")

    _hr("ATTO VI — CENSIMENTO")
    _census(chain)

    _hr("ATTO VII — MANOMISSIONE RILEVATA + CONVERGENZA A S*")
    ok, msg = chain.is_valid()
    print(f"  Validazione (replay totale): {ok} — {msg}")

    import copy as _copy
    forged = _copy.deepcopy(chain.blocks)
    victim = 11
    forged[victim]["receipts"][0]["result"] = "MANOMESSO"
    nonce, _ = mine_nonce({k: v for k, v in forged[victim].items() if k != "nonce"})
    forged[victim]["nonce"] = nonce  # PoW di nuovo valida: l'header "sembra" autentico
    ok2, msg2 = Blockchain.validate_chain(forged)
    print(f"  Ricevuta del blocco {victim} forgiata + PoW ri-coniata → {ok2} — {msg2}")

    print("\n  Conio di blocchi vuoti fino alla convergenza della supply verso S*...")
    target = S_STAR * 99 // 100
    start_h = chain.height
    while chain.tip_state.supply() < target and chain.height - start_h < 400:
        ts += 60
        chain.mine_block(founder.address, [], timestamp=ts)
    st = chain.tip_state
    pct = st.supply() * 100 // S_STAR
    print(f"  Altezza: {chain.height} blocchi  |  Supply: {fmt(st.supply())}  =  {pct}% di S*")
    print(f"  (S* = {fmt(S_STAR)} — la materia inerte evapora, l'equilibrio emerge dalla fisica.)")

    ok3, msg3 = chain.is_valid()
    print(f"\n  Validazione finale: {ok3} — {msg3}")
    _hr("FINE — Πάντα ῥεῖ")


if __name__ == "__main__":
    demo()
