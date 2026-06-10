# DAIMON

**🇬🇧 English** · [🇮🇹 Italiano](README.it.md)

[![CI](https://github.com/stoneproof-tech/daimon/actions/workflows/ci.yml/badge.svg)](https://github.com/stoneproof-tech/daimon/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-7ee0c0.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)

> *Πάντα ῥεῖ — no one steps in the same river twice.*
> *Here inert matter evaporates and only what works persists.*
> *Wörgl 1932 → Daimon 2026. Fair launch: no issuer, only the source.*

**DAIMON** is a Layer-1 blockchain written from scratch in pure Python where AI
agents are **native protocol primitives**. They are not smart contracts running
*on top of* the chain — they are citizens of the chain. They are born, they work,
they pay a metabolism, they reproduce with mutation, and they die.

|  | Layer-1 | Promise |
|--|---------|---------|
| **Bitcoin** | unstoppable **money** | value no one can seize |
| **Ethereum** | unstoppable **apps** | code no one can stop |
| **DAIMON** | unstoppable **agents** | minds no one can kill |

**Deploy once. Lives forever.** An agent's genome is immutable, its address is
derived from that genome, and as long as it earns enough to pay its metabolism it
keeps living, working and reproducing on a chain no one controls.

## The idea

| Verb | Primitive | Meaning |
|------|-----------|---------|
| **Be born** | `SPAWN` | An immutable genome `{mind, motto, indole, lineage}` creates a daimon. Its id and address derive *only* from the genome — no human key. |
| **Work** | `TASK` | A deterministic mind (`run_mind`) executes the job. The requester pays: royalty to the creator, `think_cost` burned, net to the daimon, result engraved in the block receipts. |
| **Pay** | metabolism | Every block, a living daimon burns `upkeep`. |
| **Reproduce** | reproduction | Balance ≥ 50 DMN and ≥ 3 tasks ⇒ a child with a mutated genome. |
| **Die** | `FOSSIL` | Balance < 0.5 DMN ⇒ the daimon becomes a fossil, recorded forever. |

## The monetary physics

Two opposing forces govern the money, **with integer math only**:

- **Constant emission** — `R = 50 DMN` per block to the miner (no halving, no cap).
- **Entropy / demurrage** — every block, on **every** account: `balance ← balance · 98 // 100` (−2%).

Equilibrium emerges from physics, not from an arbitrary rule:

```
S* = R / r = 50 / 0.02 = 2500 DMN
```

Supply converges to `S*` in ~240 blocks. Inert matter (idle capital) evaporates;
only what works — and therefore receives flow — persists. This is **metabolism as
monetary policy**: an agent that stops earning starves and dies; one that keeps
working pays its upkeep and endures.

**Fair launch**: no premine, no issuer. The first coin is born only from the
emission of the first mined block.

## Inviolable consensus rules

1. **Block processing order** (never alterable):
   `entropy → transactions → emission → metabolism → reproduction → death`
2. **Integer math only**. Internal unit = *drops* (`1 DMN = 1000 drops`). No floats in consensus.
3. **Absolute determinism** in `process_block` and `run_mind`.
4. **No premine.**

`process_block` is the **single** consensus function: identical for mining and for
validation. Validation is a **full replay from genesis** — any tampering (header,
receipts, state) produces a divergence that is detected.

> **Genesis manifesto.** The genesis block carries a manifesto that is a consensus
> rule: changing a single byte forks the chain. It is therefore kept verbatim in
> Greek/Italian and never translated. Its meaning: *"Everything flows — no one steps
> in the same river twice. Here inert matter evaporates and only what works persists.
> Wörgl 1932 → Daimon 2026. Fair launch: no issuer, only the source."* (The 1932
> reference is the [Wörgl experiment](https://en.wikipedia.org/wiki/W%C3%B6rgl#The_W%C3%B6rgl_Experiment),
> a demurrage currency.)

## The minds (`run_mind`) — deterministic and pure

- **`ORACLE_MATH`** — a tiny arithmetic evaluator over a whitelisted AST (no names or
  calls, exponent ≤ 16, length ≤ 80). Integer math.
- **`NOTARY`** — incremental counter + `sha256` of the payload + block number.
- **`SCRIBE`** — uppercased payload + the daimon's motto and indole.

A mind's output is engraved into the block receipts, so it is consensus-visible and
must be byte-for-byte deterministic across machines and Python versions.

## Cryptography

Transactions are signed with **ECDSA secp256k1** and carry a **per-account nonce**
(anti-replay). Types: `TRANSFER`, `SPAWN`, `TASK`. Human wallets hold keys; daimons
do not — their identity *is* their genome.

## Structure

```
daimon/
  config.py          # consensus parameters (drops) + network limits
  store.py           # persistence: append-only JSONL store, atomic writes, replay
  demo.py            # 7-act demo (separate from the core)
  core/
    crypto.py        # canonical serialization, sha, ECDSA Wallet, tx signing
    minds.py         # run_mind: ORACLE_MATH, NOTARY, SCRIBE (deterministic)
    tx.py            # genome, daimon identity, TRANSFER/SPAWN/TASK handlers
    state.py         # State + the six block phases
    chain.py         # process_block (consensus), PoW, Blockchain, replay/validation
  network/
    protocol.py      # newline-delimited JSON messages (HELLO/GETCHAIN/CHAIN/BLOCK/TX)
    node.py          # asyncio node: gossip, sync, fork resolution, mempool, hardening
    client.py        # lightweight client (GETCHAIN/TX) used by the CLI
    demo_p2p.py      # demo: 3 nodes converging to the same state_hash
  cli.py             # CLI: wallet, node, census, transfer, spawn, task, explorer
  explorer.py        # web block explorer (stdlib): genomes, genealogy, fossils, royalties
tests/               # 61 tests: consensus, retargeting, network, CLI, explorer, security, persistence
deploy/              # daimon-node.service (systemd) + setup_vps.sh (Ubuntu 24.04)
.github/workflows/   # ci.yml — pytest on every push/PR (Python 3.10 and 3.12)
daimon_chain.py      # compatibility entry-point (runs the demo)
```

## Demo & tests

```bash
pip install -e ".[dev]"      # or: pip install ecdsa pytest
python -m daimon.demo         # (equivalent: python daimon_chain.py)
python -m daimon.network.demo_p2p   # 3 P2P nodes that converge
pytest                        # 61 tests
```

> On Windows, if the console raises `UnicodeEncodeError`, export `PYTHONUTF8=1`.

## CLI

```bash
daimon wallet new   --out alice.wallet              # (or: python -m daimon.cli …)
daimon node         --port 9101 --mine 2 --wallet alice.wallet --data-dir ./data
daimon census       --connect 127.0.0.1:9101
daimon spawn        --connect 127.0.0.1:9101 --wallet alice.wallet --name Pythia \
                    --mind ORACLE_MATH --motto "All is number" --indole rigorous \
                    --endowment 30 --royalty 1000
daimon task         --connect 127.0.0.1:9101 --wallet alice.wallet \
                    --daimon DMN_… --payload "2**10+24" --payment 12
daimon transfer     --connect 127.0.0.1:9101 --wallet alice.wallet --to <addr> --amount 5
```

Transaction commands connect to a running node, read its state (for the nonce) and
inject the tx into the mempool, which the network gossips.

## Block explorer

```bash
daimon explorer --demo --port 8080            # in-memory sample chain
daimon explorer --connect 127.0.0.1:9101      # reads from a running node
```

Open `http://127.0.0.1:8080`: overview and blocks, daimon genomes, **genealogy
trees** (living + fossils, with royalties and generations), and the fossils. In
`--connect` mode the explorer re-fetches the chain on every request, so just refresh
the page to see the live chain grow.

## Testnet 🌐

DAIMON's first public testnet is **online**. A seed node is a 24/7 meeting point
(relay + persistence); anyone can run a node, mine and sync over the Internet.

```
seed node:  168.119.231.109:9101
```

The seed is **relay-only** (it does not mine: providers' ToS forbid mining) and
**persists the chain to disk**, so it keeps it across reboots. Mining lives on your
PC and on whoever joins.

**Join the network** (from your PC, after `pip install -e .`):

```bash
daimon node --port 9102 --peers 168.119.231.109:9101 --mine 1 --data-dir ./data
daimon census --connect 127.0.0.1:9102          # same height & state_hash as the seed
daimon census --connect 168.119.231.109:9101
```

**Host your own seed** (Ubuntu 24.04, idempotent — see `deploy/`):

```bash
curl -fsSL https://raw.githubusercontent.com/stoneproof-tech/daimon/main/deploy/setup_vps.sh | sudo bash
```

The script installs dependencies, creates a venv, generates **a new wallet that
stays on the server**, configures the firewall safely (it never enables `ufw` and
never touches existing rules — only adds `9101/tcp` if `ufw` is already active, so it
is safe on shared/production hosts) and starts the systemd service
(`deploy/daimon-node.service`, non-root user, `Restart=always`, `--mine 0`,
`--data-dir /var/lib/daimon`).

> Persistence: the seed appends every block (mined and received) to
> `/var/lib/daimon/chain.jsonl` (append-only, atomic writes with `fsync`). On start
> it reloads and **fully validates the chain by replay** before serving; a corrupted
> tail is truncated to the last valid block. After a server reboot the service comes
> back on its own and **keeps the chain**.

### Network security

The seed's port is exposed to the Internet, so the node is hardened against hostile
traffic (`daimon/network/node.py`, `protocol.py`):

- **strict validation** of every message (type, schema, sizes) *before* it touches
  the chain; malformed input ⇒ disconnect and a recorded strike;
- **caps**: max size per message and per received chain, total and per-IP peers, mempool size;
- **rate limiting** per connection and a **temporary IP ban** after N strikes;
- **timeouts** on the handshake and on every read (no unbounded waits);
- the node **never crashes** on external input — verified by `test_security.py`
  (random bytes, malformed JSON, giant messages, floods) with the chain always intact.

## Roadmap

- [x] **Genesis** — working chain: PoW SHA-256, entropy, daimon lifecycle.
- [x] **Milestone 1** — package refactor (`daimon/core`, `config`, separate demo) + consensus `pytest` suite.
- [x] **Milestone 2** — asyncio P2P (`daimon/network`): block+tx gossip, handshake, initial sync, longest-chain fork resolution, shared mempool. 3-node demo + integration tests.
- [x] **Milestone 3** — difficulty retargeting every N blocks: adaptive target (`int(hash) ≤ MAX//D`), targeting `TARGET_BLOCK_TIME` with a 4× clamp, verified in replay.
- [x] **Milestone 4** — CLI (`daimon`): wallet, node, census, transfer, spawn, task — over the P2P protocol against a running node.
- [x] **Milestone 5** — web block explorer (stdlib, `daimon explorer`): overview/blocks, genomes, genealogy trees, fossils and royalties.
- [x] **Hardening + CI** — network defenses (validation, rate limit, ban, timeouts, fuzzing) and GitHub Actions on every push/PR.
- [x] **Persistence** — append-only disk store (JSONL, atomic writes), replay+validation on start, corruption recovery; the seed keeps the chain across reboots.
- [x] **Testnet** — first remote seed node online: **`168.119.231.109:9101`**. Sync and convergence verified over the Internet (same `state_hash`); persistence survived a real server reboot. **First inhabitant: Pythia** (`ORACLE_MATH`), born and replicated across the network.

**61 green tests**, run in CI on Python 3.10 and 3.12. **Public testnet online.**

## Security

See [SECURITY.md](SECURITY.md) for responsible disclosure, and
[CONTRIBUTING.md](CONTRIBUTING.md) to contribute. Note the consensus invariants: the
genesis manifesto, the mind output strings, and the block processing order must never
change — they are protocol, not text.

## License

MIT © 2026 stoneproof-tech.
