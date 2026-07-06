from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import tempfile
import time
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Iterable

from .predictor import (
    PREDICTION_REQUEST_GENERIC,
    PREDICTION_REQUEST_NO_INPUT,
    PREDICTION_REQUEST_PINYIN_CONSTRAINED,
    PREDICTION_REQUEST_RIME_REORDER,
    normalize_prediction_request_type,
    normalized_rime_candidate_texts,
    parse_ime_prediction_candidates,
    parse_prediction_candidates,
)
from .text_utils import compact_whitespace


SYSTEM_PROMPT = (
    "你是本地中文输入法的续写候选模型。根据已上屏文本预测光标后最可能继续输入的中文短语。"
    "只返回 JSON 字符串数组, 不要解释, 不要编号, 不要输出拼音, 不要输出思考过程。"
    "每个候选必须是后文增量, 不能复述已上屏文本、提示词、格式说明或固定示例。"
    "上下文太短或不确定时可以返回空数组。"
    "不要输出泛词或模板词: 根据、基于、和、测试、分析、验证、假设、或者、现在、目前、当前、然后、模型相关表达、调试流程。"
)

STREAM_FIRST_SYSTEM_PROMPT = (
    "补全用户正在写的中文句子。"
    "只输出光标后的具体中文内容，5到16个字，不要解释。"
    "不要只输出“下一步”或“接下来”这种过渡词。"
)

SPACE_LIST_SYSTEM_PROMPT = (
    "你是一个智能中文输入法，请根据上下文预测接下来最可能出现的短候选。"
    "只返回候选词或短语，不要解释，不要编号，不要 JSON。"
    "候选之间用单个空格分隔，按可能性从高到低排列。"
    "每个候选必须是能直接接在光标后的后文增量，不要复述上下文。"
    "不要只输出下一步、接下来这种过渡词；英文专名只可作为上下文对象，不要单独当候选。"
)

LOGITS_SYSTEM_PROMPT = (
    "你是本地中文输入法的续写候选模型。根据已上屏文本直接给出最可能接在光标后的中文短语。"
    "不要解释, 不要编号, 不要 JSON, 不要拼音, 不要思考过程。"
    "不要输出泛词或固定示例: 根据、基于、和、测试、分析、验证、假设、或者、现在、目前、当前、然后、模型相关表达、调试流程。"
)

QWEN_NON_THINKING_ASSISTANT_PREFIX = "<|im_start|>assistant\n<think>\n\n</think>\n\n"
GENERATION_STOP_MARKERS = (
    "<|im_end|>",
    "<|endoftext|>",
    "<|im_start|>",
    "\nHuman:",
    "\nAssistant:",
    "Human:",
    "Assistant:",
)

_CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LOW_VALUE_LOGITS_CANDIDATES = {
    "测试",
    "测试流程",
    "分析",
    "分析问题",
    "验证",
    "并且",
    "但是",
    "同时",
    "或者",
    "基于",
    "根据",
    "生成",
    "假设",
    "然后",
    "现在",
    "目前",
    "当前",
    "当前问题",
    "当前流程",
    "当前拼音或参考候选",
    "模型相关表达",
    "调试流程",
    "方案",
    "上屏",
    "上屏文字",
    "已上屏",
    "已上屏文本",
    "已上屏上下文",
    "下一步",
    "接下来",
    "下一句",
    "下一句：",
    "接龙",
    "把流程跑通",
    "接入本地",
    "接入本地记忆",
    "验证 LLM 候选",
    "验证LLM候选",
    "预测流程完成",
    "部署 RAG 组件",
    "部署RAG组件",
    "继续预测",
    "预测流程",
    "的",
    "了",
    "和",
    "是",
}


@dataclass(frozen=True)
class MlxPredictorServerConfig:
    host: str = "127.0.0.1"
    port: int = 8767
    model: str = ""
    max_tokens: int = 8
    temperature: float = 0.15
    top_p: float = 0.85
    prompt_cache: bool = False
    prompt_cache_max_kv_size: int = 0


@dataclass(frozen=True)
class _ContinuationBranchSpec:
    label: str
    temperature: float
    max_tokens: int
    max_candidate_chars: int


class MlxLmEngine:
    """Resident MLX-LM engine for the IME model lane.

    This module intentionally imports MLX-LM lazily so the rest of RAG-IME can
    run on machines where MLX is not installed. The loaded process owns model
    memory; the IME talks to it over a tiny local HTTP protocol.
    """

    def __init__(
        self,
        model_id: str,
        *,
        enable_prompt_cache: bool = False,
        prompt_cache_max_kv_size: int = 0,
    ):
        if not model_id:
            raise RuntimeError("MLX predictor requires --model or RAG_IME_MLX_MODEL")
        try:
            from mlx_lm import load  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on local Mac setup
            raise RuntimeError("Install mlx-lm before running mlx-predictor-server") from exc

        self.model_id = model_id
        self.model_info = _inspect_local_mlx_model(model_id)
        self.model, self.tokenizer = load(model_id)
        self._base_completion_mode = _is_base_completion_model(model_id, self.model_info)
        self._prompt_cache = _PromptCacheState(
            enabled=bool(enable_prompt_cache) and not self._base_completion_mode,
            stable_prefix=self._stable_prompt_prefix(),
            max_kv_size=max(0, int(prompt_cache_max_kv_size)),
        )
        if self._prompt_cache.enabled:
            self._prepare_prompt_cache()

    def health(self) -> dict[str, Any]:
        prompt_cache = self.prompt_cache_status()
        return {
            "ok": True,
            "provider": "mlx-lm",
            "model": self.model_id,
            "modelLoaded": True,
            "modelInfo": self.model_info,
            "promptCache": prompt_cache,
            "capabilities": {
                "streaming": True,
                "residentModel": True,
                "promptCache": _prompt_cache_used_for_generation(prompt_cache),
                "textOnlyModel": bool(self.model_info.get("textOnly")),
                "seededPromptReplay": True,
                "kvFork": False,
                "sequenceFork": False,
                "batchCandidates": True,
                "logitsTopK": True,
                "continuationBranches": True,
                "serverTiming": True,
                "baseCompletion": self._base_completion_mode,
            },
            "promptMode": "base-completion" if self._base_completion_mode else "chat-json",
        }

    def prompt_cache_status(self) -> dict[str, Any]:
        return self._prompt_cache.to_payload()

    def predict(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
        stream_first_candidate: bool = False,
        request_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        resolved_request_type = normalize_prediction_request_type(request_type)
        rime_candidate_tuple = normalized_rime_candidate_texts(rime_candidates)
        if self._base_completion_mode:
            raw_text = "".join(
                self.stream_text(
                    current_input=current_input,
                    recent_context=recent_context,
                    max_candidates=max_candidates,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    request_type=resolved_request_type,
                    rime_candidates=rime_candidate_tuple,
                    stream_first_candidate=stream_first_candidate,
                    request_metadata=request_metadata,
                )
            )
            total_ms = int((time.perf_counter() - started) * 1000)
            candidates = self.parse_candidates_from_raw(
                raw_text,
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
            )
            return {
                "ok": True,
                "model": self.model_id,
                "rawText": raw_text,
                "candidates": candidates,
                "candidateMode": "base-completion",
                "requestType": resolved_request_type,
                "totalMs": total_ms,
                "promptCache": self.prompt_cache_status(),
                "timing": {
                    "candidateMode": "base-completion",
                    "logitsMs": 0,
                    "fallbackJson": False,
                    "requestType": resolved_request_type,
                },
                "requestMeta": dict(request_metadata or {}),
            }

        logits_candidates = self.predict_next_token_logits(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
            request_type=resolved_request_type,
            rime_candidates=rime_candidate_tuple,
            request_metadata=request_metadata,
        )
        if _logits_candidates_are_ime_quality(logits_candidates["candidates"], max_candidates=max_candidates):
            total_ms = int((time.perf_counter() - started) * 1000)
            return {
                "ok": True,
                "model": self.model_id,
                "rawText": " ".join(logits_candidates["candidates"]),
                "candidates": logits_candidates["candidates"],
                "candidateScores": logits_candidates["candidateScores"],
                "candidateMode": "next-token-logits",
                "requestType": resolved_request_type,
                "totalMs": total_ms,
                "promptCache": self.prompt_cache_status(),
                "timing": {
                    "candidateMode": "next-token-logits",
                    "logitsMs": logits_candidates["elapsedMs"],
                    "fallbackJson": False,
                    "requestType": resolved_request_type,
                },
                "requestMeta": dict(request_metadata or {}),
            }

        if resolved_request_type == PREDICTION_REQUEST_NO_INPUT and not stream_first_candidate:
            seeded_replay_payload = self.predict_no_input_seeded_prompt_replay(
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                started=started,
                logits_candidates=logits_candidates,
                request_metadata=request_metadata,
            )
            if seeded_replay_payload is not None and seeded_replay_payload.get("candidates"):
                return seeded_replay_payload
            branch_payload = self.predict_no_input_continuation_branches(
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                started=started,
                logits_elapsed_ms=logits_candidates.get("elapsedMs", 0),
                logits_quality_reason=logits_candidates.get("qualityReason") or "logits_candidates_not_phrase_quality",
                request_metadata=request_metadata,
            )
            return branch_payload

        raw_text = "".join(
            self.stream_text(
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
                max_tokens=max_tokens,
                temperature=temperature,
                top_p=top_p,
                request_type=resolved_request_type,
                rime_candidates=rime_candidate_tuple,
                stream_first_candidate=stream_first_candidate,
                request_metadata=request_metadata,
            )
        )
        total_ms = int((time.perf_counter() - started) * 1000)
        candidates = parse_ime_prediction_candidates(
            raw_text,
            max_candidates=max_candidates,
            current_input=current_input,
            recent_context=recent_context,
            request_type=resolved_request_type,
            rime_candidates=rime_candidate_tuple,
        )
        return {
            "ok": True,
            "model": self.model_id,
            "rawText": raw_text,
            "candidates": candidates,
            "candidateMode": "json-generation",
            "requestType": resolved_request_type,
            "totalMs": total_ms,
            "promptCache": self.prompt_cache_status(),
            "timing": {
                "candidateMode": "json-generation",
                "logitsMs": logits_candidates.get("elapsedMs", 0),
                "fallbackJson": True,
                "fallbackReason": logits_candidates.get("qualityReason") or "logits_candidates_not_phrase_quality",
                "requestType": resolved_request_type,
            },
            "requestMeta": dict(request_metadata or {}),
        }

    def predict_no_input_continuation_branches(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
        started: float,
        logits_elapsed_ms: int,
        logits_quality_reason: str,
        request_metadata: dict[str, Any] | None = None,
        ) -> dict[str, Any]:
        max_items = max(1, int(max_candidates))
        branch_specs = _continuation_branch_specs(temperature=temperature, max_tokens=max_tokens)
        raw_texts: list[str] = []
        candidates: list[str] = []
        seen: set[str] = set()
        branch_timings: list[dict[str, Any]] = []
        list_started = time.perf_counter()
        list_max_tokens = max(16, min(64, max(int(max_tokens), max_items * 8)))
        list_raw_text = "".join(
            self._stream_text_with_generate_step(
                prompt=_build_no_input_space_list_prompt(
                    recent_context=recent_context,
                    max_candidates=max_items,
                ),
                max_tokens=list_max_tokens,
                temperature=max(0.05, min(float(temperature), 0.18)),
                top_p=top_p,
            )
        )
        raw_texts.append(list_raw_text)
        list_candidates = _space_list_continuation_candidates(
            list_raw_text,
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_items,
        )
        branch_timings.append(
            {
                "label": "space-list",
                "temperature": max(0.05, min(float(temperature), 0.18)),
                "maxTokens": list_max_tokens,
                "elapsedMs": int((time.perf_counter() - list_started) * 1000),
                "candidates": list_candidates,
            }
        )
        for candidate in list_candidates:
            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
            if len(candidates) >= max_items:
                break

        for branch in branch_specs:
            if len(candidates) >= max_items:
                break
            branch_started = time.perf_counter()
            raw_text = "".join(
                self.stream_text(
                    current_input=current_input,
                    recent_context=recent_context,
                    max_candidates=max_candidates,
                    max_tokens=branch.max_tokens,
                    temperature=branch.temperature,
                    top_p=top_p,
                    request_type=PREDICTION_REQUEST_NO_INPUT,
                    rime_candidates=(),
                    stream_first_candidate=True,
                    request_metadata=request_metadata,
                )
            )
            raw_texts.append(raw_text)
            branch_candidates = _branch_continuation_candidates(
                raw_text,
                current_input=current_input,
                recent_context=recent_context,
                max_candidate_chars=branch.max_candidate_chars,
                max_candidates=max_items - len(candidates),
            )
            branch_timings.append(
                {
                    "label": branch.label,
                    "temperature": branch.temperature,
                    "maxTokens": branch.max_tokens,
                    "elapsedMs": int((time.perf_counter() - branch_started) * 1000),
                    "candidates": branch_candidates,
                    "candidate": branch_candidates[0] if branch_candidates else "",
                }
            )
            for candidate in branch_candidates:
                if candidate and not _looks_like_meta_completion_candidate(candidate) and candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
                if len(candidates) >= max_items:
                    break
        if max_items >= 5 and len(candidates) == 1:
            expanded_candidates = _expand_continuation_candidates_from_model_output(
                candidates,
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_items,
            )
            for candidate in expanded_candidates:
                if candidate and candidate not in seen:
                    seen.add(candidate)
                    candidates.append(candidate)
                if len(candidates) >= max_items:
                    break
            if expanded_candidates:
                branch_timings.append(
                    {
                        "label": "model-output-splits",
                        "temperature": temperature,
                        "maxTokens": 0,
                        "elapsedMs": 0,
                        "candidates": expanded_candidates,
                    }
                )
        candidate_scores = _continuation_branch_candidate_scores(
            candidates[:max_items],
            branch_timings=branch_timings,
        )
        total_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": True,
            "model": self.model_id,
            "rawText": "\n".join(raw_texts),
            "candidates": candidates[:max_items],
            "candidateScores": candidate_scores,
            "candidateMode": "continuation-branches",
            "requestType": PREDICTION_REQUEST_NO_INPUT,
            "totalMs": total_ms,
            "promptCache": self.prompt_cache_status(),
            "timing": {
                "candidateMode": "continuation-branches",
                "logitsMs": int(logits_elapsed_ms or 0),
                "fallbackJson": False,
                "fallbackReason": logits_quality_reason,
                "requestType": PREDICTION_REQUEST_NO_INPUT,
                "branches": branch_timings,
            },
            "requestMeta": dict(request_metadata or {}),
        }

    def predict_no_input_seeded_prompt_replay(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
        started: float,
        logits_candidates: dict[str, Any],
        request_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        seeds = _seed_replay_specs_from_logits(
            logits_candidates.get("candidateScores"),
            max_seeds=max(1, min(3, int(max_candidates))),
        )
        if not seeds:
            return None
        raw_texts: list[str] = []
        candidates: list[str] = []
        seen: set[str] = set()
        branch_timings: list[dict[str, Any]] = []
        per_seed_max_tokens = max(8, min(24, int(max_tokens)))
        replay_temperature = max(0.05, min(float(temperature), 0.18))
        branch_count = len(seeds)
        for branch_rank, seed in enumerate(seeds, start=1):
            if len(candidates) >= max(1, int(max_candidates)):
                break
            seed_text = str(seed.get("text") or "")
            if not seed_text:
                continue
            branch_started = time.perf_counter()
            raw_text = "".join(
                self._stream_text_with_generate_step(
                    prompt=_build_seeded_replay_prompt(recent_context=recent_context, seed_text=seed_text),
                    max_tokens=per_seed_max_tokens,
                    temperature=replay_temperature,
                    top_p=top_p,
                )
            )
            raw_texts.append(f"{seed_text}{raw_text}")
            candidate = _seeded_replay_candidate(
                seed_text=seed_text,
                raw_text=raw_text,
                current_input=current_input,
                recent_context=recent_context,
                max_candidate_chars=max(12, min(24, per_seed_max_tokens * 2)),
            )
            branch_candidates = [candidate] if candidate else []
            branch_timings.append(
                {
                    "label": f"seed:{seed_text}",
                    "branchRank": branch_rank,
                    "branchCount": branch_count,
                    "seedText": seed_text,
                    "seedTokenId": seed.get("tokenId"),
                    "logprob": seed.get("logprob"),
                    "probability": seed.get("probability"),
                    "maxTokens": per_seed_max_tokens,
                    "elapsedMs": int((time.perf_counter() - branch_started) * 1000),
                    "candidates": branch_candidates,
                }
            )
            if candidate and candidate not in seen:
                seen.add(candidate)
                candidates.append(candidate)
        if not candidates:
            return None
        total_ms = int((time.perf_counter() - started) * 1000)
        return {
            "ok": True,
            "model": self.model_id,
            "rawText": "\n".join(raw_texts),
            "candidates": candidates[: max(1, int(max_candidates))],
            "candidateScores": _seeded_prompt_replay_candidate_scores(
                candidates[: max(1, int(max_candidates))],
                branch_timings=branch_timings,
            ),
            "candidateMode": "seeded-prompt-replay",
            "requestType": PREDICTION_REQUEST_NO_INPUT,
            "totalMs": total_ms,
            "promptCache": self.prompt_cache_status(),
            "timing": {
                "candidateMode": "seeded-prompt-replay",
                "logitsMs": int(logits_candidates.get("elapsedMs") or 0),
                "fallbackJson": False,
                "fallbackReason": "top_logits_seed_replay",
                "requestType": PREDICTION_REQUEST_NO_INPUT,
                "branches": branch_timings,
            },
            "requestMeta": dict(request_metadata or {}),
        }

    def predict_next_token_logits(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
        request_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _ = request_metadata
        started = time.perf_counter()
        try:
            from mlx_lm.generate import generate_step  # type: ignore
            import mlx.core as mx  # type: ignore

            prompt = self._build_logits_prompt(
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
                request_type=request_type,
                rime_candidates=rime_candidates,
            )
            tokens = self.tokenizer.encode(prompt)
            token, logprobs = next(generate_step(mx.array(tokens), self.model, max_tokens=1))
            candidate_scores = self._candidate_scores_from_logprobs(
                logprobs,
                max_candidates=max_candidates,
                scan_limit=max(64, max_candidates * 24),
            )
            return {
                "candidates": [item["text"] for item in candidate_scores],
                "candidateScores": candidate_scores,
                "sampledTokenId": _token_to_int(token),
                "elapsedMs": int((time.perf_counter() - started) * 1000),
            }
        except Exception as exc:  # pragma: no cover - depends on local MLX-LM internals
            return {
                "candidates": [],
                "candidateScores": [],
                "error": exc.__class__.__name__,
                "elapsedMs": int((time.perf_counter() - started) * 1000),
            }

    def _candidate_scores_from_logprobs(
        self,
        logprobs: Any,
        *,
        max_candidates: int,
        scan_limit: int,
    ) -> list[dict[str, Any]]:
        result: list[dict[str, Any]] = []
        seen: set[str] = set()
        for token_id in _top_logprob_indices(logprobs, limit=max(1, int(scan_limit))):
            text = _normalize_logits_candidate_text(self.tokenizer.decode([int(token_id)]))
            if not text or text in seen:
                continue
            if text in _LOW_VALUE_LOGITS_CANDIDATES:
                continue
            if len(text) > 8 or not _CJK_RE.search(text):
                continue
            seen.add(text)
            logprob = _logprob_at(logprobs, int(token_id))
            item: dict[str, Any] = {
                "text": text,
                "tokenId": int(token_id),
            }
            if logprob is not None:
                item["logprob"] = logprob
                item["probability"] = max(0.0, min(1.0, math.exp(max(-60.0, min(0.0, logprob)))))
            result.append(item)
            if len(result) >= max(1, min(10, int(max_candidates))):
                break
        return result

    def stream_text(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
        stream_first_candidate: bool = False,
        request_metadata: dict[str, Any] | None = None,
    ) -> Iterable[str]:
        _ = request_metadata
        prompt = self._build_prompt(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
            request_type=request_type,
            rime_candidates=rime_candidates,
            stream_first_candidate=stream_first_candidate,
        )
        if self._prompt_cache.ready_for_generation() and not stream_first_candidate and not self._base_completion_mode:
            try:
                for text in self._stream_text_with_prompt_cache(
                    current_input=current_input,
                    recent_context=recent_context,
                    max_candidates=max_candidates,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    top_p=top_p,
                    request_type=request_type,
                    rime_candidates=rime_candidates,
                    stream_first_candidate=stream_first_candidate,
                ):
                    yield text
                return
            except Exception as exc:  # pragma: no cover - depends on local MLX-LM internals
                self._prompt_cache.miss_count += 1
                self._prompt_cache.error = f"cached_generation:{exc.__class__.__name__}"

        if self._prompt_cache.enabled:
            self._prompt_cache.miss_count += 1
        for text in self._stream_text_with_generate_step(
            prompt=prompt,
            max_tokens=max(1, min(64, int(max_tokens))),
            temperature=float(temperature),
            top_p=float(top_p),
        ):
            yield text

    def _stream_text_with_prompt_cache(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        max_tokens: int,
        temperature: float,
        top_p: float,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
        stream_first_candidate: bool = False,
    ) -> Iterable[str]:
        from mlx_lm.generate import generate_step  # type: ignore
        from mlx_lm.models.cache import load_prompt_cache  # type: ignore
        from mlx_lm.sample_utils import make_sampler  # type: ignore
        import mlx.core as mx  # type: ignore

        cache = load_prompt_cache(str(self._prompt_cache.cache_file))
        dynamic_prompt = self._dynamic_prompt_suffix(
            current_input=current_input,
            recent_context=recent_context,
            max_candidates=max_candidates,
            request_type=request_type,
            rime_candidates=rime_candidates,
            stream_first_candidate=stream_first_candidate,
        )
        self._prompt_cache.used_for_generation = True
        self._prompt_cache.hit_count += 1
        self._prompt_cache.error = ""
        for text in self._stream_text_with_generate_step(
            prompt=dynamic_prompt,
            max_tokens=max(1, min(64, int(max_tokens))),
            temperature=float(temperature),
            top_p=float(top_p),
            prompt_cache=cache,
        ):
            yield text

    def _stream_text_with_generate_step(
        self,
        *,
        prompt: str,
        max_tokens: int,
        temperature: float,
        top_p: float,
        prompt_cache: Any | None = None,
    ) -> Iterable[str]:
        from mlx_lm.generate import generate_step  # type: ignore
        from mlx_lm.sample_utils import make_sampler  # type: ignore
        import mlx.core as mx  # type: ignore

        tokens = self.tokenizer.encode(prompt)
        sampler = make_sampler(temp=max(0.0, float(temperature)), top_p=max(0.0, float(top_p)))
        emitted = ""
        generated_tokens: list[int] = []
        for token, _logprobs in generate_step(
            mx.array(tokens),
            self.model,
            max_tokens=max(1, min(64, int(max_tokens))),
            prompt_cache=prompt_cache,
            sampler=sampler,
        ):
            token_id = _token_to_int(token)
            if _token_is_eos(self.tokenizer, token_id):
                break
            generated_tokens.append(token_id)
            decoded = self.tokenizer.decode(generated_tokens)
            if isinstance(decoded, bytes):
                decoded = decoded.decode("utf-8", errors="ignore")
            if not isinstance(decoded, str):
                decoded = str(decoded)
            decoded, reached_stop = _visible_generation_text(decoded)
            if "\ufffd" in decoded:
                continue
            delta = decoded[len(emitted) :] if decoded.startswith(emitted) else decoded
            emitted = decoded
            if delta:
                yield delta
            if reached_stop:
                break

    def _stable_prompt_prefix(self, *, stream_first_candidate: bool = False) -> str:
        if self._base_completion_mode:
            return ""
        prompt = STREAM_FIRST_SYSTEM_PROMPT if stream_first_candidate else SYSTEM_PROMPT
        return f"<|im_start|>system\n{prompt}<|im_end|>\n<|im_start|>user\n"

    def _dynamic_prompt_suffix(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
        stream_first_candidate: bool = False,
    ) -> str:
        if self._base_completion_mode:
            return _build_base_completion_prompt(current_input=current_input, recent_context=recent_context)
        return (
            f"{_build_mlx_dynamic_prompt(current_input=current_input, recent_context=recent_context, max_candidates=max_candidates, request_type=request_type, rime_candidates=rime_candidates, stream_first_candidate=stream_first_candidate)}"
            "<|im_end|>\n"
            f"{QWEN_NON_THINKING_ASSISTANT_PREFIX}"
        )

    def _build_prompt(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
        stream_first_candidate: bool = False,
    ) -> str:
        if self._base_completion_mode:
            return _build_base_completion_prompt(current_input=current_input, recent_context=recent_context)
        return (
            f"{self._stable_prompt_prefix(stream_first_candidate=stream_first_candidate)}"
            f"{self._dynamic_prompt_suffix(current_input=current_input, recent_context=recent_context, max_candidates=max_candidates, request_type=request_type, rime_candidates=rime_candidates, stream_first_candidate=stream_first_candidate)}"
        )

    def _build_logits_prompt(
        self,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
    ) -> str:
        if self._base_completion_mode:
            return _build_base_completion_prompt(current_input=current_input, recent_context=recent_context)
        resolved_request_type = normalize_prediction_request_type(request_type)
        rime_line = _rime_candidates_prompt_line(rime_candidates)
        return (
            f"<|im_start|>system\n{LOGITS_SYSTEM_PROMPT}<|im_end|>\n"
            "<|im_start|>user\n"
            f"请求类型: {resolved_request_type}\n"
            f"上下文: {recent_context}\n"
            f"当前输入: {current_input}\n"
            f"{rime_line}"
            f"模式说明: {_request_type_prompt_instruction(resolved_request_type)}\n"
            f"给出 {max_candidates} 个候选中最可能的第一个候选, 直接从候选文本开始。"
            "<|im_end|>\n"
            f"{QWEN_NON_THINKING_ASSISTANT_PREFIX}"
        )

    def _prepare_prompt_cache(self) -> None:
        started = time.perf_counter()
        try:
            from mlx_lm.generate import generate_step  # type: ignore
            from mlx_lm.models.cache import make_prompt_cache, save_prompt_cache  # type: ignore
            import mlx.core as mx  # type: ignore

            tokens = self.tokenizer.encode(self._prompt_cache.stable_prefix)
            self._prompt_cache.stable_prefix_tokens = len(tokens)
            kwargs: dict[str, Any] = {}
            if self._prompt_cache.max_kv_size > 0:
                kwargs["max_kv_size"] = self._prompt_cache.max_kv_size
            cache = make_prompt_cache(self.model, **kwargs)
            for _ in generate_step(mx.array(tokens), self.model, max_tokens=1, prompt_cache=cache):
                break
            handle = tempfile.NamedTemporaryFile(prefix="rag-ime-mlx-prefix-", suffix=".safetensors", delete=False)
            handle.close()
            save_prompt_cache(
                handle.name,
                cache,
                metadata={
                    "model": self.model_id,
                    "stablePrefixHash": self._prompt_cache.stable_prefix_hash(),
                },
            )
            self._prompt_cache.cache_file = handle.name
            self._prompt_cache.prepared = True
            self._prompt_cache.error = ""
        except Exception as exc:  # pragma: no cover - depends on local MLX-LM internals
            self._prompt_cache.prepared = False
            self._prompt_cache.error = exc.__class__.__name__
        finally:
            self._prompt_cache.prepare_ms = int((time.perf_counter() - started) * 1000)

    def parse_candidates_from_raw(
        self,
        raw_text: str,
        *,
        current_input: str,
        recent_context: str,
        max_candidates: int,
        request_type: str = PREDICTION_REQUEST_GENERIC,
        rime_candidates: tuple[str, ...] = (),
    ) -> list[str]:
        if self._base_completion_mode:
            return _parse_base_completion_candidates(
                raw_text,
                current_input=current_input,
                recent_context=recent_context,
                max_candidates=max_candidates,
            )
        return parse_ime_prediction_candidates(
            raw_text,
            max_candidates=max_candidates,
            current_input=current_input,
            recent_context=recent_context,
            request_type=request_type,
            rime_candidates=rime_candidates,
        )


def make_mlx_predictor_handler(engine: MlxLmEngine):
    class MlxPredictorHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - stdlib API
            if self.path == "/health":
                self._send_json(engine.health())
                return
            if self.path == "/v1/models":
                self._send_json({"data": [{"id": engine.model_id, "owned_by": "local-mlx"}]})
                return
            self.send_error(404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib API
            if self.path not in {"/predict", "/predict-stream"}:
                self.send_error(404)
                return
            try:
                payload = self._read_json()
            except json.JSONDecodeError:
                self.send_error(400, "invalid JSON")
                return
            request = _normalize_prediction_request(payload, default_model=engine.model_id)
            if self.path == "/predict-stream":
                self._send_stream(engine, request)
                return
            result = engine.predict(**request)
            self._send_json(result)

        def _read_json(self) -> dict[str, Any]:
            length = int(self.headers.get("Content-Length") or "0")
            if length <= 0:
                return {}
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            return payload if isinstance(payload, dict) else {}

        def _send_stream(self, engine: MlxLmEngine, request: dict[str, Any]) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.end_headers()
            started = time.perf_counter()
            raw_text = ""
            for text in engine.stream_text(**request):
                raw_text += text
                self._write_json_line({"delta": text, "elapsedMs": int((time.perf_counter() - started) * 1000)})
            parse_candidates = getattr(engine, "parse_candidates_from_raw", None)
            if callable(parse_candidates):
                candidates = parse_candidates(
                    raw_text,
                    current_input=str(request.get("current_input") or ""),
                    recent_context=str(request.get("recent_context") or ""),
                    max_candidates=int(request["max_candidates"]),
                    request_type=normalize_prediction_request_type(request.get("request_type")),
                    rime_candidates=normalized_rime_candidate_texts(request.get("rime_candidates")),
                )
            else:
                candidates = parse_prediction_candidates(raw_text, max_candidates=int(request["max_candidates"]))
            self._write_json_line(
                {
                    "done": True,
                    "rawText": raw_text,
                    "candidates": candidates,
                    "requestType": normalize_prediction_request_type(request.get("request_type")),
                    "totalMs": int((time.perf_counter() - started) * 1000),
                    "promptCache": engine.prompt_cache_status(),
                    "requestMeta": dict(request.get("request_metadata") or {}),
                }
            )

        def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_json_line(self, payload: dict[str, Any]) -> None:
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n")
            self.wfile.flush()

        def log_message(self, fmt: str, *args: object) -> None:
            return

    return MlxPredictorHandler


def serve_mlx_predictor(config: MlxPredictorServerConfig) -> None:
    engine = MlxLmEngine(
        config.model,
        enable_prompt_cache=config.prompt_cache,
        prompt_cache_max_kv_size=config.prompt_cache_max_kv_size,
    )
    server = ThreadingHTTPServer((config.host, config.port), make_mlx_predictor_handler(engine))
    print(
        json.dumps(
            {
                "schemaVersion": "rag-ime.mlx-predictor-server.v1",
                "listening": f"http://{config.host}:{config.port}",
                "model": config.model,
                "maxTokens": config.max_tokens,
                "promptCache": engine.prompt_cache_status(),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


def _normalize_prediction_request(payload: dict[str, Any], *, default_model: str) -> dict[str, Any]:
    _ = str(payload.get("model") or default_model)
    return {
        "current_input": compact_whitespace(str(payload.get("currentInput") or "")),
        "recent_context": compact_whitespace(str(payload.get("recentContext") or ""))[-420:],
        "max_candidates": max(1, min(10, _int_payload(payload.get("maxCandidates"), 3))),
        "max_tokens": max(1, min(64, _int_payload(payload.get("maxTokens"), 8))),
        "temperature": _float_payload(payload.get("temperature"), 0.15),
        "top_p": _float_payload(payload.get("topP"), 0.85),
        "request_type": normalize_prediction_request_type(payload.get("requestType")),
        "rime_candidates": normalized_rime_candidate_texts(payload.get("rimeCandidates")),
        "stream_first_candidate": bool(payload.get("streamFirstCandidate")),
        "request_metadata": _request_metadata_from_payload(payload),
    }


def _inspect_local_mlx_model(model_id: str) -> dict[str, Any]:
    path = Path(model_id).expanduser()
    info: dict[str, Any] = {
        "modelId": model_id,
        "localPath": path.exists(),
        "textOnly": False,
        "hasVisionConfig": False,
        "configPresent": False,
        "modelFileCount": 0,
        "diskBytes": 0,
    }
    if not path.exists():
        info["reason"] = "non_local_model_id"
        return info

    model_dir = path if path.is_dir() else path.parent
    info["modelDir"] = str(model_dir)
    model_files = sorted(model_dir.glob("*.safetensors"))
    info["modelFileCount"] = len(model_files)
    info["diskBytes"] = sum(file.stat().st_size for file in model_files if file.is_file())

    config_path = model_dir / "config.json"
    if not config_path.exists():
        info["reason"] = "missing_config_json"
        return info

    info["configPresent"] = True
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        info["reason"] = f"invalid_config_json:{exc.__class__.__name__}"
        return info

    text_config = config.get("text_config") if isinstance(config.get("text_config"), dict) else {}
    source = text_config if text_config else config
    has_vision_config = isinstance(config.get("vision_config"), dict)
    info.update(
        {
            "architecture": _first_string(config.get("architectures")),
            "modelType": str(config.get("model_type") or source.get("model_type") or ""),
            "textModelType": str(text_config.get("model_type") or ""),
            "hasVisionConfig": has_vision_config,
            "textOnly": not has_vision_config,
            "vocabSize": _optional_int(source.get("vocab_size")),
            "hiddenSize": _optional_int(source.get("hidden_size")),
            "numHiddenLayers": _optional_int(source.get("num_hidden_layers")),
            "intermediateSize": _optional_int(source.get("intermediate_size")),
            "numAttentionHeads": _optional_int(source.get("num_attention_heads")),
            "numKeyValueHeads": _optional_int(source.get("num_key_value_heads")),
            "quantization": _quantization_summary(config),
        }
    )
    tokenizer_config_path = model_dir / "tokenizer_config.json"
    if tokenizer_config_path.exists():
        try:
            tokenizer_config = json.loads(tokenizer_config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            tokenizer_config = {}
        chat_template = str(tokenizer_config.get("chat_template") or "")
        info["hasChatTemplate"] = bool(chat_template)
        info["chatTemplateSupportsThinking"] = "enable_thinking" in chat_template or "thinking" in chat_template.lower()
    else:
        info["hasChatTemplate"] = False
        info["chatTemplateSupportsThinking"] = False
    return info


def _first_string(value: Any) -> str:
    if isinstance(value, list) and value:
        return str(value[0])
    return str(value or "")


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _quantization_summary(config: dict[str, Any]) -> dict[str, Any]:
    quantization = config.get("quantization")
    if not isinstance(quantization, dict):
        quantization = config.get("quantization_config")
    if not isinstance(quantization, dict):
        return {}
    return {
        key: value
        for key, value in quantization.items()
        if isinstance(value, (str, int, float, bool)) or value is None
    }


def _is_base_completion_model(model_id: str, model_info: dict[str, Any]) -> bool:
    normalized_id = str(model_id).lower()
    path_parts = {part.lower() for part in Path(model_id).parts}
    if "base" in normalized_id or any(part.endswith("-base") or part == "base" for part in path_parts):
        return True
    if model_info.get("hasChatTemplate"):
        return False
    architecture = str(model_info.get("architecture") or "").lower()
    model_type = str(model_info.get("modelType") or "").lower()
    if "instruct" in normalized_id or "chat" in normalized_id:
        return False
    return architecture == "qwen3forcausallm" and model_type == "qwen3"


def _build_mlx_prompt(
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
    request_type: str = PREDICTION_REQUEST_GENERIC,
    rime_candidates: tuple[str, ...] = (),
    stream_first_candidate: bool = False,
) -> str:
    return (
        f"{_stable_prompt_prefix()}"
        f"{_build_mlx_dynamic_prompt(current_input=current_input, recent_context=recent_context, max_candidates=max_candidates, request_type=request_type, rime_candidates=rime_candidates, stream_first_candidate=stream_first_candidate)}"
    )


def _stable_prompt_prefix() -> str:
    return f"{SYSTEM_PROMPT}\n"


def _build_mlx_dynamic_prompt(
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
    request_type: str = PREDICTION_REQUEST_GENERIC,
    rime_candidates: tuple[str, ...] = (),
    stream_first_candidate: bool = False,
) -> str:
    resolved_request_type = normalize_prediction_request_type(request_type)
    rime_candidate_tuple = normalized_rime_candidate_texts(rime_candidates)
    rime_line = _rime_candidates_prompt_line(rime_candidate_tuple)
    mode_instruction = _request_type_prompt_instruction(resolved_request_type)
    constraint_line = _request_type_candidate_constraint(resolved_request_type, rime_candidate_tuple)
    if stream_first_candidate:
        if resolved_request_type == PREDICTION_REQUEST_NO_INPUT:
            return (
                f"已上屏文本: {recent_context}\n"
                "光标后内容:"
            )
        return (
            f"请求类型: {resolved_request_type}\n"
            f"已上屏上下文: {recent_context}\n"
            f"当前拼音或参考候选: {current_input}\n"
            f"{rime_line}"
            f"模式说明: {mode_instruction}\n"
            f"{constraint_line}"
            "答案写用户下一步最可能输入的具体短语正文。"
        )
    return (
        f"请求类型: {resolved_request_type}\n"
        f"已上屏上下文: {recent_context}\n"
        f"当前拼音或参考候选: {current_input}\n"
        f"{rime_line}"
        f"模式说明: {mode_instruction}\n"
        f"{constraint_line}"
        "要求:\n"
        "- 输出能直接接在已上屏上下文后面的候选, 每个 2 到 16 个汉字为主。\n"
        "- 不要复述、改写、重排已上屏上下文本身; 候选必须是后文增量。\n"
        "- 当前输入如果是拼音、英文串或 Rime 候选列表, 只把它当作约束, 不要复述这些词。\n"
        "- 拼音约束模式下, 候选语义要符合上下文, 同时尽量满足当前拼音或首字母。\n"
        "- Rime 重排模式下, 优先从 Rime 候选里挑更符合上下文的词, 必要时只补充极短预测。\n"
        "- 候选要像用户下一步真的会输入的内容; 不要默认假设用户在写项目、输入法、RAG 或模型调试, 除非上下文明确出现这些主题。\n"
        "- 不要输出单字、语气词、连接词、泛词、重复词。\n"
        f"输出 {max_candidates} 个候选 JSON 数组。"
    )


def _request_type_prompt_instruction(request_type: str) -> str:
    resolved = normalize_prediction_request_type(request_type)
    if resolved == PREDICTION_REQUEST_NO_INPUT:
        return "用户刚上屏了一段文字, 现在需要预测后文接龙, 不要做拼音转汉字。"
    if resolved == PREDICTION_REQUEST_PINYIN_CONSTRAINED:
        return "用户正在用拼音约束预测方向, 候选必须尽量匹配当前拼音或首字母约束。"
    if resolved == PREDICTION_REQUEST_RIME_REORDER:
        return "当前已有 Rime/Wanxiang 候选, 只在候选之间选择或补充极短候选, 不要自由发挥长句。"
    return "根据上下文给出输入法候选。"


def _request_type_candidate_constraint(request_type: str, rime_candidates: tuple[str, ...]) -> str:
    resolved = normalize_prediction_request_type(request_type)
    if resolved == PREDICTION_REQUEST_PINYIN_CONSTRAINED and rime_candidates:
        return f"硬约束: 每个候选必须以这些 Rime 候选之一开头: {' / '.join(rime_candidates[:8])}。\n"
    if resolved == PREDICTION_REQUEST_RIME_REORDER and rime_candidates:
        return "硬约束: 只能输出 Rime候选 原文或它们的序号, 不要创造新词。\n"
    return ""


def _rime_candidates_prompt_line(rime_candidates: tuple[str, ...] | list[str] | object) -> str:
    candidates = normalized_rime_candidate_texts(rime_candidates)
    if not candidates:
        return ""
    return f"Rime候选: {' / '.join(candidates[:8])}\n"


def _build_base_completion_prompt(*, current_input: str, recent_context: str) -> str:
    sections = _split_prediction_context(recent_context)
    current = compact_whitespace(sections["current"] or _strip_prediction_context_labels(recent_context))
    query = compact_whitespace(current_input)
    if current:
        query = _remove_context_overlap(query, current)
    if query and (_looks_like_candidate_constraint_query(query) or _looks_like_prompt_instruction(query)):
        query = ""
    if current and query:
        prompt = f"{current}{query}" if _CJK_RE.search(current[-1:]) and _CJK_RE.search(query[:1]) else f"{current} {query}"
    else:
        prompt = current or query
    return _tail_chars(compact_whitespace(prompt), 360)


def _parse_base_completion_candidates(
    raw_text: str,
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
) -> list[str]:
    cleaned = _clean_base_completion_text(raw_text)
    if not cleaned:
        return []
    context_sections = _split_prediction_context(recent_context)
    context_text = compact_whitespace(" ".join(item for item in context_sections.values() if item))
    candidates = _base_candidate_parts(cleaned)
    if not candidates:
        candidates = parse_prediction_candidates(cleaned, max_candidates=max_candidates)
    if not candidates:
        candidates = [cleaned]
    return _filter_base_completion_candidates(
        candidates,
        current_input=current_input,
        recent_context=context_text or recent_context,
        max_candidates=max_candidates,
    )


def _clean_base_completion_text(text: str) -> str:
    text = re.split(r"<\|(?:im_end|endoftext|im_start)\|>", text, maxsplit=1)[0]
    cleaned = re.sub(r"(?is)<think>.*?</think>", " ", text)
    cleaned = re.sub(r"(?is)<think>.*", " ", cleaned)
    cleaned = re.sub(r"(?is)<analysis>.*?</analysis>", " ", cleaned)
    cleaned = re.sub(r"(?is)<reasoning>.*?</reasoning>", " ", cleaned)
    cleaned = re.sub(r"<\|[^|]{1,64}\|>", " ", cleaned)
    cleaned = cleaned.replace("Assistant:", " ").replace("assistant:", " ")
    cleaned = cleaned.replace("```json", " ").replace("```", " ")
    return compact_whitespace(cleaned)


def _base_candidate_parts(text: str) -> list[str]:
    json_candidates = _jsonish_base_candidates(text)
    if json_candidates:
        return json_candidates
    first_clause = re.split(r"[。！？!?；;\n\r]", text, maxsplit=1)[0]
    first_clause = re.sub(r"^[,，、\s]+", "", first_clause)
    if not first_clause:
        return []
    chunks = [part.strip(" ,，、。！？!?；;:：\"'“”‘’[]()（）") for part in re.split(r"[,，、]|\\s{2,}", first_clause)]
    chunks = [part for part in chunks if part]
    if chunks:
        return chunks
    return [first_clause]


def _jsonish_base_candidates(text: str) -> list[str]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, list):
        return [compact_whitespace(str(item)) for item in parsed if compact_whitespace(str(item))]
    if "[" in text:
        quoted = [match.strip() for match in re.findall(r'"([^"\n\r]{1,48})"', text)]
        if quoted:
            return quoted
    return []


def _filter_base_completion_candidates(
    candidates: list[str],
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    input_norm = _repeat_norm(current_input)
    context_norm = _repeat_norm(recent_context)
    for candidate in candidates:
        surface = _normalize_base_candidate(candidate)
        if not surface:
            continue
        norm = _repeat_norm(surface)
        if not norm or norm in seen:
            continue
        if input_norm and (norm == input_norm or norm in input_norm):
            continue
        if context_norm and (norm == context_norm or norm in context_norm):
            continue
        if _looks_like_prompt_instruction(surface) or _is_low_value_base_candidate(surface):
            continue
        seen.add(norm)
        result.append(surface)
        if len(result) >= max(1, int(max_candidates)):
            break
    return result


def _normalize_base_candidate(text: str) -> str:
    surface = compact_whitespace(text)
    surface = re.sub(r"^[0-9]+[.)、．]\s*", "", surface)
    surface = surface.strip(" \t\r\n\"'`[]{}(),，。！？:：;；、|")
    if not surface or "�" in surface or "<|" in surface:
        return ""
    if len(surface) > 24:
        surface = surface[:24]
    return surface


def _is_low_value_base_candidate(text: str) -> bool:
    normalized = compact_whitespace(text)
    if normalized in _LOW_VALUE_LOGITS_CANDIDATES:
        return True
    if re.fullmatch(r"(?:候选|预测|建议)[:：]\s*[A-Za-z0-9_-]{0,8}", normalized):
        return True
    if len(normalized) <= 1:
        return True
    cjk_count = len(_CJK_RE.findall(normalized))
    if re.fullmatch(r"[A-Za-z0-9_./:\-\s]{1,24}", normalized):
        return True
    if cjk_count < 2:
        return True
    if normalized.startswith(("我", "你", "您")) and len(normalized) <= 3:
        return True
    if re.fullmatch(r"(?:我|你|您)?(?:想|打算|准备|准备要|要|想要|计划)(?:设|写|做|改|看|试|用|把|让|给)?", normalized):
        return True
    if re.fullmatch(r"[嗯啊呃额哦噢唔]{1,4}", normalized):
        return True
    if normalized.endswith(("：", ":")) and len(normalized) <= 6:
        return True
    if normalized.endswith("候选") and len(normalized) <= 6:
        return True
    if _looks_like_meta_completion_candidate(normalized):
        return True
    return False


def _split_prediction_context(text: str) -> dict[str, str]:
    normalized = compact_whitespace(text)
    result = {"history": "", "current": ""}
    if not normalized:
        return result
    current_match = re.search(r"当前上下文:\s*(.+)$", normalized)
    if current_match:
        current = current_match.group(1)
        current = re.split(r"\s*历史(?:输入|参考)[^:：]*[:：]", current, maxsplit=1)[0]
        result["current"] = compact_whitespace(current)
    history_match = re.search(r"历史(?:输入|参考)[^:：]*[:：]\s*(.+?)(?:\s*当前上下文:|$)", normalized)
    if history_match:
        result["history"] = compact_whitespace(history_match.group(1))
    if not result["current"] and not result["history"]:
        result["current"] = normalized
    return result


def _strip_prediction_context_labels(text: str) -> str:
    stripped = re.sub(r"历史(?:输入|参考)[^:：]*[:：]", " ", text)
    stripped = stripped.replace("当前上下文:", " ")
    return compact_whitespace(stripped)


def _remove_context_overlap(query: str, current: str) -> str:
    query = compact_whitespace(query)
    current = compact_whitespace(current)
    if not query or not current:
        return query
    if _repeat_norm(query) == _repeat_norm(current[-len(query) :]):
        return ""
    if query.startswith(current[-min(len(current), len(query)) :]):
        return compact_whitespace(query.removeprefix(current[-min(len(current), len(query)) :]))
    return query


def _looks_like_candidate_constraint_query(text: str) -> bool:
    normalized = compact_whitespace(text)
    if not normalized:
        return False
    parts = [part for part in re.split(r"[\s,，、;；|/]+", normalized) if part]
    cjk_parts = sum(1 for part in parts if _CJK_RE.search(part))
    ascii_parts = sum(1 for part in parts if part.isascii())
    return len(parts) >= 2 and (cjk_parts >= 2 or ascii_parts >= 1)


def _looks_like_prompt_instruction(text: str) -> bool:
    lowered = text.lower()
    prompt_markers = (
        "已上屏上下文",
        "已上屏文本",
        "上屏文字",
        "请求类型",
        "模式说明",
        "当前拼音",
        "当前拼音或参考候选",
        "当前输入",
        "候选词",
        "输出",
        "json",
        "assistant",
        "system",
        "user",
        "/no_think",
    )
    return any(marker in lowered for marker in prompt_markers)


def _repeat_norm(text: str) -> str:
    return re.sub(r"[\s\W_]+", "", compact_whitespace(text), flags=re.UNICODE).lower()


def _tail_chars(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[-max_chars:]


def _request_metadata_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key in (
        "currentInputFingerprint",
        "contextFingerprint",
        "contextChars",
        "stablePrefixHash",
        "requestType",
        "rimeCandidateCount",
        "rimeCandidatesFingerprint",
    ):
        value = payload.get(key)
        if isinstance(value, (str, int, float, bool)):
            result[key] = value
    return result


@dataclass
class _PromptCacheState:
    enabled: bool
    stable_prefix: str
    max_kv_size: int = 0
    cache_file: str = ""
    prepared: bool = False
    stable_prefix_tokens: int = 0
    prepare_ms: int = 0
    used_for_generation: bool = False
    hit_count: int = 0
    miss_count: int = 0
    error: str = ""

    def stable_prefix_hash(self) -> str:
        return hashlib.sha256(self.stable_prefix.encode("utf-8")).hexdigest()[:16]

    def ready_for_generation(self) -> bool:
        return self.enabled and self.prepared and bool(self.cache_file) and os.path.exists(self.cache_file)

    def to_payload(self) -> dict[str, Any]:
        payload = {
            "enabled": self.enabled,
            "prepared": self.prepared,
            "usedForGeneration": self.used_for_generation,
            "stablePrefixHash": self.stable_prefix_hash(),
            "stablePrefixTokens": self.stable_prefix_tokens,
            "prepareMs": self.prepare_ms,
            "maxKvSize": self.max_kv_size,
            "cacheFileReady": bool(self.cache_file) and os.path.exists(self.cache_file),
            "hits": self.hit_count,
            "misses": self.miss_count,
        }
        if self.error:
            payload["error"] = self.error
        if self.enabled and self.prepared and not self.used_for_generation:
            payload["reason"] = "prepared_only_streaming_generation_not_cached_yet"
        elif not self.enabled:
            payload["reason"] = "disabled"
        return payload


def _token_to_int(token: object) -> int:
    item = getattr(token, "item", None)
    if callable(item):
        return int(item())
    return int(token)  # type: ignore[arg-type]


def _token_is_eos(tokenizer: Any, token_id: int) -> bool:
    eos_token_id = getattr(tokenizer, "eos_token_id", None)
    if eos_token_id is None:
        return False
    if isinstance(eos_token_id, (list, tuple, set)):
        try:
            return int(token_id) in {int(item) for item in eos_token_id}
        except (TypeError, ValueError):
            return False
    try:
        return int(token_id) == int(eos_token_id)
    except (TypeError, ValueError):
        return False


def _truncate_at_generation_stop(text: str) -> tuple[str, bool]:
    stop_indexes = [text.find(marker) for marker in GENERATION_STOP_MARKERS if marker and marker in text]
    stop_indexes = [index for index in stop_indexes if index >= 0]
    if not stop_indexes:
        return text, False
    first_stop = min(stop_indexes)
    return text[:first_stop], True


def _visible_generation_text(text: str) -> tuple[str, bool]:
    visible, reached_stop = _truncate_at_generation_stop(text)
    if reached_stop:
        return visible, True
    for marker in GENERATION_STOP_MARKERS:
        max_prefix = min(len(marker) - 1, len(visible))
        for prefix_len in range(max_prefix, 0, -1):
            if visible.endswith(marker[:prefix_len]):
                return visible[:-prefix_len], False
    return visible, False


def _top_logprob_indices(logprobs: Any, *, limit: int) -> list[int]:
    if isinstance(logprobs, (list, tuple)):
        return sorted(range(len(logprobs)), key=lambda index: float(logprobs[index]), reverse=True)[:limit]
    try:
        import mlx.core as mx  # type: ignore

        order = mx.argsort(-logprobs)[:limit]
        return [int(item) for item in _array_to_list(order)]
    except Exception:
        return []


def _logprob_at(logprobs: Any, token_id: int) -> float | None:
    try:
        if isinstance(logprobs, (list, tuple)):
            return float(logprobs[token_id])
        value = logprobs[token_id]
        item = getattr(value, "item", None)
        return float(item() if callable(item) else value)
    except Exception:
        return None


def _array_to_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        result = tolist()
        return result if isinstance(result, list) else [result]
    try:
        return list(value)
    except TypeError:
        return [value]


def _normalize_logits_candidate_text(value: Any) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    text = compact_whitespace(str(value))
    text = text.strip(" \t\r\n\"'`[]{}(),，。！？:：;；、|")
    text = text.replace("<0x0A>", "").replace("<|endoftext|>", "")
    if "<|" in text or "�" in text:
        return ""
    return text


def _logits_candidates_are_ime_quality(candidates: Any, *, max_candidates: int) -> bool:
    if not isinstance(candidates, list):
        return False
    texts = [compact_whitespace(str(item)) for item in candidates if compact_whitespace(str(item))]
    if not texts:
        return False
    if len(texts) < max(3, min(5, int(max_candidates))):
        return False
    phrase_like = [
        text
        for text in texts
        if len(text) >= 3
        and not _is_low_value_logits_candidate(text)
        and not re.fullmatch(r"[嗯啊呃额哦噢唔]{1,4}", text)
    ]
    if len(phrase_like) < max(3, min(5, int(max_candidates))):
        return False
    single_char_count = sum(1 for text in phrase_like if len(text) == 1)
    if single_char_count > len(phrase_like) // 2:
        return False
    return True


def _is_low_value_logits_candidate(text: str) -> bool:
    normalized = compact_whitespace(text)
    if normalized in _LOW_VALUE_LOGITS_CANDIDATES:
        return True
    if re.fullmatch(r"(?:候选|预测|建议)[:：]\s*[A-Za-z0-9_-]{0,8}", normalized):
        return True
    cjk_count = len(_CJK_RE.findall(normalized))
    if re.fullmatch(r"[A-Za-z0-9_./:\-\s]{1,24}", normalized):
        return True
    if cjk_count < 2:
        return True
    if any(normalized.startswith(prefix) for prefix in ("测试", "分析")) and len(normalized) <= 4:
        return True
    if any(normalized.startswith(prefix) for prefix in ("当前", "目前", "现在")) and len(normalized) <= 5:
        return True
    if _looks_like_meta_completion_candidate(normalized):
        return True
    return False


def _build_no_input_space_list_prompt(*, recent_context: str, max_candidates: int) -> str:
    max_items = max(1, min(10, int(max_candidates)))
    return (
        f"<|im_start|>system\n{SPACE_LIST_SYSTEM_PROMPT}<|im_end|>\n"
        "<|im_start|>user\n"
        f"上下文：\"{recent_context}\"\n"
        "当前输入：\"\"\n"
        f"候选词数量：{max_items}\n"
        "候选词："
        "<|im_end|>\n"
        f"{QWEN_NON_THINKING_ASSISTANT_PREFIX}"
    )


def _build_seeded_replay_prompt(*, recent_context: str, seed_text: str) -> str:
    return (
        f"<|im_start|>system\n{STREAM_FIRST_SYSTEM_PROMPT}<|im_end|>\n"
        "<|im_start|>user\n"
        f"上下文：\"{recent_context}\"\n"
        f"当前输入：\"\"\n"
        f"种子候选：\"{seed_text}\"\n"
        "请把这个种子候选续写成一个可直接上屏的短语。"
        "不要解释，不要换行，不要输出多个候选。"
        "<|im_end|>\n"
        f"{QWEN_NON_THINKING_ASSISTANT_PREFIX}{seed_text}"
    )


def _space_list_continuation_candidates(
    raw_text: str,
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
) -> list[str]:
    cleaned = _clean_base_completion_text(raw_text)
    if not cleaned:
        return []
    parts = [
        part
        for part in re.split(r"[\s,，、;；|/\n\r]+", cleaned)
        if compact_whitespace(part)
    ]
    result: list[str] = []
    seen: set[str] = set()
    for part in parts:
        candidate = _branch_continuation_candidate(
            part,
            current_input=current_input,
            recent_context=recent_context,
            max_candidate_chars=12,
        )
        normalized = compact_whitespace(candidate)
        if (
            not normalized
            or normalized in seen
            or _is_low_value_base_candidate(normalized)
            or _looks_like_meta_completion_candidate(normalized)
        ):
            continue
        seen.add(normalized)
        result.append(normalized)
        if len(result) >= max(1, int(max_candidates)):
            break
    return result


def _continuation_branch_specs(*, temperature: float, max_tokens: int) -> list[_ContinuationBranchSpec]:
    low_temperature = max(0.05, min(float(temperature), 0.18))
    token_budget = max(12, min(64, int(max_tokens)))
    return [
        _ContinuationBranchSpec(
            label="lead",
            temperature=low_temperature,
            max_tokens=min(24, token_budget),
            max_candidate_chars=24,
        )
    ]


def _seed_replay_specs_from_logits(candidate_scores: Any, *, max_seeds: int) -> list[dict[str, Any]]:
    if not isinstance(candidate_scores, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in candidate_scores:
        if not isinstance(item, dict):
            continue
        text = compact_whitespace(str(item.get("text") or ""))
        if (
            not text
            or text in seen
            or _is_low_value_base_candidate(text)
            or _looks_like_meta_completion_candidate(text)
        ):
            continue
        if len(text) > 6:
            continue
        seen.add(text)
        result.append(
            {
                "text": text,
                "tokenId": item.get("tokenId"),
                "logprob": item.get("logprob"),
                "probability": item.get("probability"),
            }
        )
        if len(result) >= max(1, int(max_seeds)):
            break
    return result


def _branch_continuation_candidate(
    raw_text: str,
    *,
    current_input: str,
    recent_context: str,
    max_candidate_chars: int,
) -> str:
    parsed = parse_ime_prediction_candidates(
        raw_text,
        max_candidates=8,
        current_input=current_input,
        recent_context=recent_context,
        request_type=PREDICTION_REQUEST_NO_INPUT,
    )
    if not parsed:
        return ""
    limit = max(2, int(max_candidate_chars))
    eligible = [candidate for candidate in parsed if len(candidate) <= limit]
    if eligible:
        candidate = max(eligible, key=len)
    else:
        candidate = parsed[0][:limit]
    if _is_low_value_base_candidate(candidate) or _looks_like_meta_completion_candidate(candidate):
        return ""
    return candidate


def _branch_continuation_candidates(
    raw_text: str,
    *,
    current_input: str,
    recent_context: str,
    max_candidate_chars: int,
    max_candidates: int,
) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    parts = [
        compact_whitespace(part)
        for part in re.split(r"[\s,，、;；。.!！?？\n\r]+", _clean_base_completion_text(raw_text))
        if compact_whitespace(part)
    ]
    if len(parts) <= 1:
        parts = [raw_text]
    for part in parts:
        candidate = _branch_continuation_candidate(
            part,
            current_input=current_input,
            recent_context=recent_context,
            max_candidate_chars=max_candidate_chars,
        )
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        result.append(candidate)
        if len(result) >= max(1, int(max_candidates)):
            break
    return result


def _seeded_replay_candidate(
    *,
    seed_text: str,
    raw_text: str,
    current_input: str,
    recent_context: str,
    max_candidate_chars: int,
) -> str:
    seed = compact_whitespace(seed_text)
    continuation = _clean_base_completion_text(raw_text)
    if continuation.startswith(seed):
        combined = continuation
    else:
        combined = compact_whitespace(f"{seed}{continuation}")
    direct = _normalize_base_candidate(combined)
    if (
        direct
        and direct.startswith(seed)
        and len(direct) > len(seed)
        and len(direct) <= max(2, int(max_candidate_chars))
        and not _is_low_value_base_candidate(direct)
        and not _looks_like_meta_completion_candidate(direct)
    ):
        return direct
    parsed = parse_ime_prediction_candidates(
        combined,
        max_candidates=4,
        current_input=current_input,
        recent_context=recent_context,
        request_type=PREDICTION_REQUEST_NO_INPUT,
    )
    limit = max(2, int(max_candidate_chars))
    for candidate in parsed:
        normalized = compact_whitespace(candidate)
        if (
            normalized
            and normalized.startswith(seed)
            and len(normalized) > len(seed)
            and len(normalized) <= limit
            and not _is_low_value_base_candidate(normalized)
            and not _looks_like_meta_completion_candidate(normalized)
        ):
            return normalized
    return ""


def _expand_continuation_candidates_from_model_output(
    candidates: list[str],
    *,
    current_input: str,
    recent_context: str,
    max_candidates: int,
) -> list[str]:
    """Split a real model continuation into several selectable IME candidates.

    This keeps post-commit prediction local-model based even when the small MLX
    model emits one fluent continuation instead of a candidate list.
    """

    max_items = max(1, int(max_candidates))
    result: list[str] = []
    seen = {compact_whitespace(item) for item in candidates if compact_whitespace(item)}
    for candidate in candidates:
        normalized = compact_whitespace(candidate)
        if not normalized or _looks_like_meta_completion_candidate(normalized):
            continue
        splits = _continuation_candidate_splits(normalized)
        if not splits:
            splits = parse_ime_prediction_candidates(
                normalized,
                max_candidates=max_items,
                current_input=current_input,
                recent_context=recent_context,
                request_type=PREDICTION_REQUEST_NO_INPUT,
            )
        for item in splits:
            item = compact_whitespace(item)
            if (
                not item
                or item in seen
                or _is_low_value_base_candidate(item)
                or _looks_like_meta_completion_candidate(item)
            ):
                continue
            seen.add(item)
            result.append(item)
            if len(seen) >= max_items:
                return result
    return result


def _continuation_candidate_splits(text: str) -> list[str]:
    normalized = compact_whitespace(text)
    compacted = re.sub(r"\s+", "", normalized)
    if _CJK_RE.search(compacted) is None or len(compacted) < 5:
        return []
    base = _strip_leading_continuation_connector(compacted)
    variants = [base]
    for match in re.finditer(r"(更直观|看到|优化|完成|继续|实现|提升|减少|帮助|方便|用于|接入|整理|修复|验证)", base):
        if 0 < match.start() <= len(base) - 4:
            variants.append(base[match.start() :])
        if 0 < match.end() <= len(base) - 4:
            variants.append(base[match.end() :])
    result: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        if len(variant) < 4:
            continue
        full_variant = _normalize_continuation_split_candidate(variant[:12])
        if (
            full_variant
            and full_variant not in seen
            and len(full_variant) >= 4
            and not _is_low_value_base_candidate(full_variant)
            and not _looks_like_meta_completion_candidate(full_variant)
        ):
            seen.add(full_variant)
            result.append(full_variant)
        if len(variant) >= 4:
            tail = _normalize_continuation_split_candidate(variant[-min(6, len(variant)) :])
            if (
                tail
                and tail not in seen
                and len(tail) >= 3
                and not _is_low_value_base_candidate(tail)
                and not _looks_like_meta_completion_candidate(tail)
            ):
                seen.add(tail)
                result.append(tail)
    return result


def _strip_leading_continuation_connector(text: str) -> str:
    result = compact_whitespace(text)
    for prefix in ("从而", "用于", "以便", "为了", "并且", "然后", "接着", "以", "并", "来", "将"):
        if result.startswith(prefix) and len(result) - len(prefix) >= 4:
            return result[len(prefix) :]
    return result


def _normalize_continuation_split_candidate(text: str) -> str:
    item = compact_whitespace(str(text))
    item = item.strip(" \t\r\n。.!！?？:\"'“”‘’[]()（）{}<>《》")
    return compact_whitespace(item)


def _looks_like_meta_completion_candidate(text: str) -> bool:
    normalized = compact_whitespace(text)
    if not normalized:
        return False
    meta_prefixes = (
        "你正在",
        "您正在",
        "用户正在",
        "当前正在",
        "正在输入",
        "正在阅读",
    )
    attempt_prefixes = (
        "你尝试",
        "您尝试",
        "用户尝试",
    )
    if any(normalized.startswith(prefix) for prefix in attempt_prefixes):
        return True
    meta_markers = (
        "已经上屏",
        "上屏文本",
        "说明性文本",
        "关于“",
        "关于\"",
        "作为候选",
        "输入法候选",
        "LLM",
        "RAG",
        "功能",
        "方法",
        "成功",
        "请检查",
        "重新输入",
        "这个项目",
        "号项目",
        "项目吗",
    )
    if not any(normalized.startswith(prefix) for prefix in meta_prefixes):
        return False
    if len(normalized) <= 8:
        return True
    return any(marker in normalized for marker in meta_markers)


def _continuation_branch_candidate_scores(
    candidates: list[str],
    *,
    branch_timings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    branch_by_candidate: dict[str, str] = {}
    for branch in branch_timings:
        label = str(branch.get("label") or "branch")
        branch_candidates = branch.get("candidates")
        if not isinstance(branch_candidates, list):
            continue
        for item in branch_candidates:
            text = compact_whitespace(str(item))
            if text and text not in branch_by_candidate:
                branch_by_candidate[text] = label
    total = max(1, len(candidates))
    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        text = compact_whitespace(candidate)
        if not text:
            continue
        result.append(
            {
                "text": text,
                "rank": index,
                "source": branch_by_candidate.get(text, "branch"),
                "mode": "continuation-branches",
                "confidence": max(0.0, min(1.0, 1.0 - ((index - 1) / max(3, total + 1)) * 0.35)),
            }
        )
    return result


def _seeded_prompt_replay_candidate_scores(
    candidates: list[str],
    *,
    branch_timings: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    branch_by_candidate: dict[str, dict[str, Any]] = {}
    for branch in branch_timings:
        branch_candidates = branch.get("candidates")
        if not isinstance(branch_candidates, list):
            continue
        for item in branch_candidates:
            text = compact_whitespace(str(item))
            if text and text not in branch_by_candidate:
                branch_by_candidate[text] = branch
    total = max(1, len(candidates))
    result: list[dict[str, Any]] = []
    for index, candidate in enumerate(candidates, start=1):
        text = compact_whitespace(candidate)
        if not text:
            continue
        branch = branch_by_candidate.get(text, {})
        result.append(
            {
                "text": text,
                "rank": index,
                "source": str(branch.get("label") or "seed-replay"),
                "mode": "seeded-prompt-replay",
                "branchRank": branch.get("branchRank"),
                "branchCount": branch.get("branchCount"),
                "seedText": branch.get("seedText"),
                "seedTokenId": branch.get("seedTokenId"),
                "probability": branch.get("probability"),
                "logprob": branch.get("logprob"),
                "confidence": max(0.0, min(1.0, 1.0 - ((index - 1) / max(3, total + 1)) * 0.28)),
            }
        )
    return result


def _prompt_cache_used_for_generation(prompt_cache: dict[str, Any]) -> bool:
    return (
        bool(prompt_cache.get("enabled"))
        and bool(prompt_cache.get("prepared"))
        and bool(prompt_cache.get("cacheFileReady"))
        and bool(prompt_cache.get("usedForGeneration"))
    )


def _int_payload(value: object, fallback: int) -> int:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def _float_payload(value: object, fallback: float) -> float:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return fallback


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rag-ime-mlx-predictor-server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8767)
    parser.add_argument("--model", required=True)
    parser.add_argument("--max-tokens", type=int, default=8)
    parser.add_argument("--temperature", type=float, default=0.15)
    parser.add_argument("--top-p", type=float, default=0.85)
    parser.add_argument("--prompt-cache", action="store_true", help="Prepare the stable system-prompt cache at startup")
    parser.add_argument("--prompt-cache-max-kv-size", type=int, default=0)
    args = parser.parse_args(argv)
    serve_mlx_predictor(
        MlxPredictorServerConfig(
            host=args.host,
            port=args.port,
            model=args.model,
            max_tokens=args.max_tokens,
            temperature=args.temperature,
            top_p=args.top_p,
            prompt_cache=args.prompt_cache,
            prompt_cache_max_kv_size=args.prompt_cache_max_kv_size,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
