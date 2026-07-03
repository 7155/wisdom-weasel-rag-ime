# Felix-First RAG-IME Architecture

Snapshot:
- Primary reference repo: `/tmp/felix-wisdom-weasel`
- Primary upstream: `https://github.com/Felix3322/Wisdom-Weasel.git`
- Reference commit: `3473284a14b0336d5e6a39d2dfb0ffcbdcfb5a17`
- Date checked: 2026-07-03

## Decision

The foreground IME architecture must primarily follow `Felix3322/Wisdom-Weasel`.

OpenLess is only a later management-console reference. It must not drive the current IME architecture until the Felix/Squirrel/Wanxiang route is working.

## Target Shape

```text
Squirrel/Rime/Wanxiang
  owns raw keystrokes, pinyin anchoring, English/code/path, user dictionary, and fallback

RAG-IME sidecar/core
  owns LLM/RAG/memory prediction, candidateization, session binding, ranking, and trace

MLX worker
  owns local small-model continuation, pinyin-constrained suggestion, and later prompt-cache warmup

SQLite memory/RAG
  owns typed history, phrase frequency, RAG evidence, accepted/skipped feedback, and score traces
```

The IME must feel like:

```text
Anchor with pinyin
  -> predict continuation
  -> user selects or continues pinyin to constrain
  -> rerank/predict again
```

It must not feel like:

```text
traditional Rime candidate list + stale AI popup + clipboard snippets
```

## Felix Mechanisms We Must Copy

### 1. One Visible Candidate List

Felix's `RimeWithWeasel/RimeWithWeasel.cpp` builds one display list with `_BuildDisplayCandidates(...)`.

Each visible row maps to exactly one source:

```text
Rime candidate
LLM candidate
Pending placeholder
```

Selection does not guess from row text. Number keys and mouse selection route through that display mapping via `_SelectDisplayCandidate(...)`.

Our rule:

```text
Every visible slot must map to one current-session candidate object.
If there is no current-session candidate object, digit keys must pass through normally.
```

This is the P0 fix for the user's repeated "candidate box stays and blocks numbers" feedback.

### 2. Typed LLM Requests

Felix's `WeaselServer/LLMProvider.h` defines:

```text
NoInputPrediction
PinyinConstrainedPrediction
RimeReorder
```

This is the correct small-model boundary.

Our MLX provider must keep the same conceptual contract:

```text
NoInputPrediction:
  input: recent committed context
  output: short continuation candidates

PinyinConstrainedPrediction:
  input: recent context + current pinyin + Rime candidates
  output: candidates that obey the current pinyin/prefix

RimeReorder:
  input: current Rime/Wanxiang candidate pool + recent context
  output: same pool reordered, not arbitrary new text
```

The model must not be asked to do raw pinyin conversion. Rime/Wanxiang owns that.

### 3. Candidateization Is Mandatory

Felix's `WeaselServer/LLMProvider.cpp` has explicit candidate normalization:

- trim wrappers and punctuation;
- strip numbering;
- reject ignorable tokens;
- cut generated text into short continuation candidates;
- deduplicate;
- diversify no-input candidates;
- parse streaming chunks into partial candidates.

Our rule:

```text
Raw MLX output is never inserted directly into the candidate list.
Only normalized, short, directly committable spans enter CandidatePool.
```

This fixes the current failure mode where candidates look like copied history or random snippets rather than useful LLM continuations.

### 4. Request Lifecycle And Stale Response Rejection

Felix clears old AI candidates on new pinyin input and uses request sequencing / scheduling boundaries to prevent stale rows from being selectable.

Our corresponding implementation boundary:

```text
PredictionManager computes sessionFingerprint
sidecar response carries predictionSession
Squirrel patch stores display session fingerprint
click/number selection checks candidate fingerprint
trace verifier rejects mismatched selection/commit
```

This is already partially implemented in the Squirrel patch and must be verified in the real installed IME before moving on.

### 5. Different Latency Lanes

Felix uses profiles:

```text
RimeReorder                 interactive, about 80 ms budget
PinyinConstrainedPrediction interactive, about 180 ms budget
NoInputPrediction           background, quiet window before showing
```

Our macOS/MLX rule:

```text
Keystroke path:
  never block on MLX/RAG

First visible AI candidate:
  memory/cache/short MLX lane first

Richer candidates:
  refresh later only if session still matches
```

No-input/post-commit predictions must auto-hide. They cannot stay forever.

### 6. Wanxiang Owns English And Vibe Coding

Felix's architecture keeps Wanxiang/Rime translators and Lua filters as the core input engine. For our use case this matters even more because the user writes code, paths, repo names, model names, and mixed English/Chinese.

Rules:

```text
English/code/path/URL-like input:
  Rime/Wanxiang lane dominates
  LLM/RAG lanes should be hidden, delayed, or clearly secondary

Chinese pinyin anchor:
  Rime first for anchor/fallback
  LLM/RAG first only after intent is anchored or pinyin-constrained
```

### 7. Alpha-Style Ranking And Feedback

Felix's `RimeLuaAlpha` and `docs/alpha_rerank_integration.md` show the right ranking direction:

```text
semantic_score
preference_score
user_frequency_score
continuation_prior
order_prior
quality_prior
input_coverage_prior
contrastive_bonus
```

It also records user feedback:

```text
selected candidate -> positive
higher displayed candidates skipped before selected -> negative
committed text -> user frequency / preference update
```

Our SQLite ranker should copy the product behavior, not the Windows DLL implementation:

```text
accepted candidate:
  phrase_frequency += 1
  source acceptance count += 1
  selected score trace persisted

skipped higher candidates:
  skipped count += 1
  light negative feedback persisted

candidate display:
  score breakdown visible in trace/debug, not in IME panel
```

This is how "same phrase repeatedly committed naturally becomes higher frequency" should work.

### 8. RAG Is Candidate Material, Not A Paragraph Popup

Felix does not solve our RAG layer, but its candidateization and ranking architecture gives the right boundary.

RAG must be compiled into candidate spans:

```text
raw history / documents
  -> clean query from anchor and recent context
  -> retrieve FTS/vector/BM25 evidence
  -> SuggestionCompiler compresses evidence into short candidates
  -> CandidatePool ranks with LLM/memory/Rime candidates
  -> evidence stays available in trace/management view
```

RAG should not dump paragraphs into the IME candidate list.

## Mapping To This Repo

Current repo target mapping:

```text
Felix RimeWithWeasel.cpp
  -> squirrel-patches/0001-add-rag-ime-sidecar.patch
  -> rag_ime/rime_sidecar.py

Felix LLMProvider.h request types
  -> rag_ime/predictor.py
  -> rag_ime/mlx_predictor_server.py

Felix LLMProvider.cpp candidateization
  -> rag_ime/candidateization module to add / strengthen

Felix ContextHistory
  -> short-term committed context in sidecar
  -> not a replacement for SQLite/RAG evidence

Felix Alpha rerank
  -> SQLite ranker + score breakdown + feedback tables

Felix DevConsole/diagnostics
  -> trace logs, doctor scripts, later management console
```

## Development Order

### P0: Foreground IME Flow

Acceptance:

- Branded Squirrel route is installed and selectable.
- Pinyin input still works with Wanxiang/Rime.
- English/code/path input is not broken.
- LLM/RAG/memory candidates appear only in a live session.
- Candidate window auto-hides when it should.
- Number keys select only visible current-session candidates.
- Stale sidecar/model responses are discarded.
- Real foreground trace proves:

```text
sidecar_request_scheduled
sidecar_response_applied
number_key_route
side_candidate_commit
```

with matching session fingerprint.

### P1: Felix-Style MLX Candidateization

Acceptance:

- MLX uses typed request modes.
- Prompt format is copied conceptually from Wisdom-Weasel request type boundaries.
- Small model output is parsed into 2-20 character candidate spans.
- No prompt echo, numbered junk, explanation text, or raw paragraph snippets enter candidates.
- Pinyin-constrained mode respects current pinyin.
- First candidate latency is measured and traced.

### P2: Alpha-Style SQLite Ranking

Acceptance:

- Candidate rows include score breakdown.
- Accepted/skipped feedback is persisted.
- Repeated accepted phrases rise in rank.
- RAG evidence ids are attached to RAG-derived candidates.
- Debug trace can explain why a candidate appeared.

Current migrated pieces:

- `rag_ime/local_sqlite_core.py` now emits `score_breakdown` with
  `fts5 / overlap / field / pinyin / frequency / recent / vector / project /
  tag / pinned / accepted / skipped / downranked / runtimeTrace` components.
- `rag_ime/suggestion_compiler.py` passes the breakdown into suggestion
  metadata, and `displayCandidates[*].metadata.score_breakdown` exposes it to
  the sidecar/debug path.
- `rag_ime/debug_server.py` now lifts the same data into `/rime-suggest`
  `rankingDiagnostics`, cache-probe samples, and Squirrel doctor summaries, so
  RAG/LLM/memory source counts and top score components can be checked without
  enlarging the IME candidate window.
- This ports Felix Alpha's score-breakdown diagnostic idea without porting the
  Windows DLL, ONNX runtime, or Lua filter directly.

### P3: Management Console

Only after P0-P2 are usable:

- use OpenLess as a management-console reference;
- show history, memory, RAG sources, model status, ranking breakdown, and evals;
- never put this console on the keystroke path.

## Current Rule For Future Work

Before each code patch:

1. Reopen the relevant Felix source path.
2. State which Felix mechanism is being copied.
3. Patch the smallest matching module in this repo.
4. Run focused tests.
5. Verify with real Squirrel foreground behavior whenever the patch affects input flow.

OpenLess is frozen until Felix-first P0/P1/P2 are materially working.
