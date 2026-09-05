"""The contract every source implements.

`read()` must be safe to call from scratch with no prior state and must
yield the full available history every time -- callers rely on that for
"replay from empty reproduces the same numbers, no hidden state."
"""
from __future__ import annotations

from typing import Iterator, Protocol


class EpisodeSource(Protocol):
    def read(self) -> Iterator[dict]:
        ...
