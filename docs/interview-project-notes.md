# RAG-IME Interview Notes

For the Chinese interview-ready difficulty summary, see `docs/interview-project-difficulties.md`.

## 30-Second Pitch

I am building a local-first RAG input method.

Traditional RAG waits until the user asks a question, then the system guesses which context to retrieve. My idea is to move retrieval into the input method: while the user is typing, the IME retrieves related personal memories and lets the user accept, skip, or expand them. That makes the input process itself a feedback loop for memory quality.

The project is based on the observation that an input method is the highest-frequency writing entry point. If it can locally recall personal context, the user gets faster writing, better Agent alignment, and a private memory system at the same time.

## Why This Is Hard

### 1. RAG Results Are Not IME Candidates

RAG retrieves chunks, paragraphs, source notes, and previous conversations. A traditional input method candidate is a short word or phrase selected by `1-9`.

The main product problem is therefore not only retrieval accuracy. It is candidateization:

```text
retrieved memory
  -> short surface candidate
  -> insert text
  -> compact evidence preview
  -> expanded source view
  -> user action feedback
```

The IME panel must stay small. It cannot show pipeline status, model names, debug JSON, or long paragraphs by default. Those belong in a debug page or expanded evidence view.

### 2. Number Keys Have Two Meanings

The input method needs both:

- normal short candidates from language prediction;
- RAG/memory candidates that may represent a sentence or paragraph.

Splitting `1-5` for words and `6-0` for memory looks simple, but it breaks muscle memory and does not scale.

The current native panel uses one shared number row:

```text
1-3: short model predictions
4-6: RAG / memory suggestions
```

This keeps number-key semantics stable while still supporting paragraph memory. The IME panel stays compact by limiting the top layer to three short model predictions and the lower layer to three RAG/memory suggestions.

### 3. Latency And GPU Memory Are Product Constraints

This system may need:

- an embedding model;
- a reranker;
- a small local LLM for short candidate compression or prediction;
- the input method process itself.

Running embedding and LLM on the same Mac GPU can be too heavy. The current practical plan is tiered:

```text
fast default:
  SQLite FTS/BM25 + local governance

better local:
  embedding / reranker when resources allow

resource split:
  embedding service on WSL notebook
  Mac keeps IME UI and local SQLite control path

optional later:
  small local LLM for candidate compression
```

This is still local-first from the product perspective if the remote machine is the user's own device and no third-party cloud receives personal input.

### 4. Memory Feedback Cannot Be Global

If the user pins a memory while typing about `FTS5`, that does not mean the same memory should always be high-ranked for unrelated queries.

The shared core should make memory actions query-aware:

- `pin` / `accept` boost more when the new query is similar to the original action query;
- `skip` / `downrank` penalize more in similar contexts;
- unrelated contexts keep only a weak signal;
- `delete` / `hide` still remove the memory from visible results.

This is closer to how an input method learns: feedback is local to an input situation, not just a global thumbs-up.

### 5. Prompt Cache Stability Matters

VCP-like memory systems can lose efficiency when injected context changes too much between turns. For an Agent hook, memory should be formatted into stable blocks:

```text
stable section order
stable reason classes
stable source identifiers
bounded preview length
volatile diagnostics kept outside the prompt
```

That increases cache hit rate and makes later evaluation easier.

## What Wisdom-Weasel Teaches

Wisdom-Weasel already proves that an IME can call an LLM for prediction.

The verified source paths are:

- `Wisdom-Weasel/RimeWithWeasel/RimeWithWeasel.cpp`: records committed text, enters LLM prediction mode, starts async prediction, drops stale results, and merges LLM candidates back into the candidate list.
- `Wisdom-Weasel/WeaselServer/LLMProvider.cpp`: OpenAI-compatible provider that asks the model to output multiple candidates in one response.
- `Wisdom-Weasel/WeaselServer/HFConstraintProvider.cpp`: local HTTP provider with `pinyin_constraints`.
- `Wisdom-Weasel/WeaselServer/LlamaCppProvider.cpp`: local llama.cpp provider with system prompt KV cache reuse and batched multi-candidate sampling.

I also checked official `rime/weasel` at `93eec2d` as the mature input-method baseline. The key separation there is:

```text
TSF / IME frontend
  -> WeaselIPC client
  -> RimeWithWeasel handler
  -> librime session
  -> serialized Context / CandidateInfo
  -> WeaselUI candidate window
```

That boundary is important for RAG-IME: RAG should be an additional candidate/evidence source, not a replacement for the mature composition engine boundary.

The relevant code path has three forms:

### OpenAI-Compatible Provider

`OpenAICompatibleProvider::PredictCandidates()` builds a prompt asking the model to return several candidates separated by spaces.

The result is parsed by finding the response content and splitting it into words.

This is simple but fragile:

- output format depends on prompt compliance;
- JSON parsing is ad hoc;
- multiple candidates are generated as one text response.

### HF Constraint Provider

`HFConstraintProvider::PredictCandidates()` sends:

```json
{
  "prompt": "history context",
  "pinyin_constraints": ["current", "input"]
}
```

The backend returns a field such as `responses`, then the provider splits it into candidates.

This is useful for pinyin-constrained generation.

### llama.cpp Provider

The most interesting implementation is `GenerateCandidatesBatch()`.

It does not simply ask the model to print five words. It:

1. caches the system prompt KV state;
2. restores that cached state for each request;
3. prefills the user prompt once;
4. copies the sequence state into multiple parallel sequences;
5. samples several candidate continuations in parallel;
6. limits each candidate to a small number of new tokens.

This is the stronger path for local IME prediction because it reduces repeated prefill cost and can produce several alternatives without serially running the model five times.

### Minimum Parity With Wisdom-Weasel

RAG-IME should at least preserve the useful Wisdom-Weasel behavior:

```text
commit text
  -> store recent context
  -> async prediction request
  -> stale request guard
  -> merge model candidates into IME panel
  -> number/click selection
  -> selected candidate becomes new context
```

The next step is not to copy its memory design. Wisdom-Weasel keeps a short in-memory recent context and compresses old history into a tiny summary. RAG-IME should go further:

```text
Wisdom-Weasel:
  recent text history + short compression

RAG-IME:
  local SQLite events
  FTS / embedding retrieval
  evidence-backed candidates
  query-aware action feedback
  stable Agent context blocks
```

The implementation lesson is that prediction must be asynchronous and cancellable. An input method cannot block keystrokes while retrieval, embedding, reranking, or model decoding is running.

### What Official Weasel Teaches

Official Weasel is useful even though it is Windows-specific.

The transferable architecture is:

- keep key event handling thin: key input is sent into the input engine, then UI is updated from a serialized context;
- keep candidate data structured: candidate text, labels, comments, current page, highlight index, and status are separate fields;
- keep UI layout separate from engine behavior: vertical, horizontal, and fullscreen candidate layouts read the same candidate structure;
- keep IPC explicit: frontend processes send commands such as process key, commit, clear, select candidate, highlight candidate, change page;
- update the candidate window from context snapshots, not from ad hoc UI state.

For our macOS route, the equivalent should be:

```text
Squirrel InputMethodKit controller
  -> librime composition engine
  -> RimeContext candidates / labels / comments
  -> async RAG/model side candidate source
  -> compact native panel
```

This avoids the main pitfall: building a one-off input box that cannot later support real Chinese composition, paging, labels, comments, inline preedit, focus changes, or app-specific quirks.

The current custom InputMethodKit app remains the prototype/debug harness. It should not become a replacement for Rime's pinyin parser or dictionary system.

## Local Small Model Route

The first model lane should optimize for keystroke latency, not general chat quality.

Current model candidates:

```text
confirmed speed baseline:
  Qwen3-0.6B, text-generation, max_new_tokens 4-12

confirmed balanced baseline:
  Qwen3-1.7B, text-generation, max_new_tokens 4-16

confirmed quality baseline:
  Qwen3-4B, text-generation, only if latency and memory are acceptable

Qwen3.5 candidates to verify:
  Qwen3.5-0.8B / 2B / 4B

The 2026-06-30 Hugging Face model API shows Qwen3.5 small repositories under the Qwen account, but the exact accessible text-only serving path still needs a local pull and benchmark.
```

The important settings for an IME are:

- disable long reasoning or verbose chat behavior;
- use text-only serving when the model card supports it;
- cap `max_new_tokens` aggressively;
- request multiple short candidates through one structured call or llama.cpp-style batch sampling;
- keep the system prompt stable to preserve KV/cache reuse;
- benchmark with p50/p95 latency, not only average speed.

The first production-friendly route should be an OpenAI-compatible local server wrapper. That lets the macOS adapter call the same provider interface whether the backend is `llama.cpp`, vLLM, SGLang, Ollama, or a later custom batch sampler.

If both embedding and a small LLM exceed Mac resources, the fallback architecture is:

```text
Mac:
  IME UI
  SQLite event store
  FTS/BM25 fallback
  optional 0.8B/2B predictor

user-owned WSL machine:
  embedding or rerank service
  optional heavier model experiments
```

## Our Architecture

```text
macOS InputMethodKit adapter
  -> compact AppKit candidate panel
  -> Python/JSON bridge
  -> local SQLite or shared RAG memory core
  -> InputSuggestion compiler
  -> memory action feedback
  -> optional Agent context injection
```

The browser page is only a debug surface. It is not the product UI.

```text
debug page:
  inspect backend pipeline
  inspect latency
  inspect candidate payload
  test memory actions

real IME panel:
  show only small candidate UI
  no debug JSON
  no pipeline text
  no model status
```

## Differentiation From Traditional RAG

Traditional RAG:

```text
user asks question
  -> retriever guesses context
  -> Agent answers
```

RAG-IME:

```text
user is typing
  -> IME retrieves related memories
  -> user selects or rejects
  -> memory system learns from selection
  -> Agent later receives cleaner aligned context
```

The key difference is that context alignment happens during writing, not after the user hands the problem to an Agent.

## Interview Talking Points

- I did not treat retrieval chunks as UI candidates. I added an adapter layer that turns retrieved memory into input suggestions.
- I separated product UI from debug UI. The IME panel must be tiny; pipeline and latency belong in a debug page.
- I kept the system local-first, but allowed a user-owned WSL machine to run embedding when the Mac GPU is constrained.
- I studied Wisdom-Weasel's LLM provider and found the useful part: llama.cpp batch sampling with KV cache reuse.
- I used memory actions as ranking signals, but made them query-aware so feedback does not overfit globally.
- I designed the Agent hook memory block to be cache-friendly, inspired by VCP-style context reuse problems.

## Current Risks

- macOS InputMethodKit packaging and installation are still operationally fragile.
- The current local SQLite backend is a useful MVP, but the shared RAG core must replace duplicate memory logic.
- Remote embedding on a user-owned WSL machine needs clear privacy and failure-mode documentation.
- Candidate compression by a local small LLM still needs latency testing.
- Evaluation must move beyond route hit rate into source/topic goldsets and real writing scenarios.
