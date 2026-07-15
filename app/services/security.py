from __future__ import annotations

import re
from typing import Any


SECRET_PATTERNS = (
    re.compile(r"(?i)bearer\s+[a-z0-9._~+/-]+"),
    re.compile(r"(?i)((?:api[_-]?key|access[_-]?token|token|secret|password)\s*[:=]\s*)[^\s,;]+"),
    re.compile(r"\bsk-[a-zA-Z0-9_-]{8,}\b"),
)


def redact_secrets(value: str | None, *, max_length: int = 2000) -> str | None:
    if value is None:
        return None
    text = str(value)
    for pattern in SECRET_PATTERNS:
        text = pattern.sub(lambda match: f"{match.group(1)}[REDACTED]" if match.lastindex else "[REDACTED]", text)
    return text[:max_length]


def redact_structure(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        secret_keys = {"api_key", "access_token", "token", "secret", "password", "authorization"}
        for key, nested in list(value.items())[:200]:
            safe_key = str(key)[:120]
            normalized = safe_key.lower().replace("-", "_")
            result[safe_key] = "[REDACTED]" if normalized in secret_keys else redact_structure(nested)
        return result
    if isinstance(value, list):
        return [redact_structure(item) for item in value[:500]]
    if isinstance(value, tuple):
        return [redact_structure(item) for item in value[:500]]
    if isinstance(value, str):
        return redact_secrets(value)
    return value
