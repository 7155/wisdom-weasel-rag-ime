from __future__ import annotations

import json
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .memory_optimizer_models import BlockedCandidate, ContextFrame, OptimizedMemoryCandidate, OptimizerResult, RawRetrievalHit
from .models import AgentContextInjection, InputEvent, InputSuggestion, MemoryAction
from .suggestion_compiler import RankedMemory, SuggestionCompiler
from .text_utils import compact_whitespace, now_ms, overlap_terms


@dataclass(frozen=True)
class CoreMemory:
    memory_id: str
    text: str
    source_ref: str
    score: float
    reason: str
    evidence_preview: str
    project: str = ""
    tags: tuple[str, ...] = ()
    source_event_id: str | None = None
    created_at_ms: int | None = None
    state: dict[str, Any] = field(default_factory=dict)


class CoreClient(Protocol):
    """Boundary to the shared RAG/memory core.

    The input method owns adapter behavior. The core owns persistence, FTS/vector
    retrieval, ranking, and governance state.
    """

    def record_event(self, event: InputEvent) -> str:
        ...

    def suggest_for_input(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        app: str = "",
        top_k: int = 5,
        context_group_id: str = "",
        context_group_level: str = "app",
        context_group_parent_ids: tuple[str, ...] = (),
    ) -> list[InputSuggestion]:
        ...

    def apply_action(self, action: MemoryAction) -> MemoryAction:
        ...

    def build_agent_context(self, *, project: str, query: str, top_k: int = 5) -> AgentContextInjection:
        ...

    def recent_input_context(self, *, project: str = "", limit: int = 6, max_chars: int = 420) -> str:
        ...

    def optimize_memory_candidates(
        self,
        context: ContextFrame,
        base_hits: list[RawRetrievalHit],
        *,
        top_k: int,
        latency_budget_ms: int,
    ) -> OptimizerResult:
        ...

    def record_memory_feedback(self, event: dict[str, Any]) -> None:
        ...

    def explain_memory_candidate(self, candidate_id: str, context_hash: str | None = None) -> dict[str, Any] | None:
        ...


class JsonCommandCoreClient:
    """Adapter for a future shared-core JSON command.

    The command receives one JSON request on stdin and returns one JSON response
    on stdout. This keeps the IME repo language-neutral and avoids importing PI
    runtime internals directly.
    """

    def __init__(self, command: list[str], *, cwd: str | Path | None = None, timeout_s: float = 5.0):
        if not command:
            raise ValueError("command must not be empty")
        self.command = command
        self.cwd = str(cwd) if cwd else None
        self.timeout_s = timeout_s

    def record_event(self, event: InputEvent) -> str:
        if event.privacy_disposition != "allowed":
            return f"skipped:privacy_{event.privacy_disposition}"
        payload = self._request("record_event", {"event": asdict(event)})
        return str(payload["event_id"])

    def suggest_for_input(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        app: str = "",
        top_k: int = 5,
        context_group_id: str = "",
        context_group_level: str = "app",
        context_group_parent_ids: tuple[str, ...] = (),
    ) -> list[InputSuggestion]:
        payload = self._request(
            "suggest_for_input",
            {
                "current_input": current_input,
                "recent_context": recent_context,
                "project": project,
                "app": app,
                "top_k": top_k,
                "context_group_id": context_group_id,
                "context_group_level": context_group_level,
                "context_group_parent_ids": list(context_group_parent_ids),
            },
        )
        return [_suggestion_from_json(item) for item in payload.get("suggestions", [])]

    def apply_action(self, action: MemoryAction) -> MemoryAction:
        payload = self._request("apply_action", {"action": asdict(action)})
        return _memory_action_from_json(payload.get("action", asdict(action)))

    def build_agent_context(self, *, project: str, query: str, top_k: int = 5) -> AgentContextInjection:
        payload = self._request("build_agent_context", {"project": project, "query": query, "top_k": top_k})
        return _agent_context_from_json(payload["injection"])

    def recent_input_context(self, *, project: str = "", limit: int = 6, max_chars: int = 420) -> str:
        try:
            payload = self._request(
                "recent_input_context",
                {"project": project, "limit": limit, "max_chars": max_chars},
            )
        except RuntimeError:
            return ""
        return str(payload.get("context") or payload.get("history_context") or "")

    def optimize_memory_candidates(
        self,
        context: ContextFrame,
        base_hits: list[RawRetrievalHit],
        *,
        top_k: int,
        latency_budget_ms: int,
    ) -> OptimizerResult:
        try:
            payload = self._request(
                "optimize_memory_candidates",
                {
                    "context": asdict(context),
                    "base_hits": [asdict(item) for item in base_hits],
                    "top_k": top_k,
                    "latency_budget_ms": latency_budget_ms,
                },
            )
        except RuntimeError:
            return OptimizerResult(candidates=[], blocked=[], trace_id=None, latency_ms=0.0, degraded=True, warnings=["json-core-unavailable"])
        return OptimizerResult(
            candidates=[
                OptimizedMemoryCandidate(
                    id=str(item["id"]),
                    text=str(item["text"]),
                    source_type=str(item["source_type"]),
                    lane=str(item["lane"]),
                    score=float(item["score"]),
                    confidence=float(item["confidence"]),
                    evidence_preview=str(item.get("evidence_preview") or ""),
                    memory_atom_ids=list(item.get("memory_atom_ids") or []),
                    tags=list(item.get("tags") or []),
                    debug_features=dict(item.get("debug_features") or {}),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in payload.get("candidates", [])
            ],
            blocked=[
                BlockedCandidate(
                    id=str(item.get("id") or ""),
                    reason=str(item.get("reason") or ""),
                    metadata=dict(item.get("metadata") or {}),
                )
                for item in payload.get("blocked", [])
                if isinstance(item, dict)
            ],
            trace_id=str(payload.get("trace_id") or "") or None,
            latency_ms=float(payload.get("latency_ms") or 0.0),
            degraded=bool(payload.get("degraded")),
            warnings=list(payload.get("warnings") or []),
        )

    def record_memory_feedback(self, event: dict[str, Any]) -> None:
        try:
            self._request("record_memory_feedback", {"event": event})
        except RuntimeError:
            return None

    def explain_memory_candidate(self, candidate_id: str, context_hash: str | None = None) -> dict[str, Any] | None:
        try:
            payload = self._request("explain_memory_candidate", {"candidate_id": candidate_id, "context_hash": context_hash})
        except RuntimeError:
            return None
        return dict(payload)

    def _request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        request = {"method": method, "params": params}
        proc = subprocess.run(
            self.command,
            input=json.dumps(request, ensure_ascii=False),
            text=True,
            capture_output=True,
            cwd=self.cwd,
            timeout=self.timeout_s,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(f"core command failed ({proc.returncode}): {proc.stderr.strip()}")
        try:
            response = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"core command returned invalid JSON: {proc.stdout[:500]}") from exc
        if response.get("error"):
            raise RuntimeError(str(response["error"]))
        return dict(response.get("result", response))


class FixtureCoreClient:
    """Deterministic local fixture for adapter/UI acceptance tests.

    This is not the production memory store. It exists so the input method
    adapter can be developed while the shared core is being extracted elsewhere.
    """

    def __init__(self, memories: list[CoreMemory] | None = None):
        self.memories = list(memories or default_fixture_memories())
        self.compiler = SuggestionCompiler()
        self.actions: list[MemoryAction] = []
        self.events: list[InputEvent] = []
        self._state: dict[str, dict[str, Any]] = {
            memory.memory_id: {
                "accepted_count": 0,
                "skipped_count": 0,
                "pinned": False,
                "downranked": 0,
                "deleted": False,
            }
            for memory in self.memories
        }

    def record_event(self, event: InputEvent) -> str:
        if event.privacy_disposition != "allowed":
            return f"skipped:privacy_{event.privacy_disposition}"
        event_id = event.event_id if event.event_id is not None else len(self.events) + 1
        stored = InputEvent(
            event_id=event_id,
            created_at_ms=event.created_at_ms or now_ms(),
            source=event.source,
            committed_text=event.committed_text,
            privacy_disposition=event.privacy_disposition,
            recent_context=event.recent_context,
            preedit=event.preedit,
            schema_id=event.schema_id,
            app=event.app,
            project=event.project,
            candidate_rank=event.candidate_rank,
            provider_name=event.provider_name,
            tags=event.tags,
            context_group_id=event.context_group_id,
            context_group_level=event.context_group_level,
            capture_metadata=dict(event.capture_metadata),
        )
        self.events.append(stored)
        return f"event:{event_id}"

    def suggest_for_input(
        self,
        *,
        current_input: str,
        recent_context: str = "",
        project: str = "",
        app: str = "",
        top_k: int = 5,
    ) -> list[InputSuggestion]:
        query = compact_whitespace(f"{recent_context} {current_input}")
        ranked = sorted(
            (
                self._score_memory(memory, query, project)
                for memory in self.memories
                if not self._state[memory.memory_id]["deleted"]
            ),
            key=lambda item: item[0],
            reverse=True,
        )
        ranked_memories = [
            RankedMemory(memory=memory, score=score, rank=rank)
            for rank, (score, memory) in enumerate(ranked[:top_k], start=1)
        ]
        return self.compiler.compile(ranked_memories)

    def apply_action(self, action: MemoryAction) -> MemoryAction:
        memory_id = action.memory_id
        if memory_id not in self._state:
            raise ValueError(f"unknown memory_id: {memory_id}")
        state = self._state[memory_id]
        if action.action_type in ("accepted", "accept"):
            state["accepted_count"] += 1
        elif action.action_type in ("skipped", "skip"):
            state["skipped_count"] += 1
        elif action.action_type == "pin":
            state["pinned"] = True
        elif action.action_type == "unpin":
            state["pinned"] = False
        elif action.action_type == "downrank":
            state["downranked"] += 1
        elif action.action_type in ("delete", "hide"):
            state["deleted"] = True
        elif action.action_type == "restore":
            state["deleted"] = False
        else:
            raise ValueError(f"unsupported action_type: {action.action_type}")

        stored = MemoryAction(
            action_id=action.action_id or len(self.actions) + 1,
            created_at_ms=action.created_at_ms or now_ms(),
            memory_id=memory_id,
            action_type=action.action_type,
            query=action.query,
            suggestion_id=action.suggestion_id,
            metadata=action.metadata,
        )
        self.actions.append(stored)
        return stored

    def build_agent_context(self, *, project: str, query: str, top_k: int = 5) -> AgentContextInjection:
        suggestions = self.suggest_for_input(current_input=query, project=project, top_k=top_k)
        lines = [
            "PROJECT_MEMORY_BLOCK",
            f"- 当前项目: {project or 'wisdom-weasel-rag-ime'}",
            "- 用户偏好: local-first, 不默认上传个人输入历史, 候选必须可选择/可治理。",
            "- 最近决策: RAG/记忆底层由 shared core 负责, 输入法仓库只做 adapter 和展示。",
            "- 禁止事项: 不把 GPT/Claude 作为默认预测链路; 不在 Mac MVP 阶段做微调。",
            "- 推荐下一步: 复用 shared core 的检索和治理 API, 完成候选化和 evidence preview 验收。",
        ]
        for index, suggestion in enumerate(suggestions[:top_k], start=1):
            lines.append(f"  {index}. {suggestion.surface_text} | {suggestion.evidence_preview}")
        return AgentContextInjection(
            project=project,
            generated_at_ms=now_ms(),
            block="\n".join(lines),
            source_event_ids=tuple(int(item.source_event_id or 0) for item in suggestions),
            query=query,
        )

    def optimize_memory_candidates(
        self,
        context: ContextFrame,
        base_hits: list[RawRetrievalHit],
        *,
        top_k: int,
        latency_budget_ms: int,
    ) -> OptimizerResult:
        del context, latency_budget_ms
        candidates = [
            OptimizedMemoryCandidate(
                id=hit.id,
                text=hit.text,
                source_type="memory" if hit.source == "stable_memory" else "rag",
                lane="memory" if hit.source == "stable_memory" else "rag",
                score=hit.score,
                confidence=max(0.0, min(1.0, hit.score)),
                evidence_preview=hit.evidence,
                memory_atom_ids=[hit.memory_atom_id] if hit.memory_atom_id else [],
                tags=list(hit.metadata.get("tags") or []),
                debug_features={},
                metadata=dict(hit.metadata),
            )
            for hit in base_hits[: max(1, top_k)]
        ]
        return OptimizerResult(candidates=candidates, blocked=[], trace_id=None, latency_ms=0.0, degraded=False, warnings=[])

    def record_memory_feedback(self, event: dict[str, Any]) -> None:
        del event
        return None

    def explain_memory_candidate(self, candidate_id: str, context_hash: str | None = None) -> dict[str, Any] | None:
        del context_hash
        memory = next((item for item in self.memories if item.memory_id == candidate_id), None)
        if memory is None:
            return None
        return {"memory_id": memory.memory_id, "text": memory.text, "tags": list(memory.tags)}

    def recent_input_context(self, *, project: str = "", limit: int = 6, max_chars: int = 420) -> str:
        if limit <= 0 or max_chars <= 0:
            return ""
        rows = [
            event
            for event in self.events
            if not project or event.project in (project, "")
        ][-limit:]
        snippets: list[str] = []
        for event in rows:
            text = compact_whitespace(event.committed_text)
            if not text:
                continue
            context = compact_whitespace(event.recent_context)
            preedit = compact_whitespace(event.preedit)
            parts = [text]
            if context and context != text:
                parts.append(f"context: {context}")
            if preedit and preedit != text:
                parts.append(f"preedit: {preedit}")
            snippets.append(" | ".join(parts))
        return _tail_chars(compact_whitespace(" / ".join(snippets)), max_chars)

    def _score_memory(self, memory: CoreMemory, query: str, project: str) -> tuple[float, CoreMemory]:
        terms = overlap_terms(query, f"{memory.text} {memory.evidence_preview} {' '.join(memory.tags)}")
        state = self._state[memory.memory_id]
        score = memory.score + min(1.5, len(terms) * 0.35)
        if project and memory.project == project:
            score += 0.5
        if state["pinned"]:
            score += 2.0
        score += state["accepted_count"] * 0.6
        score -= state["skipped_count"] * 0.3
        score -= state["downranked"] * 0.85
        return score, memory


def default_fixture_memories() -> list[CoreMemory]:
    return [
        CoreMemory(
            memory_id="mem-interview-loop",
            source_event_id="101",
            text="高频实时场景里的个人记忆系统",
            source_ref="memory:101#interview",
            score=0.88,
            reason="fixture:interview",
            evidence_preview="RAG 输入法不是普通文档问答, 而是在输入过程中用用户选择来校准记忆源。",
            project="wisdom-weasel-rag-ime",
            tags=("interview", "local-first", "feedback-loop"),
        ),
        CoreMemory(
            memory_id="mem-local-privacy",
            source_event_id="102",
            text="默认本地完成, 不上传个人输入历史",
            source_ref="memory:102#privacy",
            score=0.86,
            reason="fixture:privacy",
            evidence_preview="输入法会经过大量私人内容, 云端 GPT 只能作为离线质量上限, 不能作为默认链路。",
            project="wisdom-weasel-rag-ime",
            tags=("privacy", "local-first"),
        ),
        CoreMemory(
            memory_id="mem-feedback",
            source_event_id="103",
            text="用户选择候选会反向校准记忆源",
            source_ref="memory:103#feedback",
            score=0.83,
            reason="fixture:governance",
            evidence_preview="accepted、skipped、pin、downrank、delete 都要回写 shared core 的治理状态。",
            project="wisdom-weasel-rag-ime",
            tags=("feedback", "governance"),
        ),
        CoreMemory(
            memory_id="mem-fts-first",
            source_event_id="201",
            text="先用 FTS5 证明召回收益",
            source_ref="memory:201#fts",
            score=0.9,
            reason="fixture:fts5",
            evidence_preview="第一版用 SQLite/FTS5-only MVP, embedding 和本地 reranker 后置。",
            project="wisdom-weasel-rag-ime",
            tags=("fts5", "ranking", "mvp"),
        ),
        CoreMemory(
            memory_id="mem-rerank-later",
            source_event_id="202",
            text="排序先用规则分数, 再接轻量 reranker",
            source_ref="memory:202#ranking",
            score=0.84,
            reason="fixture:ranking",
            evidence_preview="score = lexical_score + recency + accepted_count - skipped_penalty。",
            project="wisdom-weasel-rag-ime",
            tags=("ranking", "reranker"),
        ),
        CoreMemory(
            memory_id="mem-structure-plan",
            source_event_id="203",
            text="第一步先验证 FTS5, 第二步接本地 embedding, 第三步再做 reranker。",
            source_ref="memory:203#structure",
            score=0.78,
            reason="fixture:structure",
            evidence_preview="输入法默认候选必须快, 段落生成和小模型能力应放到用户主动展开后。",
            project="wisdom-weasel-rag-ime",
            tags=("structure", "technical-plan"),
        ),
        CoreMemory(
            memory_id="mem-agent-block",
            source_event_id="301",
            text="生成 PROJECT_MEMORY_BLOCK",
            source_ref="memory:301#agent-hook",
            score=0.91,
            reason="fixture:agent-hook",
            evidence_preview="Agent 首次运行时注入当前项目、用户偏好、最近决策、禁止事项和推荐下一步。",
            project="wisdom-weasel-rag-ime",
            tags=("agent-hook", "context"),
        ),
        CoreMemory(
            memory_id="mem-agent-align",
            source_event_id="302",
            text="把本地记忆注入 Agent 首次运行上下文",
            source_ref="memory:302#agent-align",
            score=0.87,
            reason="fixture:agent-hook",
            evidence_preview="RAG 输入法能解决 Agent 与用户背景信息对齐问题, 语音输入很难稳定携带这些历史背景。",
            project="wisdom-weasel-rag-ime",
            tags=("agent-hook", "vibe-coding"),
        ),
        CoreMemory(
            memory_id="mem-agent-context-contract",
            source_event_id="303",
            text="Agent 首次运行上下文需要项目目标和禁止事项",
            source_ref="memory:303#agent-context-contract",
            score=0.85,
            reason="fixture:agent-hook",
            evidence_preview="首次运行上下文应包含项目目标、用户偏好、禁止云端实时预测和下一步任务。",
            project="wisdom-weasel-rag-ime",
            tags=("agent-hook", "context", "project-memory"),
        ),
    ]


def _suggestion_from_json(payload: dict[str, Any]) -> InputSuggestion:
    return InputSuggestion(
        suggestion_id=str(payload.get("suggestionId") or payload.get("suggestion_id")),
        surface_text=str(payload.get("surfaceText") or payload.get("surface_text")),
        suggestion_type=str(payload.get("suggestionType") or payload.get("suggestion_type")),
        source_event_id=_optional_int(payload.get("sourceEventId") or payload.get("source_event_id")),
        evidence_preview=str(payload.get("evidencePreview") or payload.get("evidence_preview") or ""),
        confidence=float(payload.get("confidence") or 0),
        actions=tuple(payload.get("actions") or ("commit", "expand", "pin", "downrank", "delete")),
        expanded_evidence=str(payload.get("expandedEvidence") or payload.get("expanded_evidence") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def _memory_action_from_json(payload: dict[str, Any]) -> MemoryAction:
    return MemoryAction(
        action_id=_optional_int(payload.get("actionId") or payload.get("action_id")),
        created_at_ms=int(payload.get("createdAtMs") or payload.get("created_at_ms") or now_ms()),
        memory_id=str(payload.get("memoryId") or payload.get("memory_id")),
        action_type=str(payload.get("actionType") or payload.get("action_type")),
        query=str(payload.get("query") or ""),
        suggestion_id=str(payload.get("suggestionId") or payload.get("suggestion_id") or ""),
        metadata=dict(payload.get("metadata") or {}),
    )


def _agent_context_from_json(payload: dict[str, Any]) -> AgentContextInjection:
    return AgentContextInjection(
        project=str(payload.get("project") or payload.get("namespace") or ""),
        generated_at_ms=int(payload.get("generatedAtMs") or payload.get("generated_at_ms") or now_ms()),
        block=str(payload.get("block") or payload.get("text") or ""),
        source_event_ids=tuple(int(item) for item in payload.get("sourceEventIds", payload.get("source_event_ids", []))),
        query=str(payload.get("query") or ""),
    )


def _optional_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _tail_chars(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[-max_chars:]
