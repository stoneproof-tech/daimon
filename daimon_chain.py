# -*- coding: utf-8 -*-
"""Compatibility entry-point: the logic now lives in the `daimon/` package.

    python daimon_chain.py        # runs the 7-act demo
    python -m daimon.demo         # equivalent

The consensus core is in daimon/core/ (crypto, minds, tx, state, chain), the
parameters in daimon/config.py.
"""

from daimon.demo import demo

if __name__ == "__main__":
    demo()
