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

The newer no-proxy Mac MLX smoke changes the baseline:

- `qwen3.5:0.8b-mlx` is downloaded and runs through Ollama on this Mac.
- Warm sequential `predictor-ttft` reached p50 first chunk 46 ms, p95 213 ms,
  and p50 total response 456 ms on the short IME prompt.
- The ordinary `qwen3.5:0.8b` Q8 path had p50 first chunk 194 ms, but p95
  2547 ms because one sequential sample stalled badly.
- On 34 Codex-history prediction cases, both 0.8B models failed the quality
  gate: MLX passed 2/34 and Q8 passed 4/34.

So the current answer is precise: Mac can produce the first visible model token
fast enough with an MLX-tag small model, but the product cannot wait for full
JSON completion or rely on the 0.8B model for project-specific memory. The model
lane should stream one short continuation; RAG remains the source of truth.

## Mac Backend Research

Research date: 2026-07-01.

The fastest Mac path is not a single library choice. It depends on whether we
optimize for immediate experiment speed or for a final native provider that can
reuse prompt/KV state and generate several short candidates together.

### Decision Table

| Backend | Fit For RAG-IME | Why | Risk |
| --- | --- | --- | --- |
| **Ollama MLX tag** | Best immediate Mac TTFT smoke | Already reached 46 ms p50 first chunk with `qwen3.5:0.8b-mlx`; no new provider code | Opaque cache behavior; complete JSON response and quality are not enough for default IME use |
| **MLX-LM direct service** | Best next Mac latency experiment | Apple Silicon first, `stream_generate` yields streaming responses, Python API accepts `prompt_cache`, CLI supports prompt caching and rotating KV cache | Python sidecar must stay resident; must shape output as first useful candidate rather than full JSON |
| **llama.cpp native Metal provider** | Best final low-latency engineering route | Mature C/C++/Metal runtime, GGUF ecosystem, native APIs can cache system prompt state and copy KV state for multi-candidate sampling, matches Wisdom-Weasel's proven approach | More implementation work than HTTP; model architecture/GGUF support must be verified |
| **Ollama native API** | Best smoke-test route | Easy model management, `keep_alive=-1`, streaming, `think:false`; Ollama has `qwen3.5` small tags and MLX tags | Opaque caching, HTTP overhead, no direct multi-sequence KV batch control |
| **MLC LLM** | Useful research/backstop | Metal device support, OpenAI-compatible server, streaming, local/interactive/server modes, prefix-cache knobs, speculative modes | Model compilation/build pipeline is heavier than MLX/Ollama; less direct fit for IME adapter MVP |
| **Core ML stateful model** | Long-term native experiment | macOS 15 stateful prediction can persist KV-like state across calls; official docs describe LM KV-cache as a stateful-model application | Conversion/support cost is high; not the first path for Qwen3.5 0.8B/2B iteration |
| **vLLM / MiniVLLM** | Design reference only | Paged KV, prefix cache, scheduler, chunked prefill ideas are valuable | CUDA/Triton/server-throughput orientation; not directly useful for single-user Mac TTFT |

### Recommendation

Use three tiers, not one winner:

1. **Immediate benchmark**: keep `qwen3.5:0.8b-mlx` as the current Mac TTFT
   baseline. It beats the GGUF/Q8 Ollama path for first chunk on this machine.
   It should stay a smoke baseline, not the final product provider.
2. **Production fast lane**: implement a native `llama.cpp` or MLX resident
   provider that owns the loaded model and stable prompt cache. The provider
   should expose `predict_many_short_candidates()` instead of a generic chat
   API.
3. **Research lane**: keep Core ML stateful KV and MLC LLM as follow-up
   experiments after the Squirrel/Rime product loop is stable.

### Next Experiment Matrix

The next implementation experiment should be MLX-LM first, not more Ollama
prompt tuning:

| Experiment | What To Measure | Accept / Reject Signal |
| --- | --- | --- |
| Ollama MLX baseline | `stream:true`, `keep_alive`, `think:false`; record first chunk plus Ollama timing fields | Keep only as baseline if p50 first chunk stays near 50 ms but full JSON remains slow. |
| MLX-LM resident Python service | Load once, use `stream_generate`, compare prompt-cache on/off, emit first candidate text directly | Adapter/protocol now exists as `mlx-predictor-server`; accept for product only after real MLX TTFT and quality beat the Ollama baseline. |
| llama.cpp/Metal server/native provider | Metal backend, streaming, stable prompt state, eventually sequence-copy multi-candidate sampling | Accept if it can match Wisdom-Weasel-style prompt/KV reuse and produce 3-5 candidates without repeated prefill. |
| MLC/Core ML | Model conversion/server setup cost vs. TTFT gain | Defer unless MLX-LM and llama.cpp fail the 200 ms warm target. |
| MiniVLLM/vLLM concepts | Prefix cache, paged KV, scheduler metrics | Use as design reference only; do not port CUDA/Triton runtime to the Mac IME MVP. |

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

RAG-IME now has a minimal resident MLX protocol:

```text
rag-ime mlx-predictor-server
  -> loads MLX-LM model once
  -> /predict for complete candidate sets
  -> /predict-stream for TTFT measurement and first visible candidate
  -> /v1/models for existing predictor-doctor checks
```

The protocol now splits the stable instruction/schema prefix from the dynamic
Rime/RAG tail and can route generation through a cached-prefix `generate_step`
path. The remaining limitation is empirical: it still needs real-model TTFT and
quality measurement before this becomes the accepted product fast lane.

The service can already be started with `--prompt-cache`. That prepares the
stable system prompt at startup through MLX-LM's `make_prompt_cache` /
`generate_step(..., prompt_cache=cache)` path, saves it locally, and loads a
fresh prompt-cache copy for each cached streaming request. A successful cached
request reports:

```json
{
  "promptCache": {
    "enabled": true,
    "prepared": true,
    "usedForGeneration": true,
    "hits": 1,
    "misses": 0
  }
}
```

The cache is loaded per request instead of reusing the same mutable cache object.
That is slower than a native sequence-copy implementation, but it avoids
polluting the stable prefix cache while still letting us measure cached-prefix
TTFT on a real MLX model. Keep `capabilities.promptCache=false` until real-model
`predictor-ttft` and `eval-prediction` prove this path beats the uncached MLX
and Ollama baselines.

Provider status now reports explicit capability flags:

```json
{
  "capabilities": {
    "streaming": true,
    "residentModel": true,
    "promptCache": false,
    "sequenceFork": false,
    "batchCandidates": false
  }
}
```

This prevents accidental overclaiming. The current MLX service has a resident
model, streaming TTFT path, and a conservative prompt-cache generation path.
It does not yet have real-model validation, llama.cpp-style sequence fork, or
true batch-candidate sampling.

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

Read-code checkpoint:

- `RimeWithWeasel.cpp::_TriggerLLMPrediction()` uses a background thread and
  `m_llm_request_seq` to drop stale prediction results.
- `LLMProvider::PredictCandidates(context, current_input, max_candidates)` is
  the upstream provider boundary worth preserving.
- `LlamaCppProvider::PrepareSystemPrompt()` prefills the system prompt and saves
  seq-0 state.
- `LlamaCppProvider::GenerateCandidatesBatch()` restores the cached state,
  prefills the user prompt once, copies seq-0 memory to parallel sequence ids
  with `llama_memory_seq_cp`, then decodes multiple sampled tokens in one batch.

So the native llama.cpp provider should not merely ask a chat model to output a
JSON list. Its acceptance bar is capability-level: `promptCache=true`,
`sequenceFork=true`, and `batchCandidates=true`.

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

The strongest current evidence is concrete: on this Mac, `qwen3.5:0.8b-mlx`
hit 46 ms p50 first chunk in a warm sequential test, but full response and
project-memory quality still failed the gate. That makes the next problem more
interesting than "install a smaller model": preserve fast first-token behavior
while moving candidate generation to a resident cached provider and using RAG
for factual/local-memory grounding.

## 2026-07-01 Mac Validation Update

The latest local rerun keeps the same conclusion but adds a clearer operating
boundary:

- `qwen3.5:0.8b-mlx` is already present under `/Volumes/undo 4t/ollama-models`
  and runs through Ollama's MLX runner.
- With `RAG_IME_PREDICTOR_TIMEOUT_MS=2000`, the first sample paid runner load
  cost at 1264 ms, then warm first chunks landed at 76-133 ms. The eight-sample
  p50 first chunk was 124 ms.
- The ordinary `qwen3.5:0.8b` GGUF/Q8 path, even with a 5000 ms benchmark
  timeout, produced p50 first chunk 296 ms and p50 total 1646 ms.
- Direct `mlx-lm` installation was attempted in a Python 3.12 venv with proxy
  variables unset. It reached the `mlx_metal` wheel download but only advanced
  at roughly 69 kB/s, so real direct-MLX validation is still pending a better
  download path or preseeded wheel/model cache.

This makes the immediate Mac ranking:

1. **Ollama `qwen3.5:0.8b-mlx`** for current TTFT smoke and UI iteration.
2. **Direct MLX-LM resident service** once `mlx-lm` and
   `mlx-community/Qwen3.5-0.8B-4bit` can be downloaded or cached locally.
3. **Native llama.cpp/Metal provider** for the eventual Wisdom-Weasel parity
   path: prompt KV reuse plus sequence-fork multi-candidate sampling.

The remaining product problem is not "can the Mac show a token under 200 ms".
It can, on the MLX tag. The problem is to turn that into a parsed, useful
candidate without waiting 800-900 ms for full JSON and without letting the small
model replace RAG as the factual memory source.

Current implementation step:

- `RAG_IME_PREDICTOR_STREAM_FIRST=1` now makes the native Ollama and resident
  MLX providers return after the first parsed streaming candidate.
- The parser does not treat raw JSON syntax such as `["` as a candidate; it
  waits for a complete string item or a clean non-JSON candidate fragment.
- This is a side-lane latency bridge, not the final Wisdom-Weasel parity route:
  `promptCache`, `sequenceFork`, and `batchCandidates` remain separate
  capability gates for the future native provider.
