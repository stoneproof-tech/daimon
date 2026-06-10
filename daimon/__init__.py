# -*- coding: utf-8 -*-
"""DAIMON — a pure-Python Layer-1 blockchain with AI agents as native primitives."""

from . import config
from .core import (
    Wallet, Blockchain, State, process_block,
    make_tx, make_genome, daimon_id, daimon_address, run_mind,
)

__version__ = "0.3.0"

__all__ = [
    "config", "Wallet", "Blockchain", "State", "process_block",
    "make_tx", "make_genome", "daimon_id", "daimon_address", "run_mind",
]
