# Felix Wisdom-Weasel Migration Matrix

Snapshot:
- Reference repo: `/Volumes/undo 4t/git/learnA/agent-source-projects/wisdom-weasel-felix`
- Reference commit: `3473284a14b0336d5e6a39d2dfb0ffcbdcfb5a17`
- Date: 2026-07-03

## One-Line Decision

This project should not become "Rime plus an AI popup". The stable route is:

```text
Wanxiang/Rime anchors pinyin, dictionary, English, code/path, and fallback
Prediction-first sidecar owns post-commit LLM/RAG/memory continuation
Alpha-style scoring owns frequency, feedback, top1 guard, and diagnostics
```

In other words: keep Rime as the input-method core, then add RAG and memory as first-class prediction candidates after the user has anchored intent.

## Why The Previous Iterations Failed

| User-visible failure | Root cause in our project | Felix/Wisdom-Weasel lesson |
| --- | --- | --- |
| Candidate panel stayed visible and blocked digits | Prediction candidates were treated like a persistent panel, not a live IME session | `RimeWithWeasel` binds prediction visibility to live composition/prediction state, request sequence, explicit exit, and auto-hide |
| "It feels like clipboard recall" | RAG/memory raw snippets entered the candidate list without candidateization | `LLMProvider.cpp` removes prompt echo, cuts by punctuation, prefers short spans, dedups, and diversifies |
| LLM/RAG/memory were not clearly useful | Request types and sources were blurred | `LLMRequestType` separates no-input prediction, pinyin-constrained prediction, and Rime reorder |
| Pinyin and English broke | AI lanes were allowed to override raw input/code/path behavior | Wanxiang keeps script translation, English formatting, user dictionaries, and filters inside Rime |
| Same boring words occupied the top slots | Missing frequency/preference feedback and top1 guard | Alpha rerank combines semantic, preference, user frequency, order prior, quality gates, and conservative top1 takeover |
| RAG found noisy Codex runtime snippets | Retrieval query used raw recent text instead of cleaned anchors and variants | `alpha_rerank.lua` builds filtered context, recent clauses, anchor clauses, domain-preserved context, and confidence |

## Source Lessons To Migrate Directly

### 1. Rime/Wanxiang Owns Anchor And Fallback

Felix fork uses Wanxiang's schema as the base:

- `wanxiang.schema.yaml` keeps `script_translator` as the pinyin engine.
- `table_translator@custom_phrase`, `wanxiang_english`, and `wanxiang_mixedcode` remain normal Rime translators.
- `translator/enable_user_dict: true` gives Rime's native frequency learning a real role.
- `contextual_suggestions: false` is a useful warning: Rime's statistical phrase prediction and LLM continuation should not be mixed into one opaque mechanism.

Migration rule:

```text
First word / raw pinyin / English / code / path => Rime first
Post-commit continuation => Prediction-first LLM/RAG/memory first
Fallback and recovery => Rime always remains available
```

### 2. Display Candidates Must Be One Structured List

Felix does not let the LLM panel float independently. It builds a display list where every visible row maps back to one of:

- original Rime candidate index;
- LLM candidate pending commit;
- pending placeholder.

Migration rule:

```text
Visible slot 1..N must map to a source record.
Number/space selection must select that displayed record.
Stale/unselectable records must never consume digit keys.
```

This directly fixes the "I cannot type 1-6 when there is no input" problem.

### 3. Prediction Session Lifecycle Is A P0 Feature

Felix lifecycle mechanics:

- clear old LLM candidates on new pinyin input;
- increment request sequence to invalidate stale responses;
- exit prediction on Esc, backspace, delete, cursor movement, or incompatible input;
- auto-hide no-input prediction after a short window;
- only refresh UI when the active request still matches.

Migration rule:

```text
No live composition + no live prediction session => no candidate window.
New input => clear stale AI candidates before scheduling new work.
Late sidecar/model response => discard if request fingerprint changed.
```

### 4. LLM Provider Contract Needs Request Types

Felix's `LLMProvider` separates:

```text
NoInputPrediction
PinyinConstrainedPrediction
RimeReorder
```

Migration rule for our MLX provider:

```text
NoInputPrediction:
  input: recent committed context
  output: short continuation candidates

PinyinConstrainedPrediction:
  input: recent context + current pinyin + Rime candidates
  output: 1-3 supplemental candidates that obey the pinyin/prefix

RimeReorder:
  input: existing Rime/Wanxiang candidates + context
  output: same candidates, reordered only
```

Do not ask the small model to "do everything". It should not perform raw pinyin conversion.

### 5. Candidateization Is Separate From Generation

Useful Felix mechanisms:

- remove prompt echo before parsing;
- trim punctuation and whitespace;
- prefer short lengths such as 2, 3, 4, 5, 6, 8, 12, 16;
- reject explanations, meta text, and repeated prefixes;
- stream partial candidates as soon as a valid short span appears;
- run staged branches: fastest short candidate first, richer phrase later.

Migration rule:

```text
Raw model text is never a candidate.
Only normalized, short, directly committable spans enter CandidatePool.
```

This addresses the "candidate does not look like LLM output" and "clipboard-style paragraph" feedback.

### 6. MLX Should Copy The Provider Semantics, Not The Windows Code

Felix's llama.cpp provider gets speed from:

- resident model/context;
- stable system prompt state;
- prompt/KV reuse;
- parallel short candidate sampling;
- partial candidate callback.

Our Mac route should use MLX directly:

```text
Persistent MLX worker
Stable system prompt cache if supported
Short max_new_tokens for first branch
Streaming first parsed candidate
Separate richer branches after the first candidate is visible
Capability flags in doctor output: promptCache, batchCandidates, partialCandidate
```

Do not use Ollama as the product path.

### 7. RAG Query Must Be Compiled Before Retrieval

Felix's Alpha Lua path does not embed raw context directly. It builds query variants from:

- cleaned context;
- recent tail;
- recent clauses;
- anchor clause;
- domain-preserved context;
- confidence.

Migration rule:

```text
Raw Codex/runtime text
  -> clean noise
  -> split clauses
  -> preserve domain tokens
  -> build anchored query variants
  -> FTS/BM25/vector retrieval
  -> SuggestionCompiler candidateization
```

RAG should retrieve "things that help finish the current sentence", not arbitrary recent logs.

### 8. Feedback And Frequency Are Product Features

Felix's Alpha path records:

- selected candidate as positive feedback;
- higher-ranked displayed candidates skipped before the selected row as negative feedback;
- user frequency as conservative tie-breaker;
- top1 takeover guard so low-value candidates do not replace strong Rime/Wanxiang anchors too eagerly.

Migration rule:

```text
On selection:
  selected side candidate => accepted
  displayed side candidates above it => skipped
  phrase frequency => increment
  source/rank/score/debug trace => persist
```

This is the basis for "same phrase repeatedly committed naturally becomes higher frequency".

### 9. English And Vibe Coding Need A Protected Lane

Wanxiang's `super_english.lua` handles:

- capitalization;
- smart spacing;
- URL/protocol words such as `http`, `https`, `www`, `ssh`, `file`;
- user-table English hits;
- single-letter candidate handling;
- fallback reconstruction for code-like input.

Migration rule:

```text
If input looks like English/code/path/URL:
  Rime/Wanxiang lane dominates
  LLM/RAG candidates are hidden or delayed
  digit keys must not select stale AI candidates
```

## Adapt, Do Not Copy

| Felix implementation | Mac RAG-IME adaptation |
| --- | --- |
| Windows Weasel C++ frontend | Branded Squirrel/Rime app plus sidecar candidate contract |
| Lua Alpha filter calling native DLL | Python sidecar scoring first; optional native scorer later |
| llama.cpp sequence-copy KV fork | MLX direct worker with prompt cache / partial streaming / staged branches |
| `user_preference.json` and frequency files | SQLite tables for accepts, skips, frequency, source score, evidence |
| WinHTTP/Ollama/OpenAI-compatible provider | Local MLX API or embedded worker; no Ollama product dependency |
| Wanxiang full schema bundle | Use Wanxiang dictionaries/hooks as the pinyin and English foundation |

## Do Not Migrate Now

- Windows TSF/Weasel installer code.
- Felix ASR work.
- PPT/demo assets.
- Ollama as default product backend.
- HF backend as production dependency.
- Full Alpha native DLL/Rust stack before the Python/SQLite scorer proves useful.

## Current Priority Order

### P0: Make The IME Session Correct

Acceptance:

- no candidate window when there is no live composition/prediction session;
- digits insert normally after panel hide;
- `1..9` selects the visible display candidate, not a stale internal row;
- new pinyin clears old LLM/RAG/memory candidates;
- English/code/path input is not rewritten by AI lanes;
- doctor can prove selected bundle is the current Squirrel/RAG-IME build.

### P1: Make MLX Predictions Look Like IME Candidates

Acceptance:

- MLX provider implements the three request types;
- first visible LLM candidate is a short committable phrase;
- candidateization strips prompt echo and explanations;
- model results stream into the display list without blocking Rime;
- doctor reports model path, backend, latency, first parsed candidate time, and capability flags.

### P2: Make RAG/Memory Actually Useful

Acceptance:

- RAG queries are built from cleaned anchors and domain-preserved variants;
- results are compiled into short input candidates, not raw logs;
- source labels distinguish `LLM`, `RAG`, `memory`, `Rime`;
- `Ctrl+number` or debug API can show evidence;
- accepted/skipped feedback updates frequency and ranking.

### P3: Add Debug And Management Visibility

Acceptance:

- every candidate row can show source, score, guard reason, latency, and backend;
- a doctor command can explain why LLM/RAG/memory did or did not appear;
- later management panel can show accepted phrases, skipped candidates, retrieved evidence, and model latency.

## Test Cases To Keep Before Coding

1. `woxiang` anchors with Rime, then post-commit candidates are mostly LLM/RAG/memory.
2. `我想 sj` filters prediction candidates by pinyin and leaves Rime fallback visible.
3. `git status`, `npm run build`, `/Volumes/...`, `model_prediction` pass through as English/code/path.
4. No active input for more than the prediction timeout leaves no panel and digits type normally.
5. Selecting row 5 records rows 1-4 side candidates as skipped only if they were actually shown.
6. A repeated accepted phrase rises in rank without letting low-value words like `根据` dominate.
7. RAG over Codex history returns project-relevant candidate phrases, not tool logs or pasted stack traces.
8. MLX first parsed candidate appears before richer candidates; late stale responses are discarded.

## Reading Protocol For Future Changes

Before touching a related module:

1. Reopen the corresponding Felix file and this matrix.
2. Identify whether the change belongs to Rime/Wanxiang, display lifecycle, MLX provider, RAG compiler, or scorer.
3. Implement only that boundary.
4. Run focused tests and `git diff --check`.
5. Recheck the Felix behavior after the patch to confirm the interaction did not drift.
