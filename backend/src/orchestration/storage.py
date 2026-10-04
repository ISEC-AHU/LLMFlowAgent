import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from deps import db


JSON_FIELDS = {
    "dag",
    "simulation_results",
    "universal_rubric",
    "final_rubric",
    "evaluation_report",
    "issues",
    "repair_plan",
    "repair_summary",
    "validation_results",
    "payload",
}


def now_ms() -> int:
    return int(time.time() * 1000)


def _row_to_dict(row) -> Dict[str, Any]:
    if row is None:
        return {}
    if hasattr(row, "keys"):
        return {key: row[key] for key in row.keys()}
    raise TypeError(f"Unsupported database row type: {type(row)}")


def _decode_json_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    decoded = dict(data)
    for field in JSON_FIELDS:
        value = decoded.get(field)
        if isinstance(value, str):
            try:
                decoded[field] = json.loads(value)
            except json.JSONDecodeError:
                pass
    return decoded


def ensure_orchestration_schema() -> None:
    migrations_dir = Path(__file__).resolve().parents[2] / "migrations"
    for migration_name in ("001_workflows.sql", "002_workflow_runs.sql"):
        migration_path = migrations_dir / migration_name
        sql = migration_path.read_text(encoding="utf-8")
        db.execute_query(sql)
    timestamp = now_ms()
    db.execute_query(
        """
        WITH interrupted AS (
            SELECT id,
                   status AS previous_status,
                   active_agent AS previous_agent,
                   active_step AS previous_step,
                   current_version AS previous_version,
                   updated_at AS previous_updated_at
            FROM workflow_run
            WHERE status IN (
                'pending', 'generating', 'evaluating', 'repairing', 'verifying'
            )
            FOR UPDATE
        ),
        updated AS (
            UPDATE workflow_run AS run
            SET status = 'needs_review',
                active_agent = NULL,
                active_step = NULL,
                error_message = COALESCE(
                    run.error_message,
                    'The previous server process stopped before this run completed.'
                ),
                updated_at = %s
            FROM interrupted
            WHERE run.id = interrupted.id
            RETURNING run.id
        ),
        event_candidates AS (
            SELECT interrupted.id,
                   interrupted.previous_status,
                   interrupted.previous_agent,
                   interrupted.previous_step,
                   interrupted.previous_version,
                   interrupted.previous_updated_at
            FROM interrupted
            INNER JOIN updated ON updated.id = interrupted.id

            UNION ALL

            SELECT run.id,
                   run.status AS previous_status,
                   run.active_agent AS previous_agent,
                   run.active_step AS previous_step,
                   run.current_version AS previous_version,
                   run.updated_at AS previous_updated_at
            FROM workflow_run AS run
            WHERE run.status = 'needs_review'
              AND run.error_message =
                  'The previous server process stopped before this run completed.'
              AND NOT EXISTS (
                  SELECT 1 FROM interrupted WHERE interrupted.id = run.id
              )
        )
        INSERT INTO workflow_run_event (
            run_id, event_type, agent, step, version_no,
            message, payload, created_at
        )
        SELECT candidate.id,
               'coordinator_interrupted',
               'coordinator',
               'interrupted',
               candidate.previous_version,
               'Coordinator Agent detected that the previous server process stopped before the run completed.',
               json_build_object(
                   'previous_status', candidate.previous_status,
                   'previous_agent', candidate.previous_agent,
                   'previous_step', candidate.previous_step
               )::text,
               %s
        FROM event_candidates AS candidate
        WHERE NOT EXISTS (
            SELECT 1
            FROM workflow_run_event AS event
            WHERE event.run_id = candidate.id
              AND event.event_type = 'coordinator_interrupted'
              AND event.created_at >= candidate.previous_updated_at
        )
        """,
        (timestamp, timestamp),
    )


class WorkflowRunStorage:
    def create_run(
        self,
        *,
        run_id: str,
        workflow_id: int,
        uid: int,
        description: str,
        max_iterations: int,
        regeneration_threshold: float,
        acceptance_threshold: float,
        auto_repair: bool,
    ) -> None:
        timestamp = now_ms()
        db.execute_query(
            """
            INSERT INTO workflow_run (
                id, workflow_id, uid, description, status,
                max_iterations, regeneration_threshold,
                acceptance_threshold, auto_repair, updated_at
            )
            VALUES (%s, %s, %s, %s, 'pending', %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                workflow_id,
                uid,
                description,
                max_iterations,
                regeneration_threshold,
                acceptance_threshold,
                auto_repair,
                timestamp,
            ),
        )

    def get_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        rows = db.fetch_query(
            "SELECT * FROM workflow_run WHERE id = %s LIMIT 1",
            (run_id,),
        )
        return _row_to_dict(rows[0]) if rows else None

    def get_latest_run(self, workflow_id: int) -> Optional[Dict[str, Any]]:
        rows = db.fetch_query(
            """
            SELECT *
            FROM workflow_run
            WHERE workflow_id = %s
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (workflow_id,),
        )
        return _row_to_dict(rows[0]) if rows else None

    def get_active_run(self, workflow_id: int) -> Optional[Dict[str, Any]]:
        rows = db.fetch_query(
            """
            SELECT *
            FROM workflow_run
            WHERE workflow_id = %s
              AND status IN (
                  'pending', 'generating', 'evaluating', 'repairing', 'verifying',
                  'awaiting_review'
              )
            ORDER BY updated_at DESC
            LIMIT 1
            """,
            (workflow_id,),
        )
        return _row_to_dict(rows[0]) if rows else None

    def update_run(self, run_id: str, **fields: Any) -> None:
        if not fields:
            return
        fields["updated_at"] = now_ms()
        assignments = ", ".join(f"{key} = %({key})s" for key in fields)
        params = {**fields, "run_id": run_id}
        db.execute_query(
            f"UPDATE workflow_run SET {assignments} WHERE id = %(run_id)s",
            params,
        )

    def request_stop(self, run_id: str) -> None:
        self.update_run(run_id, stop_requested=True)

    def should_stop(self, run_id: str) -> bool:
        run = self.get_run(run_id)
        return bool(run and run.get("stop_requested"))

    def add_event(
        self,
        run_id: str,
        event_type: str,
        *,
        agent: Optional[str] = None,
        step: Optional[str] = None,
        version_no: Optional[int] = None,
        message: str = "",
        payload: Any = None,
    ) -> None:
        db.execute_query(
            """
            INSERT INTO workflow_run_event (
                run_id, event_type, agent, step, version_no,
                message, payload, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                run_id,
                event_type,
                agent,
                step,
                version_no,
                message,
                json.dumps(payload, ensure_ascii=False) if payload is not None else None,
                now_ms(),
            ),
        )

    def list_events(self, run_id: str, limit: int = 100) -> List[Dict[str, Any]]:
        rows = db.fetch_query(
            """
            SELECT *
            FROM workflow_run_event
            WHERE run_id = %s
            ORDER BY id DESC
            LIMIT %s
            """,
            (run_id, limit),
        )
        return [
            _decode_json_fields(_row_to_dict(row))
            for row in reversed(rows)
        ]

    def create_version(
        self,
        *,
        run_id: str,
        workflow_id: int,
        version_no: int,
        parent_version_no: Optional[int],
        dag: Dict[str, Any],
        fingerprint: str,
        repair_plan: Any = None,
        repair_summary: Any = None,
    ) -> None:
        db.execute_query(
            """
            INSERT INTO workflow_version (
                run_id, workflow_id, version_no, parent_version_no,
                dag, fingerprint, repair_plan, repair_summary, created_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (run_id, version_no)
            DO UPDATE SET
                dag = EXCLUDED.dag,
                fingerprint = EXCLUDED.fingerprint,
                repair_plan = EXCLUDED.repair_plan,
                repair_summary = EXCLUDED.repair_summary
            """,
            (
                run_id,
                workflow_id,
                version_no,
                parent_version_no,
                json.dumps(dag, ensure_ascii=False),
                fingerprint,
                json.dumps(repair_plan, ensure_ascii=False)
                if repair_plan is not None
                else None,
                json.dumps(repair_summary, ensure_ascii=False)
                if repair_summary is not None
                else None,
                now_ms(),
            ),
        )

    def update_version(self, run_id: str, version_no: int, **fields: Any) -> None:
        if not fields:
            return
        encoded = {}
        for key, value in fields.items():
            encoded[key] = (
                json.dumps(value, ensure_ascii=False)
                if key in JSON_FIELDS and value is not None
                else value
            )
        assignments = ", ".join(f"{key} = %({key})s" for key in encoded)
        params = {**encoded, "run_id": run_id, "version_no": version_no}
        db.execute_query(
            f"""
            UPDATE workflow_version
            SET {assignments}
            WHERE run_id = %(run_id)s AND version_no = %(version_no)s
            """,
            params,
        )

    def get_version(
        self, run_id: str, version_no: int
    ) -> Optional[Dict[str, Any]]:
        rows = db.fetch_query(
            """
            SELECT *
            FROM workflow_version
            WHERE run_id = %s AND version_no = %s
            LIMIT 1
            """,
            (run_id, version_no),
        )
        if not rows:
            return None
        return _decode_json_fields(_row_to_dict(rows[0]))

    def list_versions(self, run_id: str) -> List[Dict[str, Any]]:
        rows = db.fetch_query(
            """
            SELECT *
            FROM workflow_version
            WHERE run_id = %s
            ORDER BY version_no
            """,
            (run_id,),
        )
        return [
            _decode_json_fields(_row_to_dict(row))
            for row in rows
        ]

    def fingerprint_exists(self, run_id: str, fingerprint: str) -> bool:
        rows = db.fetch_query(
            """
            SELECT 1
            FROM workflow_version
            WHERE run_id = %s AND fingerprint = %s
            LIMIT 1
            """,
            (run_id, fingerprint),
        )
        return bool(rows)

    def get_detail(self, run_id: str) -> Optional[Dict[str, Any]]:
        run = self.get_run(run_id)
        if not run:
            return None
        return {
            **run,
            "versions": self.list_versions(run_id),
            "events": self.list_events(run_id),
        }
