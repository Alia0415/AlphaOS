"""Thread-safe SQLite persistence for AlphaOS tasks, events, and reports.

The store keeps only real orchestration facts: the plans the Manager produced,
the events the executor emitted, the aggregations synthesized from evidence, and
the evidence-derived completeness of each report. It never fabricates data.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB_PATH = REPO_ROOT / "alphaos.db"
_ENV_DB_PATH = "ALPHAOS_DB"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _loads(value: str | None) -> Any:
    if value is None or value == "":
        return None
    return json.loads(value)


_SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    prompt TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    plan_json TEXT,
    aggregation_json TEXT,
    final_answer TEXT,
    duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS events (
    task_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    type TEXT NOT NULL,
    agent TEXT,
    step_id TEXT,
    message TEXT NOT NULL,
    metadata_json TEXT,
    ts TEXT NOT NULL,
    PRIMARY KEY (task_id, seq)
);
CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    title TEXT NOT NULL,
    created_at TEXT NOT NULL,
    completeness_json TEXT,
    aggregation_json TEXT
);
CREATE TABLE IF NOT EXISTS followups (
    id TEXT PRIMARY KEY,
    report_id TEXT NOT NULL,
    role TEXT NOT NULL,
    text TEXT NOT NULL,
    evidence_json TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS agent_overrides (
    agent_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS user_profiles (
    profile_id TEXT PRIMARY KEY,
    profile_version INTEGER NOT NULL,
    onboarding_completed INTEGER NOT NULL,
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""


class Store:
    """A single SQLite file guarded by a process-wide lock (WAL mode)."""

    def __init__(self, db_path: str | Path | None = None) -> None:
        resolved = db_path or os.environ.get(_ENV_DB_PATH) or DEFAULT_DB_PATH
        self.db_path = Path(resolved)
        if self.db_path.parent and not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL;")
            self._conn.execute("PRAGMA foreign_keys=ON;")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    # -- tasks ---------------------------------------------------------------

    def create_task(
        self,
        *,
        task_id: str,
        prompt: str,
        status: str,
        plan: Any | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks (id, prompt, status, created_at, plan_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (task_id, prompt, status, _now(), _dumps(plan) if plan is not None else None),
            )
            self._conn.commit()

    def update_task_plan(
        self,
        task_id: str,
        *,
        status: str,
        plan: Any | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET status = ?, plan_json = ? WHERE id = ?",
                (status, _dumps(plan) if plan is not None else None, task_id),
            )
            self._conn.commit()

    def update_task_request(
        self,
        task_id: str,
        *,
        prompt: str,
        status: str,
        plan: Any | None = None,
    ) -> None:
        """Atomically persist a re-governed clarification request and plan."""

        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET prompt = ?, status = ?, plan_json = ? "
                "WHERE id = ?",
                (
                    prompt,
                    status,
                    _dumps(plan) if plan is not None else None,
                    task_id,
                ),
            )
            self._conn.commit()

    def append_event(
        self,
        task_id: str,
        *,
        type: str,
        message: str,
        agent: str | None = None,
        step_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        ts: str | None = None,
    ) -> int:
        with self._lock:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS next FROM events WHERE task_id = ?",
                (task_id,),
            ).fetchone()
            seq = int(row["next"])
            self._conn.execute(
                "INSERT INTO events "
                "(task_id, seq, type, agent, step_id, message, metadata_json, ts) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task_id,
                    seq,
                    type,
                    agent,
                    step_id,
                    message,
                    _dumps(metadata) if metadata is not None else None,
                    ts or _now(),
                ),
            )
            self._conn.commit()
            return seq

    def finish_task(
        self,
        task_id: str,
        *,
        status: str,
        aggregation: Any | None = None,
        final_answer: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET status = ?, aggregation_json = ?, "
                "final_answer = ?, duration_ms = ? WHERE id = ?",
                (
                    status,
                    _dumps(aggregation) if aggregation is not None else None,
                    final_answer,
                    duration_ms,
                    task_id,
                ),
            )
            self._conn.commit()

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            task_row = self._conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            if task_row is None:
                return None
            event_rows = self._conn.execute(
                "SELECT * FROM events WHERE task_id = ? ORDER BY seq ASC",
                (task_id,),
            ).fetchall()
        return _task_to_dict(task_row, event_rows)

    def list_tasks(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, prompt, status, created_at, duration_ms "
                "FROM tasks ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "prompt": row["prompt"],
                "status": row["status"],
                "created_at": row["created_at"],
                "duration_ms": row["duration_ms"],
            }
            for row in rows
        ]

    # -- reports -------------------------------------------------------------

    def create_report(
        self,
        *,
        report_id: str,
        task_id: str,
        title: str,
        completeness: Any | None = None,
        aggregation: Any | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO reports "
                "(id, task_id, title, created_at, completeness_json, aggregation_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    report_id,
                    task_id,
                    title,
                    _now(),
                    _dumps(completeness) if completeness is not None else None,
                    _dumps(aggregation) if aggregation is not None else None,
                ),
            )
            self._conn.commit()

    def get_report(self, report_id: str) -> dict[str, Any] | None:
        with self._lock:
            report_row = self._conn.execute(
                "SELECT * FROM reports WHERE id = ?", (report_id,)
            ).fetchone()
            if report_row is None:
                return None
            followup_rows = self._conn.execute(
                "SELECT * FROM followups WHERE report_id = ? ORDER BY created_at ASC, id ASC",
                (report_id,),
            ).fetchall()
        report = _report_to_dict(report_row)
        report["followups"] = [_followup_to_dict(row) for row in followup_rows]
        return report

    def list_reports(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, task_id, title, created_at, completeness_json "
                "FROM reports ORDER BY created_at DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "task_id": row["task_id"],
                "title": row["title"],
                "created_at": row["created_at"],
                "completeness": _loads(row["completeness_json"]),
            }
            for row in rows
        ]

    # -- followups -----------------------------------------------------------

    def add_followup(
        self,
        *,
        followup_id: str,
        report_id: str,
        role: str,
        text: str,
        evidence: Any | None = None,
    ) -> dict[str, Any]:
        created_at = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO followups "
                "(id, report_id, role, text, evidence_json, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    followup_id,
                    report_id,
                    role,
                    text,
                    _dumps(evidence) if evidence is not None else None,
                    created_at,
                ),
            )
            self._conn.commit()
        return {
            "id": followup_id,
            "report_id": report_id,
            "role": role,
            "text": text,
            "evidence": evidence,
            "created_at": created_at,
        }

    def list_followups(self, report_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM followups WHERE report_id = ? ORDER BY created_at ASC, id ASC",
                (report_id,),
            ).fetchall()
        return [_followup_to_dict(row) for row in rows]

    # -- overrides -----------------------------------------------------------

    def get_overrides(self) -> dict[str, bool]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT agent_id, enabled FROM agent_overrides"
            ).fetchall()
        return {row["agent_id"]: bool(row["enabled"]) for row in rows}

    def set_override(self, agent_id: str, enabled: bool) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO agent_overrides (agent_id, enabled) VALUES (?, ?) "
                "ON CONFLICT(agent_id) DO UPDATE SET enabled = excluded.enabled",
                (agent_id, 1 if enabled else 0),
            )
            self._conn.commit()

    # -- local single-user profile ------------------------------------------

    def get_user_profile(self, profile_id: str) -> dict[str, Any] | None:
        """Read the canonical profile JSON.

        ``profile_id`` is ``local-default-user`` in the hackathon MVP. It is
        deliberately not identity data and can later be replaced by a login ID.
        """

        with self._lock:
            row = self._conn.execute(
                "SELECT profile_json FROM user_profiles WHERE profile_id = ?",
                (profile_id,),
            ).fetchone()
        return _loads(row["profile_json"]) if row is not None else None

    def save_user_profile(
        self,
        *,
        profile_id: str,
        profile_version: int,
        onboarding_completed: bool,
        profile: dict[str, Any],
        created_at: str,
        updated_at: str,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO user_profiles "
                "(profile_id, profile_version, onboarding_completed, "
                "profile_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(profile_id) DO UPDATE SET "
                "profile_version = excluded.profile_version, "
                "onboarding_completed = excluded.onboarding_completed, "
                "profile_json = excluded.profile_json, "
                "created_at = excluded.created_at, "
                "updated_at = excluded.updated_at",
                (
                    profile_id,
                    profile_version,
                    1 if onboarding_completed else 0,
                    _dumps(profile),
                    created_at,
                    updated_at,
                ),
            )
            self._conn.commit()

    def delete_user_profile(self, profile_id: str) -> bool:
        with self._lock:
            cursor = self._conn.execute(
                "DELETE FROM user_profiles WHERE profile_id = ?",
                (profile_id,),
            )
            self._conn.commit()
        return cursor.rowcount > 0

    # -- overview ------------------------------------------------------------

    def overview_counts(self) -> dict[str, Any]:
        with self._lock:
            total_tasks = int(
                self._conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
            )
            completed_tasks = int(
                self._conn.execute(
                    "SELECT COUNT(*) AS c FROM tasks WHERE status = 'completed'"
                ).fetchone()["c"]
            )
            report_count = int(
                self._conn.execute("SELECT COUNT(*) AS c FROM reports").fetchone()["c"]
            )
            completeness_rows = self._conn.execute(
                "SELECT completeness_json FROM reports"
            ).fetchall()
        ratios: list[float] = []
        for row in completeness_rows:
            completeness = _loads(row["completeness_json"])
            if isinstance(completeness, dict):
                ratio = completeness.get("completion_ratio")
                if isinstance(ratio, (int, float)):
                    ratios.append(float(ratio))
        average_completion = round(sum(ratios) / len(ratios), 4) if ratios else 0.0
        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "report_count": report_count,
            "average_completion": average_completion,
        }


def _task_to_dict(
    task_row: sqlite3.Row,
    event_rows: list[sqlite3.Row],
) -> dict[str, Any]:
    return {
        "id": task_row["id"],
        "prompt": task_row["prompt"],
        "status": task_row["status"],
        "created_at": task_row["created_at"],
        "plan": _loads(task_row["plan_json"]),
        "aggregation": _loads(task_row["aggregation_json"]),
        "final_answer": task_row["final_answer"],
        "duration_ms": task_row["duration_ms"],
        "events": [_event_to_dict(row) for row in event_rows],
    }


def _event_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "seq": row["seq"],
        "type": row["type"],
        "agent": row["agent"],
        "step_id": row["step_id"],
        "message": row["message"],
        "metadata": _loads(row["metadata_json"]) or {},
        "ts": row["ts"],
    }


def _report_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "title": row["title"],
        "created_at": row["created_at"],
        "completeness": _loads(row["completeness_json"]),
        "aggregation": _loads(row["aggregation_json"]),
    }


def _followup_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "report_id": row["report_id"],
        "role": row["role"],
        "text": row["text"],
        "evidence": _loads(row["evidence_json"]) or [],
        "created_at": row["created_at"],
    }


_default_store: Store | None = None
_default_store_lock = threading.Lock()


def get_store() -> Store:
    """Return the process-wide store singleton (path from ALPHAOS_DB or default)."""

    global _default_store
    with _default_store_lock:
        if _default_store is None:
            _default_store = Store()
        return _default_store


def reset_store_for_tests(db_path: str | Path | None = None) -> Store:
    """Replace the singleton with a fresh store; used by tests for isolation."""

    global _default_store
    with _default_store_lock:
        if _default_store is not None:
            _default_store.close()
        _default_store = Store(db_path)
        return _default_store
