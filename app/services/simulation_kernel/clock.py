"""Deterministic integer clock for Kernel V2."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DeterministicClock:
    tick: int = 0
    phase: str = "prepare"

    def advance(self, *, tick: int, phase: str) -> DeterministicClock:
        if tick < self.tick:
            raise ValueError("DeterministicClock cannot move backwards")
        if tick == self.tick and phase == self.phase:
            raise ValueError("DeterministicClock advance must change tick or phase")
        if not phase.strip():
            raise ValueError("DeterministicClock phase cannot be empty")
        return DeterministicClock(tick=tick, phase=phase)
