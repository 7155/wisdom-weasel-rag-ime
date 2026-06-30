# RAG-IME Interview Notes

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

The current design uses a focus-layer model:

```text
default focus: short candidates
  1-0 choose short candidate

RAG focus:
  1-0 choose memory candidate

shortcut:
  Option+1..0 directly choose memory candidate
```

This keeps number-key semantics stable while still supporting paragraph memory.

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
