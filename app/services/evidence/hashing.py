"""Content-addressed hashing for the Evidence bounded context.

The functions in this module are deliberately pure.  Snapshot and pack
integrity must use the same canonical representation in persistence mappers
and application workflows, regardless of the active database adapter.
"""

from __future__ import annotations

import hashlib
import json


def canonical_json(value: dict) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def snapshot_digest(
    source_id: str,
    project_id: str | None,
    external_ref: str,
    title: str,
    category: str,
    canonical_content: str,
    observed_at: str,
    cutoff_at: str,
) -> str:
    return sha256_text(canonical_json({
        "schema_version": "evidence-snapshot.v1",
        "source_id": source_id,
        "project_id": project_id,
        "external_ref": external_ref,
        "title": title,
        "category": category,
        "content": json.loads(canonical_content),
        "observed_at": observed_at,
        "cutoff_at": cutoff_at,
    }))
