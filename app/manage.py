from __future__ import annotations

import argparse
import json
import os
from getpass import getpass

from app.db import apply_migrations, migration_status, verify_schema
from app.services.project_store import DB_PATH
from app.db.postgres import (
    apply_postgres_migrations,
    database_url,
    export_postgres_schema,
    is_postgres_url,
    portability_report,
    postgres_migration_status,
    verify_postgres_schema,
)
from app.db.transfer import copy_sqlite_to_postgres


def _migration_command(action: str) -> int:
    if is_postgres_url():
        if action == "apply":
            applied = apply_postgres_migrations(database_url())
            print(json.dumps({"status": "ok", "backend": "postgresql", "applied": applied}, ensure_ascii=False))
        elif action == "status":
            print(json.dumps(postgres_migration_status(database_url()), ensure_ascii=False, indent=2))
        elif action == "verify":
            print(json.dumps(verify_postgres_schema(database_url()), ensure_ascii=False))
        return 0
    if action == "apply":
        applied = apply_migrations(DB_PATH)
        print(json.dumps({"status": "ok", "applied": [item.version for item in applied]}, ensure_ascii=False))
    elif action == "status":
        print(json.dumps(migration_status(DB_PATH), ensure_ascii=False, indent=2))
    elif action == "verify":
        print(json.dumps(verify_schema(DB_PATH), ensure_ascii=False))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="WorldPulse administration commands")
    sub = parser.add_subparsers(dest="command", required=True)
    migrate = sub.add_parser("migrate", help="Apply or inspect numbered schema migrations")
    migrate.add_argument("action", nargs="?", default="apply", choices=("apply", "status", "verify"))
    sub.add_parser("status", help="Alias for migrate status")
    sub.add_parser("verify", help="Alias for migrate verify")
    create_admin = sub.add_parser("create-admin", help="Create the first local administrator")
    create_admin.add_argument("--username", required=True)
    create_admin.add_argument("--display-name", default="WorldPulse Admin")
    create_admin.add_argument("--password")
    create_user_parser = sub.add_parser("create-user", help="Create a local user with an explicit role")
    create_user_parser.add_argument("--username", required=True)
    create_user_parser.add_argument("--display-name", default="WorldPulse User")
    create_user_parser.add_argument("--role", required=True, choices=("admin", "analyst", "reviewer", "viewer"))
    create_user_parser.add_argument("--password")
    readiness = sub.add_parser("db-readiness", help="Report PostgreSQL runtime portability blockers")
    readiness.add_argument("--output", help="Optionally export the translated PostgreSQL schema")
    db_copy = sub.add_parser("db-copy", help="Copy and audit a SQLite database into PostgreSQL")
    db_copy.add_argument("--source", default=str(DB_PATH), help="SQLite source path")
    db_copy.add_argument("--target-url", default=database_url(), help="PostgreSQL target URL")
    db_copy.add_argument("--verify-only", action="store_true", help="Only compare source and target")
    blobs = sub.add_parser("blobs", help="Inspect content-addressed source document blobs")
    blobs.add_argument("action", choices=("verify",))
    monitoring = sub.add_parser("monitoring", help="Inspect continuous intelligence monitoring")
    monitoring.add_argument("action", choices=("verify", "poll-due"))
    notifications = sub.add_parser("notifications", help="Manage notification deliveries")
    notifications.add_argument("action", choices=("retry-failed",))
    benchmark_parser = sub.add_parser("benchmark", help="Manage historical benchmark manifests and sealed labels")
    benchmark_parser.add_argument("action", choices=("ingest-manifest", "import-label-pack", "verify", "status", "validate-source-plan", "fetch-sources", "build-manifest", "pack-labels"))
    benchmark_parser.add_argument("--file", help="Manifest or sealed label pack JSON file")
    benchmark_parser.add_argument("--source-plan", help="Source plan JSON used to build a manifest or select blind cases")
    benchmark_parser.add_argument("--output", help="Write a generated lock, manifest or label pack JSON file")
    benchmark_parser.add_argument("--signer-key-id", default="offline-release")
    benchmark_parser.add_argument("--encryption-key-id", default="offline-labels")
    benchmark_parser.add_argument("--evidence-hash", default="")
    benchmark_parser.add_argument("--organization", default="org_default")
    evaluation = sub.add_parser("evaluation", help="Manage cross-mode evaluation suites and batches")
    evaluation.add_argument("action", choices=("seed", "verify", "run-standard", "run-release", "status"))
    evaluation.add_argument("--provider", choices=("mock", "deepseek", "siliconflow"), default="mock")
    evaluation.add_argument("--wait", action="store_true")
    evaluation.add_argument("--label-pack")
    args = parser.parse_args()
    if args.command in {"migrate", "status", "verify"}:
        action = args.action if args.command == "migrate" else args.command
        return _migration_command(action)
    if args.command in {"create-admin", "create-user"}:
        from app.services.auth import create_user
        password = args.password or getpass("Admin password: ")
        confirmation = args.password or getpass("Confirm password: ")
        if password != confirmation:
            parser.error("Passwords do not match")
        role = "admin" if args.command == "create-admin" else args.role
        user = create_user(args.username, password, args.display_name, role)
        print(json.dumps(user.model_dump(mode="json"), ensure_ascii=False))
        return 0
    if args.command == "db-readiness":
        result = portability_report()
        if args.output:
            result["schema_output"] = str(export_postgres_schema(args.output))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ready" else 1
    if args.command == "db-copy":
        if not args.target_url or not is_postgres_url(args.target_url):
            parser.error("--target-url must be a PostgreSQL URL (or set WORLDPULSE_DATABASE_URL)")
        result = copy_sqlite_to_postgres(args.source, args.target_url, verify_only=args.verify_only)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    if args.command == "blobs":
        from app.services.scenario_compiler import ScenarioCompilerService
        result = ScenarioCompilerService().verify_blobs()
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["status"] == "ok" else 1
    if args.command == "monitoring":
        from app.services.continuous_intelligence import ContinuousIntelligenceService
        service = ContinuousIntelligenceService()
        result = service.verify() if args.action == "verify" else {"status": "ok", "queued": service.enqueue_due_polls()}
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") == "ok" else 1
    if args.command == "notifications":
        from app.services.continuous_intelligence import ContinuousIntelligenceService
        changed = ContinuousIntelligenceService().retry_failed_deliveries()
        print(json.dumps({"status": "ok", "retried": changed}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "benchmark":
        from pathlib import Path
        from app.services.auth import ensure_system_user
        from app.services.evaluation import benchmark
        from app.services.evaluation import benchmark_tools
        if args.action == "verify":
            result = benchmark.verify_benchmarks()
        elif args.action == "status":
            result = {
                "status": "ok",
                "suites": [item.model_dump(mode="json") for item in benchmark.list_suites()],
                "label_packs": [item.model_dump(mode="json") for item in benchmark.list_label_packs(args.organization)],
            }
        elif args.action == "validate-source-plan":
            if not args.file:
                parser.error("--file is required")
            result = benchmark_tools.validate_source_plan(json.loads(Path(args.file).read_text(encoding="utf-8")))
        elif args.action == "fetch-sources":
            if not args.file:
                parser.error("--file is required")
            result = benchmark_tools.fetch_sources(json.loads(Path(args.file).read_text(encoding="utf-8")))
        elif args.action == "build-manifest":
            if not args.file or not args.source_plan:
                parser.error("build-manifest requires --file <acquisition-lock> and --source-plan <source-plan>")
            lock = json.loads(Path(args.file).read_text(encoding="utf-8"))
            source_plan = json.loads(Path(args.source_plan).read_text(encoding="utf-8"))
            result = benchmark_tools.build_manifest_from_lock(lock, source_plan)
        elif args.action == "pack-labels":
            if not args.file or not args.source_plan:
                parser.error("pack-labels requires --file <blind-labels> and --source-plan <source-plan>")
            labels = json.loads(Path(args.file).read_text(encoding="utf-8"))
            source_plan = benchmark_tools.validate_source_plan(json.loads(Path(args.source_plan).read_text(encoding="utf-8")))
            blind_ids = {item["case_id"] for item in source_plan["cases"] if item["split"] == "blind"}
            aes_key = os.getenv("WORLDPULSE_OFFLINE_AES_KEY", "")
            signer_key = os.getenv("WORLDPULSE_OFFLINE_SIGNER_PRIVATE_KEY", "")
            if not aes_key or not signer_key:
                parser.error("pack-labels requires WORLDPULSE_OFFLINE_AES_KEY and WORLDPULSE_OFFLINE_SIGNER_PRIVATE_KEY")
            result = benchmark_tools.pack_labels(
                labels,
                blind_ids,
                aes_key_b64=aes_key,
                signer_private_key_b64=signer_key,
                signer_key_id=args.signer_key_id,
                encryption_key_id=args.encryption_key_id,
                evidence_hash=args.evidence_hash or source_plan["source_plan_hash"],
            )
        else:
            if not args.file:
                parser.error("--file is required")
            payload = json.loads(Path(args.file).read_text(encoding="utf-8"))
            if args.action == "ingest-manifest":
                result = benchmark.ingest_manifest(payload, ensure_system_user()).model_dump(mode="json")
            else:
                from app.core.evaluation_models import LabelPackImportRequest
                result = benchmark.import_label_pack(args.organization, LabelPackImportRequest.model_validate(payload), ensure_system_user()).model_dump(mode="json")
        if args.output and args.action in {"fetch-sources", "build-manifest", "pack-labels"}:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in {"failed"} else 1
    if args.command == "evaluation":
        from app.services.evaluation import EvaluationService
        from app.core.evaluation_models import EvaluationBatchCreateRequest
        from app.services.auth import ensure_system_user
        service = EvaluationService()
        if args.action == "seed":
            result = service.ensure_suite().model_dump(mode="json")
        elif args.action == "verify":
            suite = service.ensure_suite(); cases = service.list_cases(suite.suite_id)
            gate = __import__("app.services.evaluation.gates", fromlist=["ensure_gate_manifest"]).ensure_gate_manifest()
            batches = service.list_batches("org_default")
            completed = [item for item in batches if item.status == "completed"]
            failed = [item for item in batches if item.status == "failed"]
            result = {
                "status": "ok" if len(cases) == 12 and gate.manifest_hash and not failed and all(item.safety_status == "passed" for item in completed) else "failed",
                "suite_hash": suite.manifest_hash,
                "case_count": len(cases),
                "gate_manifest_hash": gate.manifest_hash,
                "completed_batches": len(completed),
                "failed_batches": len(failed),
                "pending_batches": sum(item.status not in {"completed", "failed", "cancelled"} for item in batches),
            }
        elif args.action == "status":
            result = {"status": "ok", "batches": [item.model_dump(mode="json") for item in service.list_batches("org_default")]}
        elif args.action == "run-standard":
            batch = service.create_standard_batch("org_default", ensure_system_user(), EvaluationBatchCreateRequest(provider=args.provider))
            if args.wait:
                from app.services.run_lifecycle import process_one_queued_job
                for _ in range(batch.total_members * 10):
                    service.reconcile(worker_id="evaluation-cli")
                    job = process_one_queued_job(worker_id="evaluation-cli")
                    service.reconcile(worker_id="evaluation-cli")
                    current = service.get_batch(batch.batch_id)
                    if current.status in {"completed", "failed", "cancelled"}: break
                    if job is None and not service.list_members(batch.batch_id): break
                batch = service.get_batch(batch.batch_id)
            result = batch.model_dump(mode="json")
        else:
            if args.provider != "mock":
                parser.error("run-release only supports --provider mock")
            if not args.label_pack:
                parser.error("run-release requires --label-pack")
            from app.core.evaluation_models import HistoricalEvaluationCreateRequest
            actor = ensure_system_user()
            engineering = service.create_standard_batch("org_default", actor, EvaluationBatchCreateRequest(provider="mock"))
            historical = service.create_historical_batch("org_default", actor, HistoricalEvaluationCreateRequest(label_pack_id=args.label_pack))
            if args.wait:
                from app.services.run_lifecycle import process_one_queued_job
                for _ in range(414 * 12):
                    service.reconcile(worker_id="evaluation-release-cli")
                    process_one_queued_job(worker_id="evaluation-release-cli")
                    service.reconcile(worker_id="evaluation-release-cli")
                    states = [service.get_batch(engineering.batch_id).status, service.get_batch(historical.batch_id).status]
                    if all(item in {"completed", "failed", "cancelled"} for item in states):
                        break
            result = {
                "status": "ok" if all(service.get_batch(item.batch_id).status == "completed" for item in (engineering, historical)) else "failed",
                "member_count": 414,
                "engineering": service.get_batch(engineering.batch_id).model_dump(mode="json"),
                "historical": service.get_batch(historical.batch_id).model_dump(mode="json"),
            }
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("status") not in {"failed"} else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
