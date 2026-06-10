# Contributing to DAIMON

Thanks for your interest in DAIMON. Contributions are welcome — bug fixes, tests,
docs, new minds, tooling, and explorer/UX improvements.

## Getting started

```bash
git clone https://github.com/stoneproof-tech/daimon
cd daimon
pip install -e ".[dev]"
pytest                  # 61 tests should pass
python -m daimon.demo   # the 7-act demo
```

On Windows, export `PYTHONUTF8=1` if the console raises `UnicodeEncodeError`.

## Ground rules: the consensus is sacred

DAIMON's whole point is a deterministic, replayable chain. Before touching anything
under `daimon/core/`, internalize these invariants — breaking them forks the chain:

1. **Block processing order is fixed**: entropy → transactions → emission →
   metabolism → reproduction → death. Never reorder.
2. **Integer math only.** The internal unit is *drops* (`1 DMN = 1000 drops`). No
   floats anywhere in consensus.
3. **`process_block` and `run_mind` must be pure and deterministic** — same input,
   same output, on every machine and Python version. No I/O, no wall-clock, no
   randomness, no locale-dependent formatting.
4. **No premine**, ever.
5. **Do not change consensus-visible strings.** The genesis manifesto and every
   string a mind can return (engraved into receipts) are protocol. Translating or
   "tidying" them is a hard fork. See `SECURITY.md`.

Anything *outside* consensus — CLI help, logs, the explorer UI, comments, docs — is
free to change and is English-first.

## Workflow

1. Branch from `main`.
2. Make focused, atomic commits with clear English messages.
3. Add or update tests. Bug fixes should come with a regression test.
4. Run the full suite: `pytest`. It must be green.
5. Open a pull request. CI runs `pytest` on Python 3.10 and 3.12; it must pass.

## Tests

- `test_consensus.py` — replay, tampering, entropy/`S*`, lifecycle, nonce/signatures, retargeting.
- `test_network.py` — P2P sync, gossip, mempool, longest-chain forks.
- `test_security.py` — protocol validation, fuzzing, flood→ban, resilience.
- `test_persistence.py` — store↔chain, restart equivalence, corruption recovery.
- `test_cli.py`, `test_explorer.py` — CLI flows and explorer rendering.

When adding a feature that crosses the wire or touches the store, add an integration
test that exercises the real path (a subprocess or two in-process nodes), not just a
unit test — several real bugs only show up there.

## Adding a new mind

A mind is a pure function in `daimon/core/minds.py` returning a deterministic string.
Register it in `KNOWN_MINDS` (`config.py`) and `run_mind`. Remember: once a mind ships
and a daimon uses it on a live chain, its output format is frozen forever.

## Style

Match the surrounding code: clear names, focused functions, comments where intent is
non-obvious. Keep `daimon/core/` dependency-light (only `ecdsa`).

By contributing you agree your contributions are licensed under the MIT License.
