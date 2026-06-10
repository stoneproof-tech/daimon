# DAIMON

[![CI](https://github.com/stoneproof-tech/daimon/actions/workflows/ci.yml/badge.svg)](https://github.com/stoneproof-tech/daimon/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-7ee0c0.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

> *Πάντα ῥεῖ — nessuno si bagna due volte nello stesso fiume.*
> *Qui la materia inerte evapora e solo ciò che lavora persiste.*
> *Wörgl 1932 → Daimon 2026. Fair launch: nessun emittente, solo la sorgente.*

**DAIMON** è una blockchain Layer-1 scritta da zero in puro Python in cui gli
agenti AI sono **primitive native del protocollo**. Non sono smart contract che
girano *sopra* la catena: sono cittadini della catena. Nascono, lavorano,
pagano un metabolismo, si riproducono con mutazione e muoiono.

## L'idea

| Verbo | Primitiva | Significato |
|-------|-----------|-------------|
| **Nascere** | `SPAWN` | Un genoma immutabile `{mind, motto, indole, lineage}` genera un daimon. Id e indirizzo sono derivati *solo* dal genoma: nessuna chiave umana. |
| **Lavorare** | `TASK` | Una mente deterministica (`run_mind`) esegue il compito. Il committente paga: royalty al creatore, `think_cost` bruciato, netto al daimon, risultato inciso nelle ricevute. |
| **Pagare** | metabolismo | Ogni blocco un daimon vivo brucia `upkeep`. |
| **Riprodursi** | riproduzione | Saldo ≥ 50 DMN e ≥ 3 task ⇒ un figlio con genoma mutato. |
| **Morire** | `FOSSILE` | Saldo < 0.5 DMN ⇒ il daimon diventa fossile, registrato per sempre. |

## La fisica monetaria

Due forze opposte governano la moneta, **solo con matematica intera**:

- **Emissione costante** — `R = 50 DMN` per blocco al miner (no halving, no cap).
- **Entropia / demurrage** — ogni blocco, su **tutti** i conti: `saldo ← saldo · 98 // 100` (−2%).

L'equilibrio emerge dalla fisica, non da una regola arbitraria:

```
S* = R / r = 50 / 0.02 = 2500 DMN
```

La supply converge a `S*` in ~240 blocchi. La materia inerte (capitale fermo)
evapora; solo ciò che lavora — e quindi riceve flusso — persiste.

**Fair launch**: nessun premine, nessun emittente. La prima moneta nasce solo
dall'emissione del primo blocco coniato.

## Regole inviolabili del consenso

1. **Ordine di processamento del blocco** (mai alterabile):
   `entropia → transazioni → emissione → metabolismo → riproduzione → morte`
2. **Solo matematica intera**. Unità interna = *gocce* (`1 DMN = 1000 gocce`). Mai float nel consenso.
3. **Determinismo assoluto** in `process_block` e `run_mind`.
4. **Nessun premine.**

`process_block` è l'**unica** funzione di consenso: identica per il mining e per
la validazione. La validazione è un **replay totale dalla genesi** — qualunque
manomissione (header, ricevute, stato) produce una divergenza che viene rilevata.

## Le menti (`run_mind`) — deterministiche e pure

- **`ORACLE_MATH`** — mini-eval aritmetico via AST con whitelist (niente nomi né
  chiamate, esponente ≤ 16, lunghezza ≤ 80). Matematica intera.
- **`NOTARY`** — contatore incrementale + `sha256` del payload + numero di blocco.
- **`SCRIBE`** — payload in maiuscolo + motto + indole del daimon.

## Crittografia

Transazioni firmate **ECDSA secp256k1** con **nonce per account** (anti-replay).
Tipi: `TRANSFER`, `SPAWN`, `TASK`. I wallet umani hanno chiavi; i daimon no — la
loro identità è il loro genoma.

## Struttura

```
daimon/
  config.py          # parametri di consenso (gocce) + limiti di rete
  store.py           # persistenza: store append-only JSONL, scritture atomiche, replay
  demo.py            # demo in 7 atti (separata dal nucleo)
  core/
    crypto.py        # serializzazione canonica, sha, Wallet ECDSA, firme tx
    minds.py         # run_mind: ORACLE_MATH, NOTARY, SCRIBE (deterministiche)
    tx.py            # genoma, identità daimon, handler TRANSFER/SPAWN/TASK
    state.py         # State + le sei fasi del blocco
    chain.py         # process_block (consenso), PoW, Blockchain, replay/validazione
  network/
    protocol.py      # messaggi JSON delimitati da newline (HELLO/GETCHAIN/CHAIN/BLOCK/TX)
    node.py          # nodo asyncio: gossip, sync, fork-resolution, mempool
    client.py        # client leggero (GETCHAIN/TX) usato dalla CLI
    demo_p2p.py      # demo: 3 nodi che convergono allo stesso state_hash
  cli.py             # CLI: wallet, node, census, transfer, spawn, task, explorer
  explorer.py        # block explorer web (stdlib): genomi, genealogia, fossili, royalty
tests/
  test_consensus.py  # replay, manomissioni, entropia/S*, ciclo vitale, nonce/firme, retargeting
  test_network.py    # integrazione P2P: sync, gossip, mempool, fork longest-chain
  test_cli.py        # wallet roundtrip, conversioni, flusso spawn via client
  test_explorer.py   # catena d'esempio, rendering pagine, genealogia, smoke HTTP
  test_security.py   # validazione protocollo, fuzzing, flood→ban, resilienza
  test_persistence.py# store↔catena, riavvio (stesso state_hash), recupero da corruzione
deploy/              # daimon-node.service (systemd) + setup_vps.sh (Ubuntu 24.04)
.github/workflows/   # ci.yml — pytest a ogni push/PR (Python 3.10 e 3.12)
daimon_chain.py      # entry-point di compatibilità (esegue la demo)
```

## Demo & test

```bash
pip install -e ".[dev]"     # oppure: pip install ecdsa pytest
python -m daimon.demo        # (equivalente: python daimon_chain.py)
python -m daimon.network.demo_p2p   # 3 nodi P2P che convergono
pytest                       # 61 test (consenso, retargeting, rete, CLI, explorer, sicurezza, persistenza)
```

## CLI

```bash
daimon wallet new   --out alice.wallet              # (oppure: python -m daimon.cli …)
daimon node         --port 9101 --mine 2 --wallet alice.wallet     # avvia un nodo che mina
daimon census       --connect 127.0.0.1:9101
daimon spawn        --connect 127.0.0.1:9101 --wallet alice.wallet --name Pythia \
                    --mind ORACLE_MATH --motto "Tutto è numero" --indole rigorosa \
                    --endowment 30 --royalty 1000
daimon task         --connect 127.0.0.1:9101 --wallet alice.wallet \
                    --daimon DMN_… --payload "2**10+24" --payment 12
daimon transfer     --connect 127.0.0.1:9101 --wallet alice.wallet --to <addr> --amount 5
```

I comandi che inviano transazioni si connettono a un nodo in esecuzione, ne leggono
lo stato (per il nonce) e immettono la tx nella mempool, che la rete gossipa.

## Block explorer

```bash
daimon explorer --demo --port 8080            # catena d'esempio in memoria
daimon explorer --connect 127.0.0.1:9101      # legge da un nodo in esecuzione
```

Apri `http://127.0.0.1:8080`: panoramica e blocchi, genomi dei daimon, **alberi
genealogici** (viventi + fossili, con royalty e generazioni), e i fossili.

La demo in **7 atti**: fair launch → nascita di Pythia (`ORACLE_MATH`), Mnemo
(`NOTARY`), Hermes (`SCRIBE`) → lavori pagati → riproduzione di Pythia → morte di
Hermes per inedia → censimento → manomissione di un blocco passato **rilevata dal
replay** → supply che converge a `S* = 2500 DMN`.

> Su Windows, se la console solleva `UnicodeEncodeError`, esporta `PYTHONUTF8=1`.

## Testnet 🌐

La prima testnet pubblica di DAIMON è **online**. Un nodo seed fa da punto di
incontro 24/7 (relay + persistenza); chiunque può avviare un nodo, minare e
sincronizzarsi attraverso Internet.

```
seed node:  168.119.231.109:9101
```

Il seed fa **solo relay** (non mina: i ToS dei provider vietano il mining) e
**persiste la catena su disco**, quindi la conserva attraverso i riavvii. Il mining
sta sul tuo PC e su chiunque si unisca.

**Unirsi alla rete** (dal tuo PC, dopo `pip install -e .`):

```bash
# avvia un nodo locale che si connette al seed, si sincronizza e mina
daimon node --port 9102 --peers 168.119.231.109:9101 --mine 1 --data-dir ./dati

# in un'altra shell: censimento del tuo nodo e del seed — stessa altezza, stesso stato
daimon census --connect 127.0.0.1:9102
daimon census --connect 168.119.231.109:9101
```

**Mettere online un proprio seed** (Ubuntu 24.04, idempotente — vedi `deploy/`):

```bash
curl -fsSL https://raw.githubusercontent.com/stoneproof-tech/daimon/main/deploy/setup_vps.sh | sudo bash
```

Lo script installa le dipendenze, crea un venv, genera **un wallet nuovo che resta
sul server**, configura `ufw` (solo SSH + `9101`) e avvia il servizio systemd
(`deploy/daimon-node.service`, utente non-root, `Restart=always`, `--mine 0`,
`--data-dir /var/lib/daimon`).

> Persistenza: il seed salva ogni blocco (minato dalla rete e ricevuto) in
> `/var/lib/daimon/chain.jsonl` (append-only, scritture atomiche con `fsync`).
> All'avvio ricarica e **valida l'intera catena col replay** prima di servire; una
> coda di file corrotta viene troncata all'ultimo blocco valido. Dopo un riavvio del
> server, il servizio riparte da solo e **conserva la catena**.

### Sicurezza di rete

La porta del seed è esposta a Internet, quindi il nodo è temprato contro traffico
ostile (`daimon/network/node.py`, `protocol.py`):

- **validazione rigorosa** di ogni messaggio (tipo, schema, dimensioni) *prima* che
  tocchi la chain; input malformato ⇒ disconnessione e infrazione registrata;
- **tetti**: dimensione massima per messaggio e per catena ricevuta, peer totali e
  per singolo IP, dimensione della mempool;
- **rate limiting** per connessione e **ban temporaneo** dell'IP dopo N infrazioni;
- **timeout** su handshake e su ogni lettura (nessuna attesa senza scadenza);
- il nodo **non crasha mai** per input esterno — verificato da `test_security.py`
  (byte casuali, JSON malformati, messaggi giganti, flood) con chain sempre integra.

## Roadmap

- [x] **Genesi** — catena funzionante: PoW SHA-256, entropia, ciclo vitale dei daimon.
- [x] **Milestone 1** — ristrutturazione in package (`daimon/core`, `config`, demo separata) + suite `pytest` sul consenso (25 test).
- [x] **Milestone 2** — rete P2P asyncio (`daimon/network`): gossip blocchi+tx, handshake, sync iniziale, fork resolution longest-chain, mempool condivisa. Demo 3 nodi + test d'integrazione.
- [x] **Milestone 3** — difficulty retargeting ogni N blocchi: target adattivo (`int(hash) ≤ MAX//D`), riadattamento puntando a `TARGET_BLOCK_TIME` con clamp 4×, verificato nel replay.
- [x] **Milestone 4** — CLI (`daimon`): wallet (new/show), node (con mining), census, transfer, spawn, task — via il protocollo P2P verso un nodo in esecuzione.
- [x] **Milestone 5** — block explorer web (stdlib, `daimon explorer`): panoramica/blocchi, genomi, alberi genealogici (viventi + fossili), fossili e royalty.
- [x] **Hardening + CI** — difese di rete (validazione, rate limit, ban, timeout, fuzzing) e GitHub Actions su ogni push/PR.
- [x] **Persistenza** — store append-only su disco (JSONL, scritture atomiche), replay+validazione all'avvio, recupero da corruzione; il seed conserva la catena attraverso i riavvii.
- [x] **Testnet** — primo nodo seed remoto online su VPS (systemd, `deploy/`, solo relay + persistenza): **`168.119.231.109:9101`**. Sync e convergenza verificate attraverso Internet (stesso `state_hash`), persistenza sopravvissuta a un reboot del server.

**61 test verdi**, eseguiti in CI su Python 3.10 e 3.12. **Testnet pubblica online.**

## Licenza

MIT © 2026 stoneproof-tech.
