"""Immutable experiment branch helpers."""

from __future__ import annotations

from .contracts import Checkpoint, ExperimentBranch, WorldState


def branch_world_state(checkpoint: Checkpoint, branch: ExperimentBranch) -> WorldState:
    if branch.parent_checkpoint_hash != checkpoint.content_hash():
        raise ValueError("Experiment branch parent checkpoint hash mismatch")
    if branch.branch_id == checkpoint.branch_id:
        raise ValueError("Experiment branch must have a distinct branch id")
    return checkpoint.world_state.model_copy(update={"run_id": f"{checkpoint.world_state.run_id}:{branch.branch_id}", "seed": branch.seed, "tick": 0})
