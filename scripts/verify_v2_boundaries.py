"""Verify the ratcheting V2 modular-monolith import boundary.

The current V1 codebase has a small, explicit set of legacy internal imports.
They are reported but temporarily allowed by config/v2-boundaries.json. New
forbidden service-to-API/UI/test imports fail immediately. As contexts migrate,
legacy entries can be removed from the manifest and become hard failures.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.append(node.module)
    return result


def verify(root: Path) -> dict[str, object]:
    manifest = json.loads((root / "config" / "v2-boundaries.json").read_text(encoding="utf-8"))
    forbidden_prefixes = tuple(manifest["forbidden_import_prefixes_from_services"])
    legacy = manifest["legacy_internal_imports"]
    legacy_by_prefix = {item["import_prefix"]: item["allowed_callers"] for item in legacy}
    restricted = manifest.get("restricted_internal_imports", [])
    restricted_by_prefix = {item["import_prefix"]: item["allowed_callers"] for item in restricted}
    violations: list[dict[str, str]] = []
    legacy_hits: list[dict[str, str]] = []

    for path in sorted((root / "app").rglob("*.py")):
        module = ".".join(path.relative_to(root).with_suffix("").parts)
        if module.endswith(".__init__"):
            module = module.removesuffix(".__init__")
        is_service = module.startswith("app.services.")
        for imported in _imports(path):
            if is_service and imported.startswith(forbidden_prefixes):
                violations.append({"caller": module, "import": imported})
            for prefix, callers in legacy_by_prefix.items():
                if imported == prefix or imported.startswith(prefix + "."):
                    if module in callers:
                        legacy_hits.append({"caller": module, "import": imported})
            for prefix, callers in restricted_by_prefix.items():
                if imported == prefix or imported.startswith(prefix + "."):
                    if module not in callers:
                        violations.append({"caller": module, "import": imported})

    return {
        "status": "ok" if not violations else "failed",
        "schema_version": manifest["schema_version"],
        "legacy_internal_imports": len(legacy_hits),
        "forbidden_imports": violations,
    }


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    report = verify(root)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
