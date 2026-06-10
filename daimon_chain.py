# -*- coding: utf-8 -*-
"""Entry-point di compatibilità: la logica vive ora nel package `daimon/`.

    python daimon_chain.py        # esegue la demo in 7 atti
    python -m daimon.demo         # equivalente

Il nucleo di consenso è in daimon/core/ (crypto, minds, tx, state, chain),
i parametri in daimon/config.py.
"""

from daimon.demo import demo

if __name__ == "__main__":
    demo()
