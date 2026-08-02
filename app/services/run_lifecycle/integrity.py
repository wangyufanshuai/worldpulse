"""Pure integrity primitives for Run Control artifacts."""

from __future__ import annotations

import hashlib


def artifact_digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()
