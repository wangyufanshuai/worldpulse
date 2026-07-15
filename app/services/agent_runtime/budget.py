from __future__ import annotations

from dataclasses import dataclass
from math import ceil


def estimate_tokens(*texts: str) -> int:
    return max(1, ceil(sum(len(text or "") for text in texts) / 4))


@dataclass
class RuntimeBudget:
    max_calls: int
    token_budget: int
    calls: int = 0
    tokens: int = 0

    def can_start(self, input_tokens: int) -> bool:
        return self.calls < self.max_calls and self.tokens + input_tokens <= self.token_budget

    def consume(self, input_tokens: int, output_tokens: int) -> None:
        self.calls += 1
        self.tokens += max(0, input_tokens) + max(0, output_tokens)
