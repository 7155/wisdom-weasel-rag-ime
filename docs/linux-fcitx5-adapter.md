# Linux Fcitx5 / Rime Frontend Adapter

## Status

- Target platform: Linux desktop input methods.
- Preferred frontend: Fcitx5 with Rime / librime composition.
- Product boundary: thin frontend adapter, not a standalone pinyin engine.
- Shared runtime: the existing Python sidecar and `/rime-suggest` / `/rime-select` contract.

## Decision

The Linux version should mirror the accepted macOS Squirrel route: let a mature
Rime frontend own composition, dictionaries, paging, labels, English/code/path
handling, user frequency, and fallback. RAG-IME should attach after librime has
produced structured context and before the visible candidate list is finalized.

```text
Fcitx5 key event
  -> fcitx5-rime / librime process_key
  -> Rime context: raw input, preedit, commit preview, candidates, comments,
     labels, highlighted index, page state
  -> RAG-IME sidecar POST /rime-suggest
  -> displayCandidates + predictionSession
  -> Fcitx5 candidate UI
  -> selection routing
```

Do not port the macOS `RagImeMac` debug harness as the Linux product. It is a
contract and panel playground. The Linux product equivalent is a Fcitx5/Rime
adapter that follows the same display-candidate contract as the Squirrel patch.

## Hard Rules

1. **Rime/Wanxiang owns raw composition.** The Linux adapter must not ask the
   LLM to decode dirty raw pinyin.
2. **The adapter is fail-closed.** If the sidecar times out, returns invalid
   JSON, or cannot be reached, normal Fcitx5/Rime input continues unchanged.
3. **One visible candidate sequence.** Each visible row must map to either a
   Rime candidate or a side candidate with explicit selection metadata.
4. **Prediction is session-bound.** Empty candidates, stale responses, focus
   loss, Escape, raw English/code/path input, and incompatible key events clear
   the prediction panel.
5. **Feedback is centralized.** Side-candidate commits call `/rime-select` so
   accepted and skipped-higher feedback remain shared with macOS.

## Request Mapping

The Linux adapter should build the same logical request as the Squirrel frontend:

```json
{
  "sessionId": "fcitx5-rime-session",
  "requestSeq": 42,
  "rawInput": "ragshurufa",
  "preedit": "ragshurufa",
  "committedContext": "最近上屏文本",
  "maxVisibleCandidates": 8,
  "maxSideCandidates": 3,
  "latencyBudgetMs": 150,
  "rimeContext": {
    "commitTextPreview": "RAG 输入法",
    "highlightedIndex": 0,
    "page": 0,
    "isLastPage": false,
    "candidates": [
      {"label": "1", "text": "RAG 输入法", "comment": "rime"}
    ]
  }
}
```

When Rime candidates or commit preview are available, the adapter should send
that structured context and let the sidecar choose the semantic query basis. Raw
input alone is only a last resort and must not be treated as a free-form pinyin
request for the model.

## Response Mapping

The sidecar returns `displayCandidates` and `predictionSession`. The Linux
adapter should treat `displayCandidates` as the display source of truth:

- `selectionAction == select_rime_candidate`: route selection back to librime.
- `selectionAction == commit_side_candidate`: commit `insertText`, then call
  `/rime-select` with the selected row and visible `shownCandidates`.
- `selectionKey`: authoritative keyboard key for the visible row.
- `selectionRank`: rank recorded for feedback; key `0` maps to rank 10.
- `predictionSession.shouldClearPredictionPanel == true`: clear side candidates
  even if local adapter caches still have rows.

The adapter should drop late responses when `requestSeq`, session id, raw input,
preedit, page, highlighted index, or the first visible Rime candidate fingerprint
no longer matches the active context.

## Runtime Service

Linux should run the existing Python sidecar as a user service:

```bash
scripts/install_sidecar_systemd_user.sh
```

The service starts:

```bash
python3 -m rag_ime.cli sidecar-server --host 127.0.0.1 --port 8766
```

The Fcitx5 adapter should prefer `RAG_IME_SIDECAR_URL`, defaulting to
`http://127.0.0.1:8766`. The sidecar exposes:

- `GET /health`
- `POST /rime-suggest`
- `POST /rime-select`

## Predictor Defaults On Linux

Linux should not inherit the macOS MLX default path. Use the existing optional
OpenAI-compatible predictor contract for local Linux runtimes such as Ollama,
llama.cpp server, vLLM, or another user-owned endpoint:

```bash
export RAG_IME_PREDICTOR_PROVIDER=openai-compatible
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434
export RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b
export RAG_IME_PREDICTOR_PROFILE=instant
export RAG_IME_PREDICTOR_STREAM_FIRST=1
```

The model lane remains optional. Rime fallback and RAG/memory candidates must
still work when no predictor is configured.

## Minimum Implementation Checklist

- [ ] Create `linux/fcitx5-rag-ime/` adapter sources.
- [ ] Read current Fcitx5/Rime context after librime candidate generation.
- [ ] Build `RimeSidecarRequest` equivalent payloads.
- [ ] Add async request sequence and fingerprint guards.
- [ ] Merge `displayCandidates` into the visible candidate list without mutating
      librime internals.
- [ ] Route normal Rime selections to librime.
- [ ] Route side-candidate commits to insertion plus `/rime-select`.
- [ ] Clear prediction candidates on stale, empty, Escape, focus loss, raw
      English/code/path, and incompatible key events.
- [ ] Add Linux doctor checks for Fcitx5, Rime, sidecar health, and contract
      probe.
