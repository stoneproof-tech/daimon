# -*- coding: utf-8 -*-
"""Costanti e parametri di consenso di DAIMON.

Tutto in gocce (interi). 1 DMN = 1000 gocce. Mai float nel consenso.
Questi valori sono parte del consenso: cambiarli cambia la catena.
"""

DMN = 1000  # gocce per 1 DMN

# ── Proof-of-Work / emissione / entropia ────────────────────────────────────
POW_PREFIX     = "000"        # difficoltà: 3 zeri hex su sha256 dell'header
EMISSION       = 50 * DMN     # emissione costante al miner per blocco (no halving, no cap)
DEMURRAGE_NUM  = 98           # entropia: saldo ← saldo * 98 // 100 ogni blocco, su tutti i conti
DEMURRAGE_DEN  = 100

# ── Ciclo vitale dei daimon ─────────────────────────────────────────────────
SPAWN_FEE       = 5 * DMN     # bruciata alla nascita di un daimon
MIN_ENDOWMENT   = 20 * DMN    # dote minima alla nascita
THINK_COST      = 2 * DMN     # bruciato per ogni TASK
UPKEEP          = 1 * DMN     # metabolismo: bruciato ogni blocco per daimon vivo
DEATH_THRESHOLD = DMN // 2    # 0.5 DMN: sotto questa soglia il daimon muore (FOSSILE)

REPRO_BALANCE  = 50 * DMN     # riproduzione: saldo minimo
REPRO_TASKS    = 3            # riproduzione: task minimi svolti
CHILD_DOTE     = 25 * DMN     # dote trasferita al figlio
ROYALTY_MAX_BP = 5000         # royalty massima: 50% in basis points

# ── Genesi ──────────────────────────────────────────────────────────────────
GENESIS_PREV = "0" * 64
MANIFESTO = (
    "Πάντα ῥεῖ — nessuno si bagna due volte nello stesso fiume. "
    "Qui la materia inerte evapora e solo ciò che lavora persiste. "
    "Wörgl 1932 → Daimon 2026. Fair launch: nessun emittente, solo la sorgente."
)

# Equilibrio teorico della supply: S* = R / r = EMISSION / (1 - DEMURRAGE_NUM/DEMURRAGE_DEN).
S_STAR = (EMISSION * DEMURRAGE_DEN) // (DEMURRAGE_DEN - DEMURRAGE_NUM)  # = 2500 DMN in gocce

# Menti riconosciute dal protocollo.
KNOWN_MINDS = ("ORACLE_MATH", "NOTARY", "SCRIBE")


class ConsensusError(Exception):
    """Violazione delle regole di consenso: il blocco è invalido."""


def fmt(gocce: int) -> str:
    """Formatta gocce → DMN per la stampa (NON usato nel consenso)."""
    seg = "-" if gocce < 0 else ""
    g = abs(int(gocce))
    return f"{seg}{g // DMN}.{g % DMN:03d} DMN"
