from __future__ import annotations

from datetime import datetime

from app.core.negotiation_models import (
    AgentPackManifest,
    CommitmentEvent,
    NegotiationCommitment,
    NegotiationMessage,
    NegotiationRound,
    NegotiationSession,
)
from app.services.consistency.hashing import stable_hash
from app.services.project_store import connect, dumps, init_db, loads


def now_iso() -> str:
    return datetime.now().isoformat(timespec="milliseconds")


class NegotiationRepository:
    def save_agent_pack(self, pack: AgentPackManifest) -> AgentPackManifest:
        init_db()
        with connect() as conn:
            conn.execute(
                """INSERT INTO agent_packs
                (agent_pack_id, schema_version, status, seed, profiles_json, manifest_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(agent_pack_id) DO NOTHING""",
                (pack.agent_pack_id, pack.schema_version, pack.status, pack.seed, dumps([item.model_dump(mode="json") for item in pack.profiles]), pack.manifest_hash, pack.created_at),
            )
        return self.get_agent_pack(pack.agent_pack_id)

    def list_agent_packs(self) -> list[AgentPackManifest]:
        init_db()
        with connect() as conn:
            rows = conn.execute("SELECT * FROM agent_packs ORDER BY created_at DESC, agent_pack_id DESC").fetchall()
        return [self._pack(row) for row in rows]

    def get_agent_pack(self, agent_pack_id: str) -> AgentPackManifest:
        with connect() as conn:
            row = conn.execute("SELECT * FROM agent_packs WHERE agent_pack_id = ?", (agent_pack_id,)).fetchone()
        if row is None:
            raise KeyError(f"Unknown Agent Pack: {agent_pack_id}")
        return self._pack(row)

    def create_session(self, run_id: str, pack: AgentPackManifest, baseline_hash: str) -> NegotiationSession:
        session_id = f"neg_{stable_hash({'run_id': run_id, 'pack': pack.manifest_hash})[:20]}"
        created_at = now_iso()
        with connect() as conn:
            conn.execute(
                """INSERT INTO negotiation_sessions
                (session_id, run_id, agent_pack_id, agent_pack_hash, status, current_tick, baseline_result_hash,
                 cumulative_patch_json, applied_proposal_ids_json, created_at)
                VALUES (?, ?, ?, ?, 'running', 0, ?, '{}', '[]', ?)
                ON CONFLICT(run_id) DO NOTHING""",
                (session_id, run_id, pack.agent_pack_id, pack.manifest_hash, baseline_hash, created_at),
            )
            conn.execute("UPDATE run_jobs SET agent_pack_id = ?, agent_pack_hash = ? WHERE run_id = ?", (pack.agent_pack_id, pack.manifest_hash, run_id))
            row = conn.execute("SELECT * FROM negotiation_sessions WHERE run_id = ?", (run_id,)).fetchone()
        return self._session(row)

    def get_session(self, run_id: str) -> NegotiationSession:
        init_db()
        with connect() as conn:
            row = conn.execute("SELECT * FROM negotiation_sessions WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(f"No negotiation session for run: {run_id}")
        return self._session(row)

    def create_round(self, session: NegotiationSession, tick: int, day: int, agents: list[str], input_payload: dict, previous_hash: str) -> NegotiationRound:
        round_id = f"round_{stable_hash({'session': session.session_id, 'tick': tick})[:20]}"
        input_hash = stable_hash(input_payload)
        with connect() as conn:
            conn.execute(
                """INSERT INTO negotiation_rounds
                (round_id, session_id, tick, simulation_day, status, scheduled_agents_json, input_json, input_hash,
                 previous_state_hash, started_at) VALUES (?, ?, ?, ?, 'running', ?, ?, ?, ?, ?)
                ON CONFLICT(session_id, tick) DO NOTHING""",
                (round_id, session.session_id, tick, day, dumps(agents), dumps(input_payload), input_hash, previous_hash, now_iso()),
            )
            row = conn.execute("SELECT * FROM negotiation_rounds WHERE session_id = ? AND tick = ?", (session.session_id, tick)).fetchone()
        return self._round(row)

    def complete_round(self, round_id: str, output: dict, modifier_hash: str | None, result_hash: str) -> NegotiationRound:
        output_hash = stable_hash(output)
        with connect() as conn:
            conn.execute(
                """UPDATE negotiation_rounds SET status = 'completed', output_json = ?, output_hash = ?,
                modifier_bundle_hash = ?, result_state_hash = ?, completed_at = ? WHERE round_id = ?""",
                (dumps(output), output_hash, modifier_hash, result_hash, now_iso(), round_id),
            )
            row = conn.execute("SELECT * FROM negotiation_rounds WHERE round_id = ?", (round_id,)).fetchone()
        return self._round(row)

    def list_rounds(self, session_id: str) -> list[NegotiationRound]:
        init_db()
        with connect() as conn:
            rows = conn.execute("SELECT * FROM negotiation_rounds WHERE session_id = ? ORDER BY tick", (session_id,)).fetchall()
        return [self._round(row) for row in rows]

    def add_message(self, session_id: str, round_id: str, tick: int, envelope, *, provider: str = "mock-deterministic", model: str = "mock-negotiation-v1", latency_ms: int = 0, estimated_tokens: int = 0, fallback_used: bool = False) -> NegotiationMessage:
        with connect() as conn:
            existing = conn.execute("SELECT * FROM negotiation_messages WHERE session_id = ? AND tick = ? AND sender_agent_id = ?", (session_id, tick, envelope.sender_agent_id)).fetchone()
            if existing:
                return self._message(existing)
            previous = conn.execute("SELECT seq, message_hash FROM negotiation_messages WHERE session_id = ? ORDER BY seq DESC LIMIT 1", (session_id,)).fetchone()
            seq = int(previous["seq"] + 1) if previous else 1
            previous_hash = previous["message_hash"] if previous else None
            created_at = f"2000-01-01T00:{tick:02d}:{seq:02d}.000Z"
            proposal_payload = envelope.proposal.model_dump(mode="json") if envelope.proposal else None
            payload = {"proposal": proposal_payload} if proposal_payload else {}
            identity = {
                "tick": tick, "seq": seq, "sender_agent_id": envelope.sender_agent_id,
                "recipient_agent_ids": envelope.recipient_agent_ids, "message_type": envelope.message_type,
                "visibility": envelope.visibility, "parent_message_id": envelope.parent_message_id,
                "proposal": proposal_payload, "narrative": envelope.narrative, "previous_hash": previous_hash,
            }
            message_hash = stable_hash(identity)
            message_id = f"msg_{message_hash[:20]}"
            conn.execute(
                """INSERT INTO negotiation_messages
                (message_id, session_id, round_id, tick, seq, sender_agent_id, recipient_agent_ids_json,
                 message_type, visibility, parent_message_id, proposal_id, narrative, payload_json, provider,
                 model, latency_ms, estimated_tokens, fallback_used, previous_hash, message_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (message_id, session_id, round_id, tick, seq, envelope.sender_agent_id, dumps(envelope.recipient_agent_ids),
                 envelope.message_type, envelope.visibility, envelope.parent_message_id,
                 envelope.proposal.proposal_id if envelope.proposal else None, envelope.narrative, dumps(payload),
                 provider, model, latency_ms, estimated_tokens, int(fallback_used), previous_hash, message_hash, created_at),
            )
            row = conn.execute("SELECT * FROM negotiation_messages WHERE message_id = ?", (message_id,)).fetchone()
        return self._message(row)

    def list_messages(self, session_id: str, *, after_seq: int = 0, tick: int | None = None) -> list[NegotiationMessage]:
        init_db()
        sql = "SELECT * FROM negotiation_messages WHERE session_id = ? AND seq > ?"
        params: list = [session_id, after_seq]
        if tick is not None:
            sql += " AND tick = ?"
            params.append(tick)
        sql += " ORDER BY seq"
        with connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._message(row) for row in rows]

    def create_commitment(self, session_id: str, message: NegotiationMessage, proposal, parties: list[str]) -> NegotiationCommitment:
        terms = proposal.model_dump(mode="json")
        commitment_hash = stable_hash({"source_proposal_id": proposal.proposal_id, "parties": parties, "terms": terms})
        commitment_id = f"commit_{commitment_hash[:20]}"
        with connect() as conn:
            conn.execute(
                """INSERT INTO negotiation_commitments
                (commitment_id, session_id, source_message_id, source_proposal_id, action_type,
                 party_agent_ids_json, terms_json, commitment_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(session_id, source_proposal_id) DO NOTHING""",
                (commitment_id, session_id, message.message_id, proposal.proposal_id, proposal.action_type, dumps(parties), dumps(terms), commitment_hash, now_iso()),
            )
        commitment = next(item for item in self.list_commitments(session_id) if item.source_proposal_id == proposal.proposal_id)
        if not commitment.events:
            self.add_commitment_event(commitment.commitment_id, session_id, message.tick, "proposed", message.sender_agent_id, message.message_id, "Consistency-approved bilateral proposal awaiting recipient acceptance")
        return next(item for item in self.list_commitments(session_id) if item.commitment_id == commitment.commitment_id)

    def add_commitment_event(self, commitment_id: str, session_id: str, tick: int, status: str, actor_id: str, message_id: str, reason: str) -> CommitmentEvent:
        with connect() as conn:
            duplicate = conn.execute("SELECT * FROM negotiation_commitment_events WHERE commitment_id = ? AND source_message_id = ? AND status = ?", (commitment_id, message_id, status)).fetchone()
            if duplicate:
                return self._commitment_event(duplicate)
            row = conn.execute("SELECT COALESCE(MAX(seq), 0) AS seq FROM negotiation_commitment_events WHERE commitment_id = ?", (commitment_id,)).fetchone()
            seq = int(row["seq"] or 0) + 1
            payload = {"commitment_id": commitment_id, "tick": tick, "seq": seq, "status": status, "actor_agent_id": actor_id, "source_message_id": message_id, "reason": reason}
            event_hash = stable_hash(payload)
            event_id = f"cevt_{event_hash[:20]}"
            conn.execute(
                """INSERT INTO negotiation_commitment_events
                (event_id, commitment_id, session_id, tick, seq, status, actor_agent_id, source_message_id, reason, event_hash, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (event_id, commitment_id, session_id, tick, seq, status, actor_id, message_id, reason, event_hash, now_iso()),
            )
            stored = conn.execute("SELECT * FROM negotiation_commitment_events WHERE event_id = ?", (event_id,)).fetchone()
        return self._commitment_event(stored)

    def list_commitments(self, session_id: str) -> list[NegotiationCommitment]:
        init_db()
        with connect() as conn:
            rows = conn.execute("SELECT * FROM negotiation_commitments WHERE session_id = ? ORDER BY created_at, commitment_id", (session_id,)).fetchall()
            event_rows = conn.execute("SELECT * FROM negotiation_commitment_events WHERE session_id = ? ORDER BY commitment_id, seq", (session_id,)).fetchall()
        events: dict[str, list[CommitmentEvent]] = {}
        for row in event_rows:
            event = self._commitment_event(row)
            events.setdefault(event.commitment_id, []).append(event)
        result = []
        for row in rows:
            item_events = events.get(row["commitment_id"], [])
            result.append(NegotiationCommitment(
                commitment_id=row["commitment_id"], session_id=row["session_id"], source_message_id=row["source_message_id"],
                source_proposal_id=row["source_proposal_id"], action_type=row["action_type"], party_agent_ids=loads(row["party_agent_ids_json"], []),
                terms=loads(row["terms_json"], {}), commitment_hash=row["commitment_hash"],
                status=item_events[-1].status if item_events else "proposed", created_at=row["created_at"], events=item_events,
            ))
        return result

    def update_session(self, session_id: str, *, tick: int, result_hash: str, patch: dict, applied_ids: list[str], completed: bool = False) -> NegotiationSession:
        status = "completed" if completed else "running"
        completed_at = now_iso() if completed else None
        with connect() as conn:
            conn.execute(
                """UPDATE negotiation_sessions SET current_tick = ?, final_result_hash = ?, cumulative_patch_json = ?,
                applied_proposal_ids_json = ?, status = ?, completed_at = ? WHERE session_id = ?""",
                (tick, result_hash, dumps(patch), dumps(sorted(set(applied_ids))), status, completed_at, session_id),
            )
            row = conn.execute("SELECT * FROM negotiation_sessions WHERE session_id = ?", (session_id,)).fetchone()
        return self._session(row)

    @staticmethod
    def _pack(row) -> AgentPackManifest:
        return AgentPackManifest(agent_pack_id=row["agent_pack_id"], schema_version=row["schema_version"], status=row["status"], seed=row["seed"], profiles=loads(row["profiles_json"], []), manifest_hash=row["manifest_hash"], created_at=row["created_at"])

    @staticmethod
    def _session(row) -> NegotiationSession:
        return NegotiationSession(session_id=row["session_id"], run_id=row["run_id"], agent_pack_id=row["agent_pack_id"], agent_pack_hash=row["agent_pack_hash"], status=row["status"], current_tick=row["current_tick"], baseline_result_hash=row["baseline_result_hash"], final_result_hash=row["final_result_hash"], cumulative_patch=loads(row["cumulative_patch_json"], {}), applied_proposal_ids=loads(row["applied_proposal_ids_json"], []), created_at=row["created_at"], completed_at=row["completed_at"])

    @staticmethod
    def _round(row) -> NegotiationRound:
        return NegotiationRound(round_id=row["round_id"], session_id=row["session_id"], tick=row["tick"], simulation_day=row["simulation_day"], status=row["status"], scheduled_agents=loads(row["scheduled_agents_json"], []), input=loads(row["input_json"], {}), output=loads(row["output_json"], {}), input_hash=row["input_hash"], output_hash=row["output_hash"], previous_state_hash=row["previous_state_hash"], modifier_bundle_hash=row["modifier_bundle_hash"], result_state_hash=row["result_state_hash"], started_at=row["started_at"], completed_at=row["completed_at"])

    @staticmethod
    def _message(row) -> NegotiationMessage:
        return NegotiationMessage(message_id=row["message_id"], session_id=row["session_id"], round_id=row["round_id"], tick=row["tick"], seq=row["seq"], sender_agent_id=row["sender_agent_id"], recipient_agent_ids=loads(row["recipient_agent_ids_json"], []), message_type=row["message_type"], visibility=row["visibility"], parent_message_id=row["parent_message_id"], proposal_id=row["proposal_id"], narrative=row["narrative"], payload=loads(row["payload_json"], {}), provider=row["provider"], model=row["model"], latency_ms=row["latency_ms"], estimated_tokens=row["estimated_tokens"], fallback_used=bool(row["fallback_used"]), previous_hash=row["previous_hash"], message_hash=row["message_hash"], created_at=row["created_at"])

    @staticmethod
    def _commitment_event(row) -> CommitmentEvent:
        return CommitmentEvent(event_id=row["event_id"], commitment_id=row["commitment_id"], session_id=row["session_id"], tick=row["tick"], seq=row["seq"], status=row["status"], actor_agent_id=row["actor_agent_id"], source_message_id=row["source_message_id"], reason=row["reason"], event_hash=row["event_hash"], created_at=row["created_at"])
