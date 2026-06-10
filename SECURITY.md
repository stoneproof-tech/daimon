# Security Policy

DAIMON is an experimental Layer-1 blockchain. The public testnet runs with no
economic value, but we take the integrity of the protocol and the safety of node
operators seriously.

## Supported versions

The `main` branch and the latest tagged release receive security fixes. Older tags
do not.

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through one of these channels:

- **GitHub Security Advisories** — preferred: open a draft advisory at
  <https://github.com/stoneproof-tech/daimon/security/advisories/new>.
- If that is unavailable, open a regular issue titled "security contact request"
  **without any details** and a maintainer will arrange a private channel.

Please include:

- a description of the issue and its impact;
- steps to reproduce (a minimal proof of concept is ideal);
- affected version/commit;
- any suggested remediation.

## What to expect

- Acknowledgement within **5 business days**.
- An assessment and, if confirmed, a fix on a coordinated timeline.
- Credit in the release notes if you wish (opt-in).

## Scope

In scope:

- consensus violations (a node accepting an invalid block, replay/validation
  bypass, non-determinism in `process_block` / `run_mind`);
- remote crashes or resource exhaustion of a node from network input
  (the node must never crash or run unbounded on hostile traffic);
- signature/nonce bypass, double-spend, or minting without emission;
- the deployment scripts (`deploy/`) doing anything outside the DAIMON footprint.

Out of scope:

- the value of testnet DMN (there is none);
- denial of service that requires privileged network position beyond the documented
  rate-limit/ban behavior;
- third-party services running alongside a node on shared hosts.

## Consensus invariants (never change these)

Some strings and rules are **protocol, not text**. Changing them forks the chain and
is treated as a breaking consensus change, never a translation or cleanup:

- the **genesis manifesto** (`config.MANIFESTO`);
- the **mind output strings** (`daimon/core/minds.py`: `NOTARY`, `SCRIBE`,
  `ORACLE_MATH` results and their error messages) — they are engraved in receipts;
- the **block processing order** (entropy → tx → emission → metabolism → reproduction → death);
- integer-only math and the absence of any premine.
