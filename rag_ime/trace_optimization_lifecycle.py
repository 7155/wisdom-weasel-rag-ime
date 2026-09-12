"""Own the durable run lifecycle for one Trace optimization candidate."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from pathlib import Path
from threading import RLock

from .agent_lab.trials import TERMINAL_STATES
from .db import sqlite_connection
from .trace_optimization_execution import SCENE_ID as COMMAND_SCENE_ID
from .trace_optimization_pi import SCENE_ID as PI_SCENE_ID
from .trace_optimization_versions import digest, now_ms


class TraceOptimizationRunCoordinator:
    """Coordinate paired baseline/candidate trials behind one state seam."""

    def __init__(
        self,
        db_path: str | Path,
        *,
        versions,
        candidates,
        start_trial: Callable[[Mapping[str, object]], Mapping[str, object]],
        cancel_trial: Callable[[str], Mapping[str, object]],
        read_trial: Callable[[str], Mapping[str, object]],
        record_outcome: Callable[[Mapping[str, object], Mapping[str, object]], None],
    ) -> None:
        self.db_path = Path(db_path)
        self.versions = versions
        self.candidates = candidates
        self.start_trial = start_trial
        self.cancel_trial = cancel_trial
        self.read_trial = read_trial
        self.record_outcome = record_outcome
        self._mutation_lock = RLock()

    def start(self, candidate: Mapping[str, object], request_id: str) -> None:
        with self._mutation_lock:
            self._start(candidate, request_id)

    def _start(self, candidate: Mapping[str, object], request_id: str) -> None:
        with sqlite_connection(self.db_path) as conn:
            previous = conn.execute(
                "SELECT candidate_id FROM trace_optimization_run_pairs WHERE request_id=?",
                (request_id,),
            ).fetchone()
        if previous:
            if previous[0] != candidate["candidateId"]:
                raise ValueError("run request identity conflict")
            return

        candidate = self.candidates.get_candidate(candidate["candidateId"])
        if "run_candidate" not in candidate["availableActions"]:
            raise ValueError("candidate has no registered execution path")
        plan = self.versions.get_plan(candidate["comparisonContract"]["caseSetRef"])
        scene_id = (
            PI_SCENE_ID
            if plan["plan"].get("executionKind") == "pi_session"
            else COMMAND_SCENE_ID
        )
        ids: dict[str, str] = {}
        try:
            for role in ("baseline", "candidate"):
                response = self.start_trial(
                    {
                        "clientRequestId": "trace-run:" + digest([request_id, role]),
                        "sceneId": scene_id,
                        "spec": {"candidateId": candidate["candidateId"], "role": role},
                    }
                )
                ids[role] = str(response["job"]["jobId"])
        except Exception:
            for job_id in ids.values():
                self.cancel_trial(job_id)
            raise

        with sqlite_connection(self.db_path) as conn:
            previous = conn.execute(
                "SELECT candidate_id,baseline_job_id,candidate_job_id "
                "FROM trace_optimization_run_pairs WHERE request_id=?",
                (request_id,),
            ).fetchone()
            if previous and tuple(previous) != (
                candidate["candidateId"], ids["baseline"], ids["candidate"]
            ):
                raise ValueError("run request identity conflict")
            conn.execute(
                "INSERT OR IGNORE INTO trace_optimization_run_pairs "
                "VALUES(?,?,?,?,?,?,?)",
                (
                    request_id,
                    candidate["reportId"],
                    candidate["candidateId"],
                    ids["baseline"],
                    ids["candidate"],
                    "",
                    now_ms(),
                ),
            )

    def jobs(self, report_id: str) -> list[dict[str, object]]:
        with sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                "SELECT candidate_id,baseline_job_id,candidate_job_id,comparison_id "
                "FROM trace_optimization_run_pairs WHERE report_id=? "
                "ORDER BY created_at_ms DESC LIMIT 50",
                (report_id,),
            ).fetchall()
        return [
            {
                "candidateId": row[0],
                "baseline": self.read_trial(row[1])["job"],
                "candidate": self.read_trial(row[2])["job"],
                "comparisonId": row[3],
            }
            for row in rows
        ]

    def reconcile(self, report_id: str) -> None:
        for row in self.jobs(report_id):
            if row["comparisonId"]:
                comparison = self.candidates.get_comparison(row["comparisonId"])
                if comparison:
                    self.record_outcome(
                        self.candidates.get_candidate(row["candidateId"]),
                        comparison,
                    )
                continue
            if (
                row["baseline"]["state"] not in TERMINAL_STATES
                or row["candidate"]["state"] not in TERMINAL_STATES
            ):
                continue
            candidate = self.candidates.get_candidate(row["candidateId"])
            comparison = self.candidates.record_validation(
                row["candidateId"],
                client_request_id="trace-comparison:"
                + digest([row["baseline"]["jobId"], row["candidate"]["jobId"]]),
                baseline_trial_id=row["baseline"]["jobId"],
                candidate_trial_id=row["candidate"]["jobId"],
            )
            with sqlite_connection(self.db_path) as conn:
                conn.execute(
                    "UPDATE trace_optimization_run_pairs SET comparison_id=? "
                    "WHERE baseline_job_id=? AND candidate_job_id=?",
                    (
                        comparison["comparisonId"],
                        row["baseline"]["jobId"],
                        row["candidate"]["jobId"],
                    ),
                )
            self.record_outcome(candidate, comparison)
