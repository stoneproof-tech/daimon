# -*- coding: utf-8 -*-
"""DAIMON — blockchain L1 in puro Python con agenti AI come primitive native."""

from . import config
from .core import (
    Wallet, Blockchain, State, process_block,
    make_tx, make_genome, daimon_id, daimon_address, run_mind,
)

__version__ = "0.1.0"

__all__ = [
    "config", "Wallet", "Blockchain", "State", "process_block",
    "make_tx", "make_genome", "daimon_id", "daimon_address", "run_mind",
]
