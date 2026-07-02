# Rime / Squirrel Frontend Framework Decision

- Date: 2026-06-30
- Status: accepted for production route
- Current implementation: InputMethodKit prototype and debug harness
- Production target: Rime/Squirrel-based macOS frontend, with Wisdom-Weasel as the main LLM prediction reference

## Decision

The production macOS input method should be based on Rime/Squirrel, not a standalone custom pinyin engine.

The current `macos/RagImeMac` InputMethodKit adapter remains useful for quickly testing the RAG backend, JSON bridge, candidate panel, and action feedback. It is not the final Chinese composition framework.

The final frontend route should be:

```text
macOS Squirrel / InputMethodKit
  -> librime session
  -> RimeContext: preedit, Rime candidates, labels, comments, page state
  -> RAG-IME side candidate sources
       -> local model continuation / rerank
       -> local RAG / memory candidates with evidence
  -> compact candidate panel
  -> selection feedback to Rime and local memory core
```

Wisdom-Weasel should be treated as a hard reference, not only inspiration. Its useful lesson is that LLM prediction works best when it is added beside Rime, while Rime still owns schemes, dictionaries, spelling correction, paging, and ordinary candidate selection.

## Hard Principle

The LLM must not be the raw pinyin parser.

For noisy input such as abbreviated, mistyped, or partially segmented pinyin, the pipeline should first let Rime produce legal composition candidates and context. The model can then:

- continue from committed text and recent context;
- rerank or compress candidate text;
- generate continuation candidates after a commit;
- use pinyin constraints supplied by the engine or adapter.

It should not freely infer Chinese text directly from unstructured raw key streams. That would turn a deterministic input-method problem into a slow, unstable text-generation problem.

## Why Rime/Squirrel Is The Better Base

Squirrel already solves the mature macOS input method problems:

- InputMethodKit lifecycle and session handling;
- key event translation into librime key codes;
- per-client session state;
- preedit and marked text handling;
- candidate labels, comments, paging, highlighting, and mouse selection;
- inline preedit / inline candidate behavior;
- app-specific quirks and configuration;
- bundled librime plugins and Rime data deployment.

The current Squirrel source path confirms the right insertion boundary:

```text
SquirrelInputController.handle()
  -> processKey()
  -> rimeAPI.process_key()
  -> rimeUpdate()
  -> rimeAPI.get_context()
  -> candidates/comments/labels arrays
  -> SquirrelPanel.update()
```

That is exactly where RAG-IME should attach: after librime has turned the key stream into structured input context, before the panel renders final candidates.

## Lessons To Keep From Wisdom-Weasel

Wisdom-Weasel is valuable because it already stepped on several input-method-specific problems:

1. Preserve Rime schemes and dictionaries.
   Wisdom-Weasel keeps Rime as the base and appends LLM candidates instead of replacing normal input.

2. Keep LLM prediction asynchronous.
   Input must never block while model inference, HTTP, embedding, or reranking runs.

3. Drop stale prediction results.
   Wisdom-Weasel uses a request sequence counter so older model results cannot overwrite newer candidates after the user keeps typing.

4. Merge candidates at the structured candidate layer.
   Wisdom-Weasel appends LLM candidates to the Rime candidate list and branches selection handling when the chosen index belongs to an LLM candidate.

5. Keep recent committed text as prediction context.
   Recent accepted text is a better signal than raw current pinyin for the next-word prediction lane.

6. Use constrained generation only when constraints are explicit.
   The HF provider sends `pinyin_constraints`; it does not ask the model to guess arbitrary dirty pinyin.

7. Optimize local inference for IME latency.
   The llama.cpp provider caches system prompt state and batch-samples multiple candidates, instead of serially asking for five candidates.

8. Treat prediction UI as a short-lived session.
   The LLM candidate window should be visible only while composition or LLM prediction mode has live candidates. Empty candidates, stale request sequence, Esc, focus loss, or ordinary input should exit prediction mode and hide the panel. RAG-IME exposes the same contract as `predictionFirst.policy.panelVisible / hideWhenEmpty / sessionBound`.

9. Do not copy a persistent popup.
   The Wisdom-Weasel demo feels natural because LLM candidates visually continue
   the normal Rime candidate flow. It is not a long-lived clipboard/history
   panel. RAG-IME should keep the post-commit prediction panel short-lived: if
   the user does not select a prediction and the session goes stale, the panel
   must clear even when the backend still has cached memory candidates.

## Candidate Lane Policy

The UI should not split "word candidates" and "paragraph candidates" into separate number-key modes.

Use one visible number sequence:

```text
active composition:
  1..N    Rime candidates from current page
  N+1..M  side candidates if slots remain

after commit / prediction-only mode:
  1..K    model continuation and RAG/memory candidates
```

Rime candidates keep priority during active composition because they are the user's normal typing path. RAG and memory candidates should be appended or shown in a compact secondary lane, not allowed to steal the first candidate slots unless the user explicitly enables aggressive reranking.

After a commit, the prediction-only panel is allowed to replace the Rime list
briefly, but it must be session-bound. It is not a clipboard/history panel: if
no model/RAG/memory candidate is ready, or the post-commit window has gone
stale, the panel should disappear so digits and English/code input stay normal.
The practical default is a roughly 0.85-0.9s post-commit window; the current
native harness uses 0.85s and the patched Squirrel path uses 0.9s. Any longer
continuation should require an active prefix, a fresh model/RAG response, or an
explicit expand action.

The default IME panel stays small:

- top: active Rime candidates, optionally with model-informed ordering later;
- bottom: at most two or three RAG/memory/continuation candidates;
- evidence: one short hint for the highlighted RAG candidate only;
- full pipeline timing, model name, JSON, and governance controls stay in the debug surface.

## Implementation Route

### Phase 0: Keep Current Prototype

Keep `macos/RagImeMac` as:

- a fast test harness for the backend contract;
- a panel design playground;
- an installer and bridge-config experiment;
- a fallback if Squirrel integration takes longer.

The native harness now consumes the same `/rime-suggest` `displayCandidates`
and `predictionSession` payload as the Squirrel path, and side-candidate
acceptance uses `/rime-select`. This keeps debug behavior aligned with the real
contract, but it does not change the framework decision: Wisdom-Weasel feels
natural because LLM candidates live in the structured Rime/Weasel candidate
flow, not because a detached panel stays open.

For local macOS debugging before a full librime adapter is available, the native
harness includes `RimeDictionaryCandidateProvider`. It reads a user-provided
Rime/Wanxiang dictionary via `RAG_IME_RIME_DICT_PATHS`,
`RAG_IME_RIME_DICT_PATH`, or `RAG_IME_RIME_DICT_DIR`, then falls back to
`~/Library/Rime`. For Wanxiang-style entrypoints, it expands `import_tables`
and folds tone marks so rows like `nǐ` match `ni`. It also uses `essay.txt`
weights to keep common entries first. This is deliberately a bridge, not a
replacement for real Squirrel/librime context.

Do not extend it into a full pinyin engine.

### Phase 1: Squirrel Fork / Patch Exploration

Create a Squirrel-based macOS frontend branch and verify a clean build/install.

Target source boundaries:

- `SquirrelInputController.swift`: after `rimeAPI.get_context()` builds candidates, comments, labels, page state.
- `SquirrelPanel.swift`: candidate rendering, mouse selection, paging, and layout.
- `ReservedProperty.swift`: possible protocol for UI hints, but not enough by itself for full RAG evidence.
- config: add `rag_ime/enabled`, backend command, max side candidates, latency budget.

### Phase 2: Side Candidate Contract

Reuse the current JSON backend contract, but make it Rime-aware. The current command is:

```bash
python3 -m rag_ime.cli rime-suggest-json --payload-file request.json
```

The debug API exposes the same contract at `POST /api/rime-suggest`.

Request shape:

```json
{
  "sessionId": "squirrel-session",
  "rawInput": "pin yin code from librime",
  "preedit": "Rime preedit text",
  "committedContext": "recent committed text",
  "rimeCandidates": [
    {"label": "1", "text": "比如", "comment": ""}
  ],
  "latencyBudgetMs": 150
}
```

Return:

```json
{
  "requestSeq": 42,
  "modelContinuations": [],
  "ragCandidates": [
    {
      "text": "把 RAG 召回材料压缩成可选候选",
      "evidenceHint": "来自项目记录",
      "sourceRef": "local-memory:..."
    }
  ]
}
```

The sidecar must be optional and fail-closed: when it times out or errors, normal Rime typing continues.

The response also includes `displayCandidates`, a merged display list where Rime
rows keep `selectionAction: select_rime_candidate` and model/RAG rows use
`selectionAction: commit_side_candidate`. The visible `label` stays for Squirrel
panel compatibility, while `selectionKey` and `selectionRank` make the shared
candidate-key contract explicit. `selectionRank` is 1-based and maps key `0` to
rank 10, so normal `1-9,0` candidate selection can be reused for both Rime rows
and side candidates without a separate paragraph mode.

### Phase 3: Candidate Merge

Merge rules:

1. Never mutate librime's internal candidate state for the MVP.
2. Build a frontend display list from:
   - current Rime candidate page;
   - side model candidates;
   - RAG/memory candidates.
3. When the user selects a Rime candidate, call normal `select_candidate_on_current_page`.
4. When the user selects a side candidate, route by `selectionKey`, insert the side candidate text, clear or commit the current composition as appropriate, and record the acceptance action with `selectionRank`.
5. Keep a request sequence guard so stale side results are ignored.

This mirrors Wisdom-Weasel's append-and-branch selection idea, but the RAG side candidate includes evidence metadata and memory governance feedback.

### Phase 4: Model Provider Upgrade

The current OpenAI-compatible provider now has two portable prompt modes:

- `chat`: Qwen/Instruct-style `/v1/chat/completions`, with optional `extra_body` to disable thinking.
- `completion`: base-model `/v1/completions`, using `recent_context + current_input` as a prefix and `n=max_candidates` for multiple alternatives.

This is enough to benchmark local Qwen, MLX, llama.cpp server, or other OpenAI-compatible endpoints without changing the IME frontend.

The better local model route should copy Wisdom-Weasel's stronger ideas:

- stable system prompt for cache reuse;
- batch sampling for multiple short candidates;
- strict token cap;
- no reasoning output;
- base-model completion mode when it is faster and cleaner;
- pinyin constraints only when provided by Rime or a real constraint decoder;
- p50/p95 first-candidate latency benchmark.

The part not covered yet is native llama.cpp/MLX provider ownership of KV cache and batch sampling. Wisdom-Weasel's `LlamaCppProvider` caches the system-prompt state and uses parallel llama sequences for multi-candidate sampling. RAG-IME's completion mode is the portable stepping stone; the native provider is still required for the same latency ceiling.

## Rejected Routes

### Pure InputMethodKit Pinyin Engine

Rejected for production. It would require rebuilding Rime's mature composition behavior, dictionaries, spelling correction, paging, schema system, and app-specific quirks.

### LLM Directly Parses Raw Pinyin

Rejected. It is slow, unstable, and weak on typo-heavy or abbreviated input. The model should consume structured context and constraints after Rime has done input composition.

### Floating Overlay Beside Squirrel Without Integration

Rejected as the main route. It can debug, but it cannot reliably own candidate numbers, selection, preedit state, paging, or focus lifecycle.

### Librime Plugin Only

Potential later route, but not enough for the first product UI. A librime translator/filter could improve portability across Squirrel, Weasel, and fcitx5-rime, but evidence preview and memory actions still need frontend support.

## Acceptance Criteria

- Normal Rime typing, paging, labels, comments, and app behavior continue to work.
- RAG/LLM candidates never block key handling.
- Stale RAG/LLM results cannot overwrite current candidates.
- Active composition candidates come from Rime first.
- Side candidates share the same visible number sequence instead of requiring a separate selection mode.
- Accepting a side candidate inserts text and records local feedback.
- The model provider never receives raw dirty pinyin as its only source of truth.
- Debug UI can show timing, request sequence, retrieval source, rerank result, and evidence without bloating the real IME panel.

## Source Check

Checked on 2026-06-30:

- `rime/squirrel@2158538`: `sources/SquirrelInputController.swift`, `sources/SquirrelPanel.swift`, `sources/ReservedProperty.swift`.
- `rime/weasel@93eec2d`: `RimeWithWeasel/RimeWithWeasel.cpp`, `include/WeaselIPCData.h`, `WeaselUI/WeaselPanel.cpp`.
- `scukeqi/Wisdom-Weasel@64ba2fd`: `RimeWithWeasel/RimeWithWeasel.cpp`, `WeaselServer/LLMProvider.cpp`, `WeaselServer/HFConstraintProvider.cpp`, `WeaselServer/LlamaCppProvider.cpp`, `WeaselServer/ContextHistory.cpp`.

Primary upstream URLs:

- <https://github.com/rime/squirrel>
- <https://github.com/rime/weasel>
- <https://github.com/scukeqi/Wisdom-Weasel>
