# Model TTFT And KV Cache Plan

This note records how the upstream Wisdom-Weasel project reduces model latency
and how RAG-IME should turn that into a measurable local-Mac plan.

## Current Finding

The product goal is not just "fast total response". For an input method, the
important metric is TTFT: time to first visible candidate. The target worth
presenting in interviews is:

- first visible model-side candidate under 200 ms on a warm local Mac path;
- no UI blocking while the model is slow;
- multiple candidates produced from one model invocation;
- Rime candidates remain first, model/RAG candidates remain side candidates.

The current Ollama-native `qwen3.5:0.8b` smoke proves local integration but not
the final latency target:

- native `/api/chat`, `think:false`, streaming, model kept alive;
- observed first chunk around 240-408 ms for the normal JSON prompt;
- shorter prompt can touch about 190-230 ms, but quality becomes unreliable;
- non-streaming full candidate response is much slower and unsuitable as the
  only metric.

## Mac Backend Research

Research date: 2026-07-01.

The fastest Mac path is not a single library choice. It depends on whether we
optimize for immediate experiment speed or for a final native provider that can
reuse prompt/KV state and generate several short candidates together.

### Decision Table

| Backend | Fit For RAG-IME | Why | Risk |
| --- | --- | --- | --- |
| **MLX-LM direct service** | Best short-term Mac latency experiment | Apple Silicon first, `stream_generate` yields streaming responses, Python API accepts `prompt_cache`, CLI supports prompt caching and rotating KV cache | Python sidecar must stay resident; Qwen3.5 MLX model availability must be verified per tag |
| **llama.cpp native Metal provider** | Best final low-latency engineering route | Mature C/C++/Metal runtime, GGUF ecosystem, native APIs can cache system prompt state and copy KV state for multi-candidate sampling, matches Wisdom-Weasel's proven approach | More implementation work than HTTP; model architecture/GGUF support must be verified |
| **Ollama native API** | Best smoke-test route | Easy model management, `keep_alive=-1`, streaming, `think:false`; Ollama has `qwen3.5` small tags and MLX tags | Opaque caching, HTTP overhead, no direct multi-sequence KV batch control |
| **MLC LLM** | Useful research/backstop | Metal device support, OpenAI-compatible server, streaming, local/interactive/server modes, prefix-cache knobs, speculative modes | Model compilation/build pipeline is heavier than MLX/Ollama; less direct fit for IME adapter MVP |
| **Core ML stateful model** | Long-term native experiment | macOS 15 stateful prediction can persist KV-like state across calls; official docs describe LM KV-cache as a stateful-model application | Conversion/support cost is high; not the first path for Qwen3.5 0.8B/2B iteration |
| **vLLM / MiniVLLM** | Design reference only | Paged KV, prefix cache, scheduler, chunked prefill ideas are valuable | CUDA/Triton/server-throughput orientation; not directly useful for single-user Mac TTFT |

### Recommendation

Use three tiers, not one winner:

1. **Immediate benchmark**: test `qwen3.5:0.8b-mlx` through Ollama if available,
   then test direct MLX-LM with an MLX-compatible 0.8B/2B non-thinking model.
   This answers whether Mac MLX can beat the current Ollama GGUF baseline
   without building a native provider.
2. **Production fast lane**: implement a native `llama.cpp` or MLX resident
   provider that owns the loaded model and stable prompt cache. The provider
   should expose `predict_many_short_candidates()` instead of a generic chat
   API.
3. **Research lane**: keep Core ML stateful KV and MLC LLM as follow-up
   experiments after the Squirrel/Rime product loop is stable.

### Why MLX First For Measurement

MLX-LM is designed for Apple Silicon and exposes the primitives we need:

```text
load model once
  -> cache stable prompt/prefix
  -> stream_generate(...)
  -> record first non-empty text segment
```

Official MLX-LM docs describe:

- `stream_generate()` yielding incremental `GenerationResponse` objects;
- `prompt_cache` in the Python API;
- `mlx_lm.cache_prompt` / `--prompt-cache-file` for reused long prefixes;
- `--max-kv-size` for rotating KV cache;
- speculative decoding with a draft model.

This is closer to input-method needs than a generic OpenAI-compatible HTTP
server because we can measure first emitted text precisely and can separate the
stable prompt from the dynamic composition tail.

### Why llama.cpp Native Still Matters

Wisdom-Weasel already proves the most relevant low-level pattern with
`llama.cpp`:

```text
system prompt
  -> decode once
  -> save sequence state
dynamic input
  -> restore system state
  -> prefill only dynamic tokens
  -> copy KV state to parallel sequences
  -> sample 3-5 short candidates together
```

This is stronger than streaming alone. Streaming only exposes partial output;
KV-state reuse reduces the work before the first output. For RAG-IME, this is
the route most likely to get under 200 ms while still returning multiple
candidates.

### What MinivLLM Contributes

The user-provided `7155/MinivLLM` is a good educational vLLM reference, not the
runtime we should embed on Mac. Its useful ideas are:

- block-table based KV ownership;
- prefix-cache hashing over token blocks plus parent prefix hash;
- separate prefill and decode scheduling;
- scheduler metrics for cache hits, stale drops, and memory pressure.

Its CUDA/Triton kernels, continuous batching, CUDA graph, and tensor parallel
path target server throughput. Single-user input methods have short requests
and extremely strict TTFT; hard-porting those kernels would increase complexity
without solving the main Mac bottleneck.

## What Wisdom-Weasel Actually Does

Wisdom-Weasel does not rely on streaming. It waits for a completed candidate
set, but it makes that candidate set cheaper to generate.

### UI And Async Guard

Code path:

```text
RimeWithWeaselHandler::ProcessKeyEvent()
  -> _TriggerLLMPrediction()
  -> std::thread(...)
  -> LLMProvider::PredictCandidates(context, current_input, 5)
  -> m_current_llm_candidates
  -> _GetCandidateInfo() appends LLM candidates after Rime candidates
```

Key mechanisms:

- `_TriggerLLMPrediction()` gets recent context from `ContextHistory.GetRecentContext(50)`.
- It increments `m_llm_request_seq` for each request.
- The background thread drops stale results when its sequence is no longer the latest.
- `_GetCandidateInfo()` keeps normal Rime candidates first and appends LLM candidates after them.
- Candidate selection checks whether the selected index is before or after the Rime candidate count.

Reference files:

- `/Volumes/undo 4t/git/learnA/Wisdom-Weasel/RimeWithWeasel/RimeWithWeasel.cpp`
- `_TriggerLLMPrediction()` around line 2189.
- `_GetCandidateInfo()` around line 920.

RAG-IME already has equivalent guardrails in the Squirrel patch and sidecar:
request sequence checks, Rime-first merge, side-candidate routing, and accepted
candidate feedback.

### KV Cache

Wisdom-Weasel's native llama.cpp provider explicitly caches the system prompt
KV state:

```text
PrepareSystemPrompt(system_prompt)
  -> tokenize system prompt
  -> llama_decode(system tokens)
  -> llama_state_seq_get_data(ctx, seq=0)
  -> save m_system_state

GenerateText / GenerateCandidatesBatch
  -> llama_state_seq_set_data(ctx, saved system state, seq=0)
  -> prefill only user/context tokens
  -> sample candidates
```

Reference file:

- `/Volumes/undo 4t/git/learnA/Wisdom-Weasel/WeaselServer/LlamaCppProvider.cpp`
- `PrepareSystemPrompt()` around line 417.
- `GenerateCandidatesBatch()` around line 695.

This is stronger than ordinary HTTP model calls. It removes repeated prefill of
the stable instruction text. For an input method, stable prompt text is a large
share of the prompt, so this directly improves TTFT.

### Multiple Candidates In One Pass

Wisdom-Weasel's llama.cpp path does not ask the model to write one long string
and then split it. When `max_candidates > 1`, it calls:

```text
GenerateCandidatesBatch(system_prompt, user_prompt, n_parallel=max_candidates, max_new_tokens=4)
```

The function:

1. restores the cached system KV state into sequence 0;
2. prefills the user prompt once in sequence 0;
3. copies that memory state into multiple llama sequence ids with `llama_memory_seq_cp`;
4. samples one token for each active sequence;
5. decodes the batch of sampled tokens together;
6. repeats for a tiny token budget.

The effect is "five short candidates" with shared prefill cost instead of five
separate calls.

## What Not To Copy

- Do not make the model parse dirty raw pinyin. Rime should still produce the
  structured composition/candidate state first.
- Do not use hand-written JSON parsing or only space-delimited prompts as the
  final protocol.
- Do not treat an in-memory context buffer as RAG. RAG-IME should keep SQLite,
  source ids, action feedback, and deletability.
- Do not update UI directly from a model worker thread. Keep immutable
  responses, request fingerprints, and main-thread application.

## RAG-IME Plan

### Phase 1: Measure TTFT Correctly

Implemented:

```bash
python3 -m rag_ime.cli predictor-ttft \
  --case "RAG 输入法" \
  --recent-context "用户正在写本地记忆输入法" \
  --repeat 8 \
  --latency-budget-ms 200
```

The command measures streaming first chunk, total response, parsed candidates,
and over-budget count. It currently supports the native Ollama provider because
that is the only local provider in the repo with a streaming path.

### Phase 2: Stop Treating Ollama As The Final Fast Path

Ollama is useful for smoke tests:

- model install and local privacy are easy;
- `keep_alive=-1` can keep the model loaded;
- `/api/chat` can send `think:false`;
- streaming exposes first chunk timing.

But Ollama does not expose the llama.cpp-style multi-sequence candidate batch
API we need. It also adds HTTP/server overhead and opaque prompt cache behavior.
For the interview-grade <200 ms target, Ollama should be a baseline, not the
final fast path.

### Phase 3: Add A Native Fast Provider

Preferred implementation order:

1. **llama.cpp native/server experiment**
   - Use GGUF `Qwen3.5-0.8B` or an equivalent non-thinking small model.
   - Keep model resident.
   - Cache stable system prompt KV.
   - Use parallel sequence sampling for 3-5 candidates.
   - Return as soon as candidate surfaces are available.

2. **MLX-LM experiment**
   - Use Apple Silicon-native MLX runtime.
   - Test `mlx_lm.server` prompt cache and streaming.
   - If server prompt cache is not enough, use Python `stream_generate` or a
     small local service that owns the loaded model and cache.

3. **Speculative/MTP only after baseline**
   - Official Qwen3.5 material points to speculative decoding/MTP as an
     acceleration path, but on Mac this is secondary until the native small-model
     provider is measured.

### Phase 4: Product Integration

The input method should not wait for model completion:

```text
key event
  -> Rime candidates render immediately
  -> sidecar may return RAG/model side candidates later
  -> requestSeq/fingerprint prevents stale overwrite
  -> model candidates occupy at most one side slot by default
```

The model lane should become opportunistic:

- if TTFT <= 200 ms and candidate passes quality gates, show it;
- if slower, keep Rime/RAG only;
- if repeated slow/empty results, circuit-break model calls;
- never let model latency block normal typing.

## Interview Framing

The difficult part is not "calling a small LLM". A naive HTTP call can be
private but still too slow for an input method. The engineering trick is to
turn language-model prediction into a real-time side lane:

- deterministic Rime handles raw key decoding;
- RAG/memory handles personal context;
- the model only predicts short continuations from structured context;
- the model is resident and non-thinking;
- stable prompt KV is cached;
- multiple candidates share one prefill through parallel sequence sampling;
- stale results are dropped by request sequence;
- measured TTFT, not total response time, decides whether the model lane is
  enabled.
