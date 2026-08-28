"""Host-owned execution adapter behind the installable sandbox Connector.

The Pi Package only registers the model-facing Tool.  This service keeps the
actual process boundary, Trace verification, and Eval persistence inside PAW.
The connector exposes only checked-in registry entries and derives each Agent
entrypoint from its bounded suite directory; it is not a generic
arbitrary-command API.
"""

from __future__ import annotations

import os
import shlex
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from uuid import uuid4

from .agent_workspace import WorkspaceHarness
from .eval_run_store import EvalRunStore
from .sandbox_run_store import SandboxRunStore
from .trace_runtime import build_sandbox_run
from .trace_store import TraceStore
from .vertical_agent_harness import load_builtin_manifests
from .vertical_agent_process import run_external_vertical_agent_process


ProcessRunner = Callable[..., Mapping[str, object]]


class VerticalSandboxConnectorService:
    """Run allowlisted vertical suites behind a session-scoped gateway."""

    def __init__(
        self,
        *,
        eval_store: EvalRunStore,
        trace_store: TraceStore,
        sandbox_store: SandboxRunStore | None = None,
        workspace_harness: WorkspaceHarness | None = None,
        process_runner: ProcessRunner = run_external_vertical_agent_process,
        repository_root: str | Path | None = None,
        now_ms: Callable[[], int] | None = None,
    ) -> None:
        self.eval_store = eval_store
        self.trace_store = trace_store
        self.sandbox_store = sandbox_store or SandboxRunStore(trace_store.db_path)
        self.workspace_harness = workspace_harness or WorkspaceHarness()
        self.process_runner = process_runner
        self.repository_root = (
            Path(repository_root).resolve(strict=True)
            if repository_root is not None
            else Path(__file__).resolve().parents[1]
        )
        self._now_ms = now_ms or (lambda: int(time.time() * 1_000))

    def execute(
        self,
        session_id: str,
        operation: str,
        args: Mapping[str, object],
    ) -> dict[str, object]:
        if operation == "status":
            return self.status()
        if operation != "run":
            raise ValueError("unsupported vertical sandbox operation")
        return self.run(session_id, args)

    def status(self) -> dict[str, object]:
        manifests = load_builtin_manifests()
        executable = self.workspace_harness.sandbox_executable
        return {
            "summary": "垂直 Agent Sandbox Connector 已连接到 PAW Host",
            "executionOwner": "paw_host",
            "connectorOwner": "pi_package",
            "backend": "macos-seatbelt",
            "backendExecutablePresent": executable.is_file()
            and os.access(executable, os.X_OK),
            "network": "blocked",
            "productionWriteBlocked": True,
            "supportedSuites": [
                {
                    "suiteId": suite_id,
                    "suiteRevision": str(manifest["suiteRevision"]),
                    "displayName": str(manifest["displayName"]),
                }
                for suite_id, manifest in sorted(manifests.items())
            ],
        }

    def run(
        self,
        session_id: str,
        args: Mapping[str, object],
    ) -> dict[str, object]:
        suite_id = str(args.get("suiteId") or "").strip()
        manifests = load_builtin_manifests()
        manifest = manifests.get(suite_id)
        if manifest is None:
            raise ValueError("vertical sandbox suite is not registered")
        suite_revision = str(args.get("suiteRevision") or manifest["suiteRevision"])
        if suite_revision != str(manifest["suiteRevision"]):
            raise ValueError("vertical sandbox suite revision does not match the registered manifest")

        agent_path = self._agent_path(suite_id)
        fixtures = manifest.get("fixtures")
        if not isinstance(fixtures, list) or not fixtures or not isinstance(fixtures[0], Mapping):
            raise ValueError("registered vertical sandbox suite has no fixture")
        fixture_id = str(fixtures[0].get("fixtureId") or "").strip()
        if not fixture_id:
            raise ValueError("registered vertical sandbox suite fixture has no id")

        started_at_ms = self._now_ms()
        # The wall clock is useful for display but is not an identity source:
        # two calls in the same millisecond must still create distinct
        # SandboxRuns (and distinct child-process run ids).
        run_id = f"connector-{started_at_ms}-{uuid4().hex}"
        internal_session = {
            "id": f"vertical-sandbox:{session_id or 'session'}",
            "mode": "coordinator",
            "workspaceRoots": [str(self.repository_root)],
            "executionMode": "read_only",
            "toolProfileVersion": "subagent-readonly-v1",
        }
        result = self.process_runner(
            manifest,
            session=internal_session,
            source_session_id=session_id,
            command=(
                "PYTHONPATH=. python3 "
                f"{shlex.quote(str(agent_path.relative_to(self.repository_root)))} "
                f"--run-id {shlex.quote(run_id)}"
            ),
            cwd=self.repository_root,
            eval_store=self.eval_store,
            trace_store=self.trace_store,
            workspace_harness=self.workspace_harness,
            fixture_id=fixture_id,
            timeout_seconds=30,
            allow_network=False,
            now_ms=started_at_ms,
        )
        trace_id = str(result["traceId"])
        eval_run_id = str(result["evalRunId"])
        receipt = result.get("processReceipt")
        if not isinstance(receipt, Mapping):
            raise ValueError("vertical Agent process returned no execution receipt")
        eval_run = self.eval_store.get(eval_run_id)
        if not isinstance(eval_run, Mapping):
            raise ValueError("vertical Agent evaluation was not persisted")

        sandbox_run = build_sandbox_run(
            sandbox_run_id=f"sandbox:{suite_id}:{run_id}",
            workspace_root=str(self.repository_root),
            app_id=suite_id,
            workspace_binding_id=f"workspace-binding:vertical-sandbox:{suite_id}",
            mutation_mode="read_only",
            network="blocked",
            trace_ids=[trace_id],
            eval_run_ids=[eval_run_id],
            now_ms=self._now_ms(),
        ).to_dict()
        sandbox_run = self.persist(sandbox_run)
        return {
            "summary": f"{suite_id} 已在 PAW Host 管理的本地沙箱中完成 Trace/Eval 闭环",
            "suite": {
                "suiteId": suite_id,
                "suiteRevision": suite_revision,
            },
            "sandboxRun": sandbox_run,
            "sandboxRunId": str(sandbox_run["sandboxRunId"]),
            "traceId": trace_id,
            "evalRunId": eval_run_id,
            "metrics": dict(eval_run.get("metrics") or {}),
            "verification": dict(result.get("verification") or {}),
            "execution": {
                "backend": "macos-seatbelt",
                "exitCode": int(receipt.get("exitCode") or 0),
                "durationMs": int(receipt.get("durationMs") or 0),
                "timedOut": receipt.get("timedOut") is True,
                "outputLimited": receipt.get("outputLimited") is True,
                "networkAllowed": receipt.get("networkAllowed") is True,
                "sourceReadOnly": receipt.get("sourceReadOnly") is True,
            },
            "authority": {
                "connector": "pi_package",
                "execution": "paw_host",
                "trace": "TraceStore",
                "evaluation": "EvalRunStore",
            },
        }

    def persist(self, sandbox_run: Mapping[str, object]) -> dict[str, object]:
        """Persist the Host-owned SandboxRun without adding connector authority."""

        return self.sandbox_store.persist(sandbox_run)

    def _agent_path(self, suite_id: str) -> Path:
        examples_root = (
            self.repository_root / "examples" / "vertical_agents"
        ).resolve(strict=True)
        candidate = (examples_root / suite_id / "agent.py").resolve(strict=False)
        if examples_root not in candidate.parents or not candidate.is_file():
            raise ValueError("registered vertical sandbox suite has no executable Agent")
        return candidate
