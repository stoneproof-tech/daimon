# -*- coding: utf-8 -*-
"""
DAIMON — blockchain L1 in puro Python dove gli agenti AI sono primitive native.

Gli agenti (daimon) nascono (SPAWN, genoma immutabile), lavorano (TASK, menti
deterministiche), pagano metabolismo, si riproducono con mutazione e muoiono
(FOSSILE). Fisica monetaria: demurrage del 2%/blocco su TUTTI i conti + emissione
costante di 50 DMN/blocco  ⇒  la supply converge a  S* = R/r = 50/0.02 = 2500 DMN.
Fair launch: nessun premine, nessun emittente, solo la sorgente.

REGOLE INVIOLABILI
  * Ordine di processamento del blocco:
        entropia → transazioni → emissione → metabolismo → riproduzione → morte
  * Solo matematica intera (unità = "gocce", 1 DMN = 1000 gocce). Mai float nel consenso.
  * Determinismo assoluto in process_block e run_mind.
  * Nessun premine.

process_block è l'UNICA funzione di consenso: identica per mining e validazione.
La validazione è un replay totale dalla genesi: ogni manomissione viene rilevata.

File singolo, autoconsistente. Dipendenza esterna: `ecdsa` (secp256k1).
"""

import sys
import ast
import json
import copy
import time
import hashlib

from ecdsa import SigningKey, VerifyingKey, SECP256k1, BadSignatureError

# Console Windows: forza UTF-8 per manifesto greco / simboli (evita UnicodeEncodeError).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# ======================================================================================
#  CONFIG — tutto in gocce (interi). 1 DMN = 1000 gocce.
# ======================================================================================

DMN = 1000  # gocce per 1 DMN

POW_PREFIX     = "000"        # difficoltà: 3 zeri hex su sha256 dell'header
EMISSION       = 50 * DMN     # emissione costante al miner per blocco (no halving, no cap)
DEMURRAGE_NUM  = 98           # entropia: saldo ← saldo * 98 // 100 ogni blocco, su tutti i conti
DEMURRAGE_DEN  = 100

SPAWN_FEE      = 5 * DMN      # bruciata alla nascita di un daimon
MIN_ENDOWMENT  = 20 * DMN     # dote minima alla nascita
THINK_COST     = 2 * DMN      # bruciato per ogni TASK
UPKEEP         = 1 * DMN      # metabolismo: bruciato ogni blocco per daimon vivo
DEATH_THRESHOLD = DMN // 2    # 0.5 DMN: sotto questa soglia il daimon muore (FOSSILE)

REPRO_BALANCE  = 50 * DMN     # riproduzione: saldo minimo
REPRO_TASKS    = 3            # riproduzione: task minimi svolti
CHILD_DOTE     = 25 * DMN     # dote trasferita al figlio
ROYALTY_MAX_BP = 5000         # royalty massima: 50% in basis points

GENESIS_PREV   = "0" * 64
MANIFESTO = (
    "Πάντα ῥεῖ — nessuno si bagna due volte nello stesso fiume. "
    "Qui la materia inerte evapora e solo ciò che lavora persiste. "
    "Wörgl 1932 → Daimon 2026. Fair launch: nessun emittente, solo la sorgente."
)

S_STAR = (EMISSION * DEMURRAGE_DEN) // (DEMURRAGE_DEN - DEMURRAGE_NUM)  # = 2500 DMN in gocce


class ConsensusError(Exception):
    """Violazione delle regole di consenso: il blocco è invalido."""


# ======================================================================================
#  PRIMITIVE DETERMINISTICHE
# ======================================================================================

def canonical(obj) -> str:
    """Serializzazione canonica e stabile (per hashing e firme)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha(data: str) -> str:
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def fmt(gocce: int) -> str:
    """Formatta gocce → DMN per la stampa (NON usato nel consenso)."""
    seg = "-" if gocce < 0 else ""
    g = abs(int(gocce))
    return f"{seg}{g // DMN}.{g % DMN:03d} DMN"


# ======================================================================================
#  WALLET umano — chiave ECDSA secp256k1. (I daimon NON hanno chiavi umane.)
# ======================================================================================

class Wallet:
    def __init__(self, sk: SigningKey | None = None):
        self.sk = sk or SigningKey.generate(curve=SECP256k1)
        self.vk = self.sk.get_verifying_key()
        self.pubkey = self.vk.to_string().hex()
        self.address = "usr_" + sha("pk:" + self.pubkey)[:24]

    def sign(self, msg: str) -> str:
        return self.sk.sign(msg.encode("utf-8")).hex()


def tx_signing_payload(tx: dict) -> str:
    """Corpo firmabile della transazione (esclude la firma)."""
    body = {k: tx[k] for k in ("type", "from", "nonce", "payload", "pubkey")}
    return canonical(body)


def make_tx(wallet: Wallet, ttype: str, payload: dict, nonce: int) -> dict:
    tx = {
        "type": ttype,
        "from": wallet.address,
        "nonce": nonce,
        "payload": payload,
        "pubkey": wallet.pubkey,
    }
    tx["sig"] = wallet.sign(tx_signing_payload(tx))
    return tx


def verify_tx_signature(tx: dict) -> None:
    """Verifica firma ECDSA e coerenza indirizzo↔chiave. Solleva ConsensusError."""
    try:
        vk = VerifyingKey.from_string(bytes.fromhex(tx["pubkey"]), curve=SECP256k1)
        vk.verify(bytes.fromhex(tx["sig"]), tx_signing_payload(tx).encode("utf-8"))
    except (BadSignatureError, ValueError, KeyError) as exc:
        raise ConsensusError(f"firma non valida: {exc}")
    expected = "usr_" + sha("pk:" + tx["pubkey"])[:24]
    if tx["from"] != expected:
        raise ConsensusError("indirizzo mittente incoerente con la chiave pubblica")


# ======================================================================================
#  GENOMA & identità del daimon — derivata SOLO dal genoma (no chiave umana).
# ======================================================================================

def make_genome(mind: str, motto: str, indole: str, lineage: list[str]) -> dict:
    return {"mind": mind, "motto": motto, "indole": indole, "lineage": list(lineage)}


def daimon_id(genome: dict) -> str:
    return "DMN_" + sha(canonical(genome))[:16]


def daimon_address(genome: dict) -> str:
    return "dmn_" + sha("addr:" + canonical(genome))[:24]


# ======================================================================================
#  MENTI DETERMINISTICHE — run_mind: pura, nessun I/O, nessun float non controllato.
# ======================================================================================

_AST_BINOPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a // b if b != 0 else None,   # divisione INTERA (determinismo)
    ast.FloorDiv: lambda a, b: a // b if b != 0 else None,
    ast.Mod: lambda a, b: a % b if b != 0 else None,
}


def _eval_ast(node):
    """Mini-eval aritmetico via AST con whitelist. Niente nomi, niente chiamate."""
    if isinstance(node, ast.Expression):
        return _eval_ast(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            return node.value
        raise ValueError("solo costanti intere ammesse")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        v = _eval_ast(node.operand)
        return +v if isinstance(node.op, ast.UAdd) else -v
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if isinstance(node.op, ast.Pow):
            exp = _eval_ast(node.right)
            if abs(exp) > 16:
                raise ValueError("esponente troppo grande (max 16)")
            return _eval_ast(node.left) ** exp
        if op_type in _AST_BINOPS:
            res = _AST_BINOPS[op_type](_eval_ast(node.left), _eval_ast(node.right))
            if res is None:
                raise ValueError("divisione per zero")
            return res
    raise ValueError("operazione non consentita")


def mind_oracle_math(payload: str) -> str:
    if len(payload) > 80:
        return "ERR: espressione troppo lunga"
    try:
        tree = ast.parse(payload, mode="eval")
        return str(_eval_ast(tree))
    except Exception as exc:  # noqa: BLE001 — la mente non deve mai crashare il blocco
        return f"ERR: {exc}"


def mind_notary(payload: str, counter: int, block_index: int) -> str:
    return f"ATTO #{counter} · blk{block_index} · {sha(payload)[:16]}"


def mind_scribe(payload: str, motto: str, indole: str) -> str:
    return f"{payload.upper()} — {motto} [{indole}]"


def run_mind(daimon: dict, payload: str, block_index: int, notary_counter: int) -> str:
    """Esecuzione PURA e deterministica della mente del daimon."""
    mind = daimon["mind"]
    if mind == "ORACLE_MATH":
        return mind_oracle_math(payload)
    if mind == "NOTARY":
        return mind_notary(payload, notary_counter, block_index)
    if mind == "SCRIBE":
        return mind_scribe(payload, daimon["motto"], daimon["indole"])
    return "ERR: mente sconosciuta"


# ======================================================================================
#  STATO — interamente intero, serializzabile in modo deterministico.
# ======================================================================================

class State:
    def __init__(self):
        self.balances: dict[str, int] = {}   # address -> gocce
        self.nonces: dict[str, int] = {}      # address -> prossimo nonce atteso
        self.daimons: dict[str, dict] = {}    # id -> record vivo
        self.fossils: list[dict] = []         # daimon morti (in ordine di morte)
        self.notary: dict[str, int] = {}      # daimon_id -> contatore NOTARY

    def copy(self) -> "State":
        return copy.deepcopy(self)

    def credit(self, addr: str, amount: int) -> None:
        if amount == 0:
            return
        self.balances[addr] = self.balances.get(addr, 0) + amount

    def debit(self, addr: str, amount: int) -> None:
        bal = self.balances.get(addr, 0)
        if bal < amount:
            raise ConsensusError(f"saldo insufficiente su {addr}: {bal} < {amount}")
        self.balances[addr] = bal - amount

    def prune(self) -> None:
        """Rimuove i saldi azzerati (mantiene lo stato canonico minimale)."""
        self.balances = {a: b for a, b in self.balances.items() if b != 0}

    def supply(self) -> int:
        return sum(self.balances.values())

    def hash(self) -> str:
        snap = {
            "bal": sorted(self.balances.items()),
            "non": sorted(self.nonces.items()),
            "dmn": [self.daimons[k] for k in sorted(self.daimons)],
            "fos": self.fossils,
            "not": sorted(self.notary.items()),
        }
        return sha(canonical(snap))


# ======================================================================================
#  FASI DEL BLOCCO — ognuna pura sullo `state` (mutazione in-place su una copia).
#  L'ordine in cui sono chiamate da process_block è INVIOLABILE.
# ======================================================================================

def phase_entropy(state: State) -> None:
    """ENTROPIA (demurrage 2%): saldo ← saldo*98//100 su TUTTI i conti."""
    for addr in sorted(state.balances):
        state.balances[addr] = state.balances[addr] * DEMURRAGE_NUM // DEMURRAGE_DEN


def _apply_transfer(state: State, tx: dict, receipts: list) -> None:
    p = tx["payload"]
    to, amount = p["to"], int(p["amount"])
    if amount <= 0:
        raise ConsensusError("TRANSFER: importo non positivo")
    state.debit(tx["from"], amount)
    state.credit(to, amount)
    receipts.append({"k": "TRANSFER", "from": tx["from"], "to": to, "amount": amount})


def _apply_spawn(state: State, tx: dict, receipts: list, block_index: int) -> None:
    p = tx["payload"]
    genome = p["genome"]
    endowment = int(p["endowment"])
    royalty_bp = int(p["royalty_bp"])
    if endowment < MIN_ENDOWMENT:
        raise ConsensusError("SPAWN: dote sotto il minimo")
    if not (0 <= royalty_bp <= ROYALTY_MAX_BP):
        raise ConsensusError("SPAWN: royalty fuori range [0, 5000] bp")
    if not all(k in genome for k in ("mind", "motto", "indole", "lineage")):
        raise ConsensusError("SPAWN: genoma malformato")
    if genome["mind"] not in ("ORACLE_MATH", "NOTARY", "SCRIBE"):
        raise ConsensusError("SPAWN: mente sconosciuta")

    did = daimon_id(genome)
    if did in state.daimons or any(f["id"] == did for f in state.fossils):
        raise ConsensusError("SPAWN: genoma già esistente (id collisione)")

    addr = daimon_address(genome)
    # Il creatore paga: spawn_fee bruciata + dote trasferita al figlio.
    state.debit(tx["from"], SPAWN_FEE + endowment)
    state.credit(addr, endowment)  # spawn_fee NON ricreditata: bruciata.

    record = {
        "id": did,
        "name": p.get("name", did),
        "address": addr,
        "mind": genome["mind"],
        "motto": genome["motto"],
        "indole": genome["indole"],
        "lineage": list(genome["lineage"]),
        "creator": tx["from"],
        "royalty_bp": royalty_bp,
        "tasks": 0,
        "generation": len(genome["lineage"]),
        "born": block_index,
    }
    state.daimons[did] = record
    receipts.append({"k": "SPAWN", "id": did, "name": record["name"],
                     "mind": record["mind"], "addr": addr, "endowment": endowment})


def _apply_task(state: State, tx: dict, receipts: list, block_index: int) -> None:
    p = tx["payload"]
    did = p["daimon"]
    payment = int(p["payment"])
    work = str(p["payload"])
    if did not in state.daimons:
        raise ConsensusError("TASK: daimon inesistente o morto")
    daimon = state.daimons[did]
    royalty = payment * daimon["royalty_bp"] // 10000
    if payment < royalty + THINK_COST:
        raise ConsensusError("TASK: pagamento insufficiente a coprire royalty + think_cost")
    net = payment - royalty - THINK_COST

    state.debit(tx["from"], payment)         # il committente paga l'intero
    state.credit(daimon["creator"], royalty)  # royalty al creatore
    state.credit(daimon["address"], net)      # netto al daimon
    # THINK_COST bruciato (non ricreditato a nessuno).

    counter = state.notary.get(did, 0) + 1
    result = run_mind(daimon, work, block_index, counter)
    if daimon["mind"] == "NOTARY":
        state.notary[did] = counter
    daimon["tasks"] += 1

    receipts.append({"k": "TASK", "daimon": did, "mind": daimon["mind"],
                     "input": work, "result": result, "payment": payment,
                     "royalty": royalty, "net": net})


def phase_transactions(state: State, txs: list, receipts: list, block_index: int) -> None:
    """TRANSAZIONI firmate: verifica firma+nonce e applica in ordine."""
    handlers = {"TRANSFER": _apply_transfer, "SPAWN": _apply_spawn, "TASK": _apply_task}
    for tx in txs:
        verify_tx_signature(tx)
        expected_nonce = state.nonces.get(tx["from"], 0)
        if tx["nonce"] != expected_nonce:
            raise ConsensusError(
                f"nonce errato per {tx['from']}: atteso {expected_nonce}, ricevuto {tx['nonce']}")
        ttype = tx["type"]
        if ttype not in handlers:
            raise ConsensusError(f"tipo transazione sconosciuto: {ttype}")
        if ttype == "TRANSFER":
            _apply_transfer(state, tx, receipts)
        elif ttype == "SPAWN":
            _apply_spawn(state, tx, receipts, block_index)
        else:
            _apply_task(state, tx, receipts, block_index)
        state.nonces[tx["from"]] = expected_nonce + 1


def phase_emission(state: State, miner: str) -> None:
    """EMISSIONE: 50 DMN costanti al miner. È l'unica creazione di moneta."""
    state.credit(miner, EMISSION)


def phase_metabolism(state: State) -> None:
    """METABOLISMO: ogni daimon vivo brucia UPKEEP (1 DMN/blocco)."""
    for did in sorted(state.daimons):
        addr = state.daimons[did]["address"]
        bal = state.balances.get(addr, 0)
        pay = bal if bal < UPKEEP else UPKEEP
        if pay:
            state.balances[addr] = bal - pay  # bruciato


def _mutate_genome(parent: dict, parent_id: str) -> dict:
    """Mutazione DETERMINISTICA del genoma (nessun random)."""
    gen = parent["generation"] + 1
    motto = f"{parent['motto']} ·g{gen}·{parent_id[-4:]}"
    lineage = list(parent["lineage"]) + [parent_id]
    return make_genome(parent["mind"], motto, parent["indole"], lineage)


def phase_reproduction(state: State, receipts: list, block_index: int) -> None:
    """RIPRODUZIONE: saldo ≥ 50 DMN e ≥ 3 task ⇒ genera un figlio mutato."""
    for did in sorted(state.daimons):
        parent = state.daimons[did]
        addr = parent["address"]
        bal = state.balances.get(addr, 0)
        if bal < REPRO_BALANCE or parent["tasks"] < REPRO_TASKS:
            continue
        child_genome = _mutate_genome(parent, did)
        child_id = daimon_id(child_genome)
        if child_id in state.daimons or any(f["id"] == child_id for f in state.fossils):
            continue  # collisione improbabile: salta senza spendere
        # Il genitore paga: dote al figlio + spawn_fee bruciata.
        state.balances[addr] = bal - (CHILD_DOTE + SPAWN_FEE)
        parent["tasks"] = 0  # reset: serviranno nuovi task per riprodursi ancora
        child_addr = daimon_address(child_genome)
        state.credit(child_addr, CHILD_DOTE)
        child = {
            "id": child_id,
            "name": f"{parent['name']}·{parent['generation'] + 1}",
            "address": child_addr,
            "mind": child_genome["mind"],
            "motto": child_genome["motto"],
            "indole": child_genome["indole"],
            "lineage": child_genome["lineage"],
            "creator": parent["creator"],
            "royalty_bp": parent["royalty_bp"],
            "tasks": 0,
            "generation": parent["generation"] + 1,
            "born": block_index,
        }
        state.daimons[child_id] = child
        receipts.append({"k": "BIRTH", "parent": did, "child": child_id,
                         "name": child["name"], "gen": child["generation"]})


def phase_death(state: State, receipts: list, block_index: int) -> None:
    """MORTE: saldo < 0.5 DMN ⇒ il daimon diventa FOSSILE (rimosso, dust bruciato)."""
    for did in sorted(state.daimons):
        daimon = state.daimons[did]
        addr = daimon["address"]
        bal = state.balances.get(addr, 0)
        if bal < DEATH_THRESHOLD:
            state.balances.pop(addr, None)  # dust bruciato
            fossil = dict(daimon)
            fossil["died"] = block_index
            fossil["last_balance"] = bal
            state.fossils.append(fossil)
            del state.daimons[did]


# ======================================================================================
#  process_block — UNICA FUNZIONE DI CONSENSO. Usata identica da mining e validazione.
# ======================================================================================

def process_block(prev_state: State, index: int, miner: str, txs: list,
                  is_genesis: bool = False) -> tuple[State, list]:
    """
    Applica un blocco allo stato precedente e restituisce (nuovo_stato, ricevute).
    Ordine INVIOLABILE: entropia → tx → emissione → metabolismo → riproduzione → morte.
    Funzione PURA: stesso input ⇒ stesso output. Nessun I/O, nessun float.
    """
    state = prev_state.copy()
    receipts: list = []

    if is_genesis:
        # Genesi: nessuna moneta creata (fair launch, zero premine), solo il manifesto.
        return state, receipts

    phase_entropy(state)                               # 1. ENTROPIA
    phase_transactions(state, txs, receipts, index)    # 2. TRANSAZIONI
    phase_emission(state, miner)                       # 3. EMISSIONE
    phase_metabolism(state)                            # 4. METABOLISMO
    phase_reproduction(state, receipts, index)         # 5. RIPRODUZIONE
    phase_death(state, receipts, index)                # 6. MORTE
    state.prune()
    return state, receipts


# ======================================================================================
#  BLOCCO & CATENA — PoW SHA-256, prev_hash, state_hash, replay totale.
# ======================================================================================

def header_pow_hash(header: dict) -> str:
    return sha(canonical(header))


def mine_nonce(header_wo_nonce: dict) -> tuple[int, str]:
    """Proof-of-Work: trova nonce tale che l'hash dell'header inizi con POW_PREFIX."""
    nonce = 0
    while True:
        header = dict(header_wo_nonce)
        header["nonce"] = nonce
        h = header_pow_hash(header)
        if h.startswith(POW_PREFIX):
            return nonce, h
        nonce += 1


class Blockchain:
    def __init__(self):
        self.blocks: list[dict] = []
        self.states: list[State] = []  # states[i] = stato DOPO il blocco i
        self._build_genesis()

    # --- costruzione ---

    def _build_genesis(self) -> None:
        state, receipts = process_block(State(), 0, "GENESIS", [], is_genesis=True)
        hdr = {
            "index": 0,
            "timestamp": 0,
            "prev_hash": GENESIS_PREV,
            "miner": "GENESIS",
            "txs": [],
            "receipts": receipts,
            "state_hash": state.hash(),
            "manifesto": MANIFESTO,
        }
        nonce, _ = mine_nonce(hdr)
        hdr["nonce"] = nonce
        self.blocks.append(hdr)
        self.states.append(state)

    @property
    def tip_state(self) -> State:
        return self.states[-1]

    @property
    def height(self) -> int:
        return self.blocks[-1]["index"]

    def mine_block(self, miner_addr: str, txs: list | None = None,
                   timestamp: int | None = None) -> dict:
        """Conia un nuovo blocco sopra il tip. Usa process_block (stessa logica del consenso)."""
        txs = txs or []
        index = self.height + 1
        prev = self.blocks[-1]
        new_state, receipts = process_block(self.tip_state, index, miner_addr, txs)
        hdr = {
            "index": index,
            "timestamp": int(timestamp if timestamp is not None else time.time()),
            "prev_hash": header_pow_hash(prev),
            "miner": miner_addr,
            "txs": txs,
            "receipts": receipts,
            "state_hash": new_state.hash(),
        }
        nonce, _ = mine_nonce(hdr)
        hdr["nonce"] = nonce
        self.blocks.append(hdr)
        self.states.append(new_state)
        return hdr

    # --- validazione: replay totale dalla genesi ---

    @staticmethod
    def validate_chain(blocks: list[dict]) -> tuple[bool, str]:
        """Replay totale: ricostruisce lo stato e verifica PoW, linkage, ricevute, state_hash."""
        if not blocks or blocks[0]["index"] != 0:
            return False, "manca il blocco di genesi"
        # Genesi
        g = blocks[0]
        if g.get("manifesto") != MANIFESTO:
            return False, "manifesto di genesi manomesso"
        if g["prev_hash"] != GENESIS_PREV:
            return False, "prev_hash di genesi non nullo"
        if not header_pow_hash(g).startswith(POW_PREFIX):
            return False, "PoW di genesi non valida"
        gstate, greceipts = process_block(State(), 0, "GENESIS", [], is_genesis=True)
        if g["state_hash"] != gstate.hash():
            return False, "state_hash di genesi non corrisponde"
        if canonical(g["receipts"]) != canonical(greceipts):
            return False, "ricevute di genesi manomesse"

        state = gstate
        for i in range(1, len(blocks)):
            blk = blocks[i]
            prev = blocks[i - 1]
            if blk["index"] != i:
                return False, f"indice fuori sequenza al blocco {i}"
            if blk["prev_hash"] != header_pow_hash(prev):
                return False, f"prev_hash spezzato al blocco {i} (catena manomessa)"
            if not header_pow_hash(blk).startswith(POW_PREFIX):
                return False, f"PoW non valida al blocco {i}"
            try:
                new_state, receipts = process_block(state, i, blk["miner"], blk["txs"])
            except ConsensusError as exc:
                return False, f"consenso violato al blocco {i}: {exc}"
            if canonical(receipts) != canonical(blk["receipts"]):
                return False, f"ricevute manomesse al blocco {i}"
            if new_state.hash() != blk["state_hash"]:
                return False, f"state_hash manomesso al blocco {i} (stato divergente dal replay)"
            state = new_state
        return True, "catena integra"

    def is_valid(self) -> tuple[bool, str]:
        return self.validate_chain(self.blocks)


# ======================================================================================
#  DEMO IN 7 ATTI
# ======================================================================================

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

    # Il fondatore conia alcuni blocchi vuoti: la moneta nasce SOLO dall'emissione (fair launch).
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
    pid = daimon_id(g_pythia)
    mid = daimon_id(g_mnemo)
    hid = daimon_id(g_hermes)

    _hr("ATTO III — LAVORI PAGATI (TASK, menti deterministiche)")
    jobs = [
        (pid, "2**10 + 24"),
        (mid, "contratto-alfa:2026-06-10"),
        (hid, "benvenuti nel fiume"),
    ]
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
    # Alimentiamo Pythia finché saldo ≥ 50 DMN e tasks ≥ 3, poi la riproduzione scatta nel blocco.
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
    hermes_balance0 = chain.tip_state.balances.get(daimon_address(g_hermes), 0)
    print(f"  Saldo iniziale di Hermes: {fmt(hermes_balance0)}")
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

    # Manomissione di un blocco passato: alteriamo una ricevuta storica e RI-CONIAMO
    # la sua PoW, così che l'header torni valido. Solo il replay totale può smascherarla:
    # ricalcolando lo stato dalla genesi, la ricevuta forgiata non corrisponde più.
    import copy as _copy
    forged = _copy.deepcopy(chain.blocks)
    victim = 11  # un blocco con un TASK
    forged[victim]["receipts"][0]["result"] = "MANOMESSO"
    nonce, _ = mine_nonce({k: v for k, v in forged[victim].items() if k != "nonce"})
    forged[victim]["nonce"] = nonce  # PoW di nuovo valida: l'header "sembra" autentico
    ok2, msg2 = Blockchain.validate_chain(forged)
    print(f"  Ricevuta del blocco {victim} forgiata + PoW ri-coniata → {ok2} — {msg2}")

    # Convergenza: continuiamo a coniare blocchi vuoti finché supply ≥ 99% di S* (o cap blocchi).
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
