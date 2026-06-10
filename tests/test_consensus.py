# -*- coding: utf-8 -*-
"""Suite di consenso di DAIMON.

Copre: determinismo & replay, manomissioni (header / ricevute / stato),
entropia ed equilibrio S*, ciclo vitale completo (nascita→lavoro→riproduzione→morte),
nonce e firme ECDSA.

I test NON dipendono da random nelle firme: ogni catena è costruita ex novo.
Il PoW (3 zeri hex) è veloce (~4096 tentativi medi per blocco).
"""

import copy
import pytest

from daimon.config import (
    DMN, EMISSION, S_STAR, MANIFESTO, ConsensusError,
    MIN_ENDOWMENT, ROYALTY_MAX_BP, DEMURRAGE_NUM, DEMURRAGE_DEN, UPKEEP,
)
from daimon.core import (
    Wallet, Blockchain, State, process_block,
    make_tx, make_genome, daimon_id, daimon_address,
)
from daimon.core.chain import header_pow_hash, mine_nonce, POW_PREFIX
from daimon.core.minds import run_mind, mind_oracle_math


# ── Helper ──────────────────────────────────────────────────────────────────

def fresh_chain_with_founder(blocks=8):
    """Catena nuova + un fondatore che conia `blocks` blocchi (fair launch)."""
    chain = Blockchain()
    founder = Wallet()
    ts = 1_700_000_000
    for _ in range(blocks):
        ts += 60
        chain.mine_block(founder.address, [], timestamp=ts)
    return chain, founder, ts


def spawn(chain, founder, name, mind, motto, indole, endow=30 * DMN, royalty=1000, ts=0):
    g = make_genome(mind, motto, indole, [])
    n = chain.tip_state.nonces.get(founder.address, 0)
    tx = make_tx(founder, "SPAWN", {"name": name, "genome": g,
                                    "endowment": endow, "royalty_bp": royalty}, n)
    chain.mine_block(founder.address, [tx], timestamp=ts + 60)
    return g, daimon_id(g)


# ── Genesi & fair launch ─────────────────────────────────────────────────────

def test_genesi_zero_premine():
    chain = Blockchain()
    assert chain.tip_state.supply() == 0
    assert chain.blocks[0]["manifesto"] == MANIFESTO
    assert chain.blocks[0]["prev_hash"] == "0" * 64
    assert header_pow_hash(chain.blocks[0]).startswith(POW_PREFIX)


def test_emissione_e_pow():
    chain, founder, _ = fresh_chain_with_founder(1)
    # Un solo blocco coniato: il miner ha esattamente EMISSION (al netto dell'entropia,
    # che su saldo iniziale 0 non toglie nulla).
    assert chain.tip_state.balances[founder.address] == EMISSION
    for blk in chain.blocks:
        assert header_pow_hash(blk).startswith(POW_PREFIX)


# ── Determinismo & replay ────────────────────────────────────────────────────

def test_process_block_deterministico():
    chain, founder, ts = fresh_chain_with_founder(3)
    prev = chain.tip_state
    n = prev.nonces.get(founder.address, 0)
    tx = make_tx(founder, "TRANSFER", {"to": "usr_dest", "amount": 1 * DMN}, n)
    s1, r1 = process_block(prev, 99, founder.address, [tx])
    s2, r2 = process_block(prev, 99, founder.address, [tx])
    assert s1.hash() == s2.hash()
    assert r1 == r2
    # Lo stato sorgente non è stato mutato (process_block è puro).
    assert prev.hash() == chain.tip_state.hash()


def test_replay_catena_integra():
    chain, founder, ts = fresh_chain_with_founder(6)
    spawn(chain, founder, "Pythia", "ORACLE_MATH", "Tutto è numero", "rigorosa", ts=ts)
    ok, msg = chain.is_valid()
    assert ok, msg
    assert msg == "catena integra"


def test_replay_ricostruisce_stesso_state_hash():
    chain, founder, ts = fresh_chain_with_founder(5)
    # Replay indipendente con process_block deve riprodurre ogni state_hash.
    state = process_block(State(), 0, "GENESIS", [], is_genesis=True)[0]
    for i in range(1, len(chain.blocks)):
        blk = chain.blocks[i]
        state, receipts = process_block(state, i, blk["miner"], blk["txs"])
        assert state.hash() == blk["state_hash"]


# ── Manomissioni ─────────────────────────────────────────────────────────────

def test_manomissione_header_prevhash():
    chain, founder, ts = fresh_chain_with_founder(5)
    forged = copy.deepcopy(chain.blocks)
    forged[3]["prev_hash"] = "f" * 64
    ok, msg = Blockchain.validate_chain(forged)
    assert not ok and "prev_hash" in msg


def test_manomissione_ricevuta_rilevata_dal_replay():
    chain, founder, ts = fresh_chain_with_founder(5)
    g, pid = spawn(chain, founder, "Pythia", "ORACLE_MATH", "n", "r", ts=ts)
    n = chain.tip_state.nonces.get(founder.address, 0)
    tx = make_tx(founder, "TASK", {"daimon": pid, "payload": "2+2", "payment": 12 * DMN}, n)
    chain.mine_block(founder.address, [tx], timestamp=ts + 200)
    victim = len(chain.blocks) - 1
    forged = copy.deepcopy(chain.blocks)
    # Forgia il risultato e RI-CONIA la PoW: solo il replay può smascherarla.
    forged[victim]["receipts"][-1]["result"] = "MANOMESSO"
    forged[victim]["nonce"], _ = mine_nonce({k: v for k, v in forged[victim].items() if k != "nonce"})
    ok, msg = Blockchain.validate_chain(forged)
    assert not ok and "ricevute manomesse" in msg


def test_manomissione_stato_rilevata():
    chain, founder, ts = fresh_chain_with_founder(5)
    forged = copy.deepcopy(chain.blocks)
    # Alteriamo solo lo state_hash memorizzato: il replay calcola un valore diverso.
    forged[4]["state_hash"] = "deadbeef"
    forged[4]["nonce"], _ = mine_nonce({k: v for k, v in forged[4].items() if k != "nonce"})
    ok, msg = Blockchain.validate_chain(forged)
    assert not ok and "state_hash" in msg


def test_manomissione_manifesto():
    chain, founder, ts = fresh_chain_with_founder(2)
    forged = copy.deepcopy(chain.blocks)
    forged[0]["manifesto"] = "premine occulto"
    ok, msg = Blockchain.validate_chain(forged)
    assert not ok and "manifesto" in msg


def test_manomissione_importo_tx_rompe_la_firma():
    chain, founder, ts = fresh_chain_with_founder(5)
    n = chain.tip_state.nonces.get(founder.address, 0)
    tx = make_tx(founder, "TRANSFER", {"to": "usr_x", "amount": 1 * DMN}, n)
    chain.mine_block(founder.address, [tx], timestamp=ts + 200)
    victim = len(chain.blocks) - 1
    forged = copy.deepcopy(chain.blocks)
    forged[victim]["txs"][0]["payload"]["amount"] = 999 * DMN  # firma non più valida
    forged[victim]["nonce"], _ = mine_nonce({k: v for k, v in forged[victim].items() if k != "nonce"})
    ok, msg = Blockchain.validate_chain(forged)
    assert not ok and ("firma" in msg or "consenso" in msg)


# ── Entropia ed equilibrio S* ────────────────────────────────────────────────

def test_entropia_demurrage_intero():
    chain, founder, _ = fresh_chain_with_founder(2)
    bal = chain.tip_state.balances[founder.address]
    # Conia un blocco vuoto a un altro miner: l'entropia colpisce il saldo del fondatore.
    other = Wallet()
    chain.mine_block(other.address, [], timestamp=1_700_001_000)
    atteso = bal * DEMURRAGE_NUM // DEMURRAGE_DEN
    assert chain.tip_state.balances[founder.address] == atteso


def test_convergenza_supply_a_s_star():
    chain = Blockchain()
    miner = Wallet()
    ts = 1_700_000_000
    for _ in range(300):
        ts += 60
        chain.mine_block(miner.address, [], timestamp=ts)
    supply = chain.tip_state.supply()
    # Convergenza entro l'1% di S* (la fisica: emissione 50, demurrage 2% ⇒ S*=2500).
    assert abs(supply - S_STAR) <= S_STAR // 100
    assert S_STAR == 2500 * DMN


# ── Ciclo vitale completo ────────────────────────────────────────────────────

def test_nascita_spawn():
    chain, founder, ts = fresh_chain_with_founder(5)
    g, pid = spawn(chain, founder, "Pythia", "ORACLE_MATH", "n", "rigorosa", ts=ts)
    d = chain.tip_state.daimons[pid]
    assert d["name"] == "Pythia" and d["mind"] == "ORACLE_MATH"
    # Nel blocco di nascita il daimon paga già il metabolismo (upkeep), che segue
    # le transazioni nell'ordine inviolabile: 30 DMN di dote − 1 DMN di upkeep.
    assert chain.tip_state.balances[daimon_address(g)] == 30 * DMN - UPKEEP
    assert pid.startswith("DMN_")


def test_spawn_dote_sotto_minimo_rifiutato():
    chain, founder, ts = fresh_chain_with_founder(5)
    g = make_genome("SCRIBE", "m", "i", [])
    n = chain.tip_state.nonces.get(founder.address, 0)
    tx = make_tx(founder, "SPAWN", {"name": "X", "genome": g,
                                    "endowment": MIN_ENDOWMENT - 1, "royalty_bp": 100}, n)
    with pytest.raises(ConsensusError):
        process_block(chain.tip_state, chain.height + 1, founder.address, [tx])


def test_spawn_royalty_fuori_range_rifiutato():
    chain, founder, ts = fresh_chain_with_founder(5)
    g = make_genome("SCRIBE", "m", "i", [])
    n = chain.tip_state.nonces.get(founder.address, 0)
    tx = make_tx(founder, "SPAWN", {"name": "X", "genome": g,
                                    "endowment": MIN_ENDOWMENT, "royalty_bp": ROYALTY_MAX_BP + 1}, n)
    with pytest.raises(ConsensusError):
        process_block(chain.tip_state, chain.height + 1, founder.address, [tx])


def test_task_paga_royalty_thinkcost_e_netto():
    chain, founder, ts = fresh_chain_with_founder(6)
    g, pid = spawn(chain, founder, "P", "ORACLE_MATH", "n", "r", royalty=1000, ts=ts)
    creator_before = chain.tip_state.balances[founder.address]
    n = chain.tip_state.nonces.get(founder.address, 0)
    tx = make_tx(founder, "TASK", {"daimon": pid, "payload": "6*7", "payment": 20 * DMN}, n)
    blk = chain.mine_block(founder.address, [tx], timestamp=ts + 200)
    r = [r for r in blk["receipts"] if r["k"] == "TASK"][0]
    assert r["result"] == "42"
    # royalty 10% di 20 DMN = 2 DMN, think_cost 2 DMN, netto = 16 DMN.
    assert r["royalty"] == 2 * DMN
    assert r["net"] == 20 * DMN - 2 * DMN - 2 * DMN
    assert chain.tip_state.daimons[pid]["tasks"] == 1


def test_riproduzione_con_mutazione():
    chain, founder, ts = fresh_chain_with_founder(8)
    g, pid = spawn(chain, founder, "Pythia", "ORACLE_MATH", "Tutto è numero", "r", ts=ts)
    child = None
    for k in range(15):
        n = chain.tip_state.nonces.get(founder.address, 0)
        tx = make_tx(founder, "TASK", {"daimon": pid, "payload": f"{2+k}*9", "payment": 30 * DMN}, n)
        blk = chain.mine_block(founder.address, [tx], timestamp=ts + 300 + k * 60)
        births = [r for r in blk["receipts"] if r["k"] == "BIRTH"]
        if births:
            child = births[0]
            break
    assert child is not None, "la riproduzione non è avvenuta"
    cid = child["child"]
    assert cid in chain.tip_state.daimons
    assert chain.tip_state.daimons[cid]["generation"] == 1
    # Genoma mutato ⇒ id diverso dal genitore, lineage che contiene il padre.
    assert cid != pid
    assert pid in chain.tip_state.daimons[cid]["lineage"]


def test_morte_per_inedia_diventa_fossile():
    chain, founder, ts = fresh_chain_with_founder(6)
    g, hid = spawn(chain, founder, "Hermes", "SCRIBE", "m", "i", endow=MIN_ENDOWMENT, ts=ts)
    other = Wallet()  # conia altrove così Hermes non riceve nulla
    died = False
    for i in range(200):
        chain.mine_block(other.address, [], timestamp=ts + 1000 + i * 60)
        if any(f["id"] == hid for f in chain.tip_state.fossils):
            died = True
            break
    assert died, "Hermes non è morto per inedia"
    assert hid not in chain.tip_state.daimons
    foss = [f for f in chain.tip_state.fossils if f["id"] == hid][0]
    assert foss["last_balance"] < DMN // 2


# ── Nonce & firme ────────────────────────────────────────────────────────────

def test_nonce_errato_rifiutato():
    chain, founder, ts = fresh_chain_with_founder(5)
    n = chain.tip_state.nonces.get(founder.address, 0)
    tx = make_tx(founder, "TRANSFER", {"to": "usr_y", "amount": 1 * DMN}, n + 5)  # salto
    with pytest.raises(ConsensusError):
        process_block(chain.tip_state, chain.height + 1, founder.address, [tx])


def test_nonce_incrementa_e_anti_replay():
    chain, founder, ts = fresh_chain_with_founder(6)
    n = chain.tip_state.nonces.get(founder.address, 0)
    tx = make_tx(founder, "TRANSFER", {"to": "usr_z", "amount": 1 * DMN}, n)
    chain.mine_block(founder.address, [tx], timestamp=ts + 200)
    assert chain.tip_state.nonces[founder.address] == n + 1
    # Riproporre la STESSA tx (stesso nonce) deve fallire.
    with pytest.raises(ConsensusError):
        process_block(chain.tip_state, chain.height + 1, founder.address, [tx])


def test_firma_falsificata_rifiutata():
    chain, founder, ts = fresh_chain_with_founder(5)
    attacker = Wallet()
    n = chain.tip_state.nonces.get(founder.address, 0)
    tx = make_tx(founder, "TRANSFER", {"to": "usr_w", "amount": 1 * DMN}, n)
    tx["pubkey"] = attacker.pubkey  # chiave non corrispondente alla firma/indirizzo
    with pytest.raises(ConsensusError):
        process_block(chain.tip_state, chain.height + 1, founder.address, [tx])


def test_saldo_insufficiente_rifiutato():
    chain, founder, ts = fresh_chain_with_founder(2)
    n = chain.tip_state.nonces.get(founder.address, 0)
    enorme = 10_000 * DMN
    tx = make_tx(founder, "TRANSFER", {"to": "usr_q", "amount": enorme}, n)
    with pytest.raises(ConsensusError):
        process_block(chain.tip_state, chain.height + 1, founder.address, [tx])


# ── Menti deterministiche ────────────────────────────────────────────────────

def test_oracle_math_whitelist():
    assert mind_oracle_math("2**10 + 24") == "1048"
    assert mind_oracle_math("100 // 7") == "14"
    assert mind_oracle_math("(3+4)*5") == "35"
    # Niente nomi/chiamate/attributi.
    assert mind_oracle_math("__import__('os')").startswith("ERR")
    assert mind_oracle_math("abs(-5)").startswith("ERR")
    # Esponente troppo grande.
    assert mind_oracle_math("2**99").startswith("ERR")
    # Troppo lunga.
    assert mind_oracle_math("1+" * 50 + "1").startswith("ERR")


def test_notary_deterministico():
    d = {"mind": "NOTARY", "motto": "m", "indole": "i"}
    a = run_mind(d, "payload", 7, 3)
    b = run_mind(d, "payload", 7, 3)
    assert a == b and a.startswith("ATTO #3 · blk7")


def test_scribe_usa_motto_e_indole():
    d = {"mind": "SCRIBE", "motto": "Porto parole", "indole": "ironico"}
    out = run_mind(d, "ciao", 1, 0)
    assert out == "CIAO — Porto parole [ironico]"
