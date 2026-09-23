"""Request-local usage counters for comparing complete model workflows."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ModelUsage:
    """Accumulate every returned API usage record, including repair and zoom turns."""

    input: int = 0
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    turns: int = 0
    zooms: int = 0
    repairs: int = 0

    async def add(self, usage: Any) -> None:
        self.turns += 1
        self.input += getattr(usage, "input_tokens", 0) or 0
        self.output += getattr(usage, "output_tokens", 0) or 0
        self.cache_read += getattr(usage, "cache_read_input_tokens", 0) or 0
        self.cache_write += getattr(usage, "cache_creation_input_tokens", 0) or 0

    @property
    def total_input(self) -> int:
        """All input categories; cache reuse changes price rather than context size."""
        return self.input + self.cache_read + self.cache_write
