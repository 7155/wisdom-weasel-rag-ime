# Mac Local Inference Fast Path

Research date: 2026-07-01.
Latest source refresh: 2026-07-01 14:10 CST.

This document answers one product question: how should RAG-IME run a local model
on Mac so the first useful model-side candidate can appear fast enough for an
input method?

## Short Answer

Use a tiered path:

1. **Current fastest measured debug path**: Ollama `qwen3.5:0.8b-mlx`, native
   Ollama API, `think:false`, `keep_alive`, streaming, and
   `RAG_IME_PREDICTOR_STREAM_FIRST=1`. This is the fastest path already proven
   on this Mac, but it is a smoke/debug route rather than the final inference
   kernel.
2. **Next product experiment**: direct resident MLX-LM service using
   `stream_generate`, stable-prompt cache isolation, and first parsed candidate
   emission.
3. **Final Wisdom-Weasel parity path**: native `llama.cpp`/Metal provider with
   stable system-prompt KV reuse plus sequence-copy multi-candidate sampling.
4. **Later research**: Core ML stateful KV and MLC LLM. They are promising but
   add conversion or compile complexity before the input method loop is stable.

Do not optimize for total response time first. The metric for an input method is
**time to first useful parsed candidate** (`firstCandidateMs`), not first byte,
first raw token, or complete JSON response.

The final product should optimize two different things separately:

- **model choice**: start with the smallest non-thinking model that can produce
  useful short continuations (`qwen3.5:0.8b-mlx` for speed smoke; 2B/4B only if
  quality needs it);
- **runtime kernel**: keep the model resident, avoid cold load, reuse the stable
  prompt/KV prefix, stream the first useful candidate, cancel stale requests,
  and never wait for a complete JSON list in the active typing path.

## Source Refresh And Locked Direction

The 2026-07-01 source refresh keeps the existing ranking, but makes the
implementation boundary sharper:

| Question | Decision |
| --- | --- |
| What is fastest on this Mac today? | Use Ollama `qwen3.5:0.8b-mlx` as the current measured smoke path. It is already downloaded and has produced warm first chunks inside the 200 ms budget. |
| What should the product measure? | Measure `firstCandidateMs` / TTFC: the first parsed candidate that a user can select. Raw `firstChunkMs` is diagnostic only because the first streamed bytes can be JSON syntax or an incomplete token. |
| Is there a Qwen "Instant" model to look for? | No project decision should depend on an `Instant` model name. For Qwen3.5 small models, configure small + non-thinking + streaming + resident runner. |
| Which provider should ship first? | Ollama MLX for debug and Squirrel/RAG integration. It is the fastest way to keep the product loop moving. |
| Which provider should become the interview-grade fast path? | Native `llama.cpp`/Metal or direct MLX-LM, whichever proves lower p95 TTFC with explicit prompt/KV cache control, cancellation, and usable candidate quality. |

Primary-source implications:

- MLX-LM exposes the primitives we need for a Mac experiment:
  `stream_generate`, `prompt_cache`, `make_prompt_cache`, `max_kv_size`, and
  KV-cache quantization. This supports a resident Apple-Silicon sidecar, but
  the product still must isolate stable prompt cache from dynamic Rime/RAG
  context.
- llama.cpp is the strongest final control surface because the native path can
  own KV state, copy sequence memory, and batch multiple short candidate
  sequences. The server/OpenAI-compatible path is useful for benchmarks, but
  cannot by itself prove `sequenceFork=true` and `batchCandidates=true`.
- Ollama MLX is the best immediate baseline because it combines simple model
  management, streaming, keep-alive behavior, `think:false`, and Apple-Silicon
  MLX packaging. Its cache behavior is intentionally treated as opaque.
- MLC LLM and Core ML stateful models remain research lanes. They may become
  useful if MLX-LM and llama.cpp fail the target, but they add build,
  conversion, or packaging cost before the input method loop is stable.
- MiniVLLM/vLLM should be copied as ideas only: prefix-cache hashing,
  block-table ownership, prefill/decode split, and cache-hit metrics. Their
  CUDA/Triton/throughput-server path is not the right dependency for a
  single-user Mac input method.

## Local Evidence

The project already measured both Ollama tags on this Mac with proxy variables
unset and models stored under `/Volumes/undo 4t/ollama-models`.

| Backend | Model | First-candidate result | Product meaning |
| --- | --- | ---: | --- |
| Ollama MLX runner | `qwen3.5:0.8b-mlx` | p50 first chunk 46 ms in the first smoke; later rerun p50 124 ms, warm post-load samples 76-133 ms | Best current Mac TTFT baseline. Use for UI iteration and smoke tests. |
| Ollama MLX runner | `qwen3.5:0.8b-mlx` | warm single-model `bench-ime-ttfc`: p50 `firstCandidateMs` 102 ms, p95 122 ms, with 1/12 samples over 200 ms | Best current TTFC evidence, but still needs stale-cancel and quality gates. |
| Ollama GGUF/Q8 runner | `qwen3.5:0.8b` | p50 first chunk 194 ms in one run, 296 ms in rerun; unstable cold/outlier behavior | Useful baseline, not the preferred Mac route. |
| Ollama GGUF/Q8 runner | `qwen3.5:0.8b` | warm single-model `bench-ime-ttfc`: p50 `firstCandidateMs` 241 ms, p95 397 ms, 12/12 samples over 200 ms | Too slow for the active typing lane. |
| Full JSON candidate response | same 0.8B models | hundreds of ms to more than 1 s | Too slow for per-keystroke UI. Stream the first parsed candidate instead. |
| 34-case Codex-history model eval | both 0.8B models | `qwen3.5:0.8b-mlx` passed 2/34, GGUF passed 4/34 | Small model cannot replace RAG memory. RAG remains source of truth. |

Conclusion: sub-200 ms first visible model behavior is realistic on this Mac,
but only if the model is warm, small, local, streaming, and the UI accepts the
first parsed candidate instead of waiting for a complete list.

## Ranking For This Project

| Rank | Runtime | Why it ranks here | Use now? |
| ---: | --- | --- | --- |
| 1 | Ollama MLX tag | Already downloaded and measured; easiest no-code TTFT baseline; Ollama API supports streaming, `keep_alive`, and thinking controls. | Yes, as the baseline and default smoke route. |
| 2 | Direct MLX-LM resident service | Apple Silicon-native; official Python API exposes `stream_generate`; docs include prompt caching and rotating KV cache. | Next product experiment. |
| 3 | Native `llama.cpp`/Metal provider | Best control over prompt/KV reuse and sequence-copy candidate batching; closest to Wisdom-Weasel's proven low-latency design. | Final fast provider after MLX experiment. |
| 4 | MLC LLM | Supports Metal device, local/interactive/server modes, OpenAI-style streaming, prefix-cache and speculative configuration knobs. | Keep as backup; compile pipeline is heavier. |
| 5 | Core ML stateful model | macOS 15 stateful models can keep state buffers across predictions, which maps to KV-cache style inference. | Long-term only due conversion/support cost. |
| 6 | MiniVLLM/vLLM concepts | Excellent design reference for paged KV, prefix cache, scheduler metrics. | Do not embed for Mac MVP; CUDA/Triton/server-throughput oriented. |

## Decision Refinement

Separate three questions that are easy to confuse:

1. **Fastest measured smoke path today**: Ollama `qwen3.5:0.8b-mlx`. It is
   already installed, no-proxy tested, and produces the current best local
   first-chunk numbers on this Mac.
2. **Best controllable product kernel**: native `llama.cpp`/Metal, with direct
   MLX-LM as the Apple-Silicon experiment to beat. The input method eventually
   needs cancellation, stable prompt/KV reuse, sequence-forked candidates, and
   exact streaming parse control. A general local HTTP server is convenient, but
   too opaque to prove all of those properties.
3. **Best long-term Apple-native runtime**: Core ML stateful KV, only after the
   model choice stabilizes and conversion/quantization cost is justified.

Therefore the current product decision is:

```text
Ship/debug path now:
  Ollama MLX baseline + stream-first candidate

Near-term benchmark race:
  direct MLX-LM resident service
  vs native llama.cpp/Metal resident provider

Default production kernel:
  whichever wins p95 TTFC, quality, memory, cancellation, and packaging tests
```

This slightly differs from a pure "pick llama.cpp first" answer. `llama.cpp` is
the strongest controllable kernel candidate, but the already measured Ollama MLX
path remains the fastest way to keep the Squirrel/RAG product loop moving.

## Why Ollama MLX Is The Immediate Baseline

Ollama is not the final low-level provider, but it gives the fastest path to a
real local smoke test:

- model management is simple;
- the native API streams JSON chunks;
- `keep_alive` keeps the model loaded after a request;
- thinking models can be called with `think:false`;
- `qwen3.5:0.8b-mlx` is available from Ollama's `qwen3.5` library page;
- LaunchAgent env persistence now keeps the predictor lane active after login.

No-proxy download:

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  ollama pull qwen3.5:0.8b-mlx
```

Smoke config:

```bash
export RAG_IME_PREDICTOR_PROVIDER=ollama
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434
export RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b-mlx
export RAG_IME_PREDICTOR_PROFILE=instant
export RAG_IME_PREDICTOR_TIMEOUT_MS=2000
export RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0
export RAG_IME_PREDICTOR_STREAM_FIRST=1
```

Measure:

```bash
python3 -m rag_ime.cli predictor-ttft \
  --case "本地 RAG 输入法需要根据历史输入预测候选" \
  --recent-context "用户正在讨论 Mac 本地推理、Qwen3.5 0.8B、MLX、KV cache 和输入法首 token 延迟" \
  --repeat 8 \
  --latency-budget-ms 200
```

Use the doctor before enabling the real Squirrel sidecar:

```bash
RAG_IME_DOCTOR_REQUIRE_PREDICTOR=1 \
RAG_IME_PREDICTOR_PROVIDER=ollama \
RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b-mlx \
RAG_IME_PREDICTOR_STREAM_FIRST=1 \
scripts/doctor_squirrel_integration.sh
```

## Why Direct MLX-LM Is The Next Experiment

MLX-LM is designed for Apple Silicon. The official README documents:

- `stream_generate()` for streaming generation;
- `prompt_cache` support in the Python API;
- `mlx_lm.cache_prompt` and `--prompt-cache-file`;
- rotating KV cache through `--max-kv-size`;
- wired-memory guidance for large models on macOS 15+.

That is exactly the set of primitives this project needs:

```text
load model once
  -> prepare stable instruction/schema prefix cache
  -> append short dynamic Rime/RAG tail
  -> stream_generate
  -> return the first parsed useful candidate
```

The current project service already exists:

```bash
python3 -m rag_ime.cli mlx-predictor-server \
  --model <mlx-compatible-small-qwen-model> \
  --host 127.0.0.1 \
  --port 8767 \
  --prompt-cache
```

Important implementation caveat: MLX-LM prompt cache objects are used by the
generation path and can be advanced/mutated during generation. RAG-IME therefore
must treat the stable prefix cache as immutable product state: copy it, reload
it from a cache file, or otherwise isolate it per request before appending
dynamic Rime/RAG context. This is why the current capability reporting should
not claim Wisdom-Weasel parity until real-model cached TTFC proves stable
behavior.

Next validation should compare:

```text
Ollama qwen3.5:0.8b-mlx
direct MLX-LM uncached streaming
direct MLX-LM stable-prefix cached streaming
```

Acceptance bar:

- p50 first parsed candidate under 150 ms;
- p95 first parsed candidate under 200 ms after warmup;
- no cold-load request in the active typing path;
- quality better than or equal to the Ollama MLX baseline on
  `docs/eval/codex-history-cases.example.jsonl`;
- memory stays low enough to run alongside SQLite/FTS and the embedding lane.

## Why `llama.cpp`/Metal Is Still The Final Fast Path

Wisdom-Weasel's most important idea is not just streaming. It makes candidate
generation cheaper:

```text
stable system prompt
  -> prefill once
  -> save seq-0 KV state
dynamic user/context prompt
  -> restore stable KV
  -> prefill dynamic tokens once
  -> copy sequence memory to N parallel sequence ids
  -> sample 3-5 short candidates in a shared batch
```

Verified local source:

- `/Volumes/undo 4t/git/learnA/Wisdom-Weasel/WeaselServer/LLMProvider.h`
  declares `PrepareSystemPrompt()` and `GenerateCandidatesBatch(...)`.
- `/Volumes/undo 4t/git/learnA/Wisdom-Weasel/WeaselServer/LlamaCppProvider.cpp`
  uses `llama_state_seq_get_data`, `llama_state_seq_set_data`, and
  `llama_memory_seq_cp`.
- `/Volumes/undo 4t/git/learnA/Wisdom-Weasel/RimeWithWeasel/RimeWithWeasel.cpp`
  runs prediction on a background thread and drops stale results with
  `m_llm_request_seq`.

Important caveat: Wisdom-Weasel is a Windows Weasel project, not a macOS
Squirrel project. We should copy the mechanisms, not the platform code. Its
batch path also uses a tiny token budget for speed, and its provider/context
concurrency boundary needs to be made explicit in our implementation. RAG-IME's
native provider should serialize or cancel in-flight context use instead of
letting multiple model workers mutate one KV context at the same time.

For RAG-IME, the native provider acceptance flags should be:

```json
{
  "residentModel": true,
  "streaming": true,
  "promptCache": true,
  "sequenceFork": true,
  "batchCandidates": true
}
```

An OpenAI-compatible HTTP server cannot prove this by itself. It can be a
benchmark target, but the final provider should expose an explicit
`predict_many_short_candidates()` contract.

The aggregate quality gate can now enforce this distinction:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  quality-gate \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --force-side-candidates \
  --require-predictor-capability promptCache \
  --require-predictor-capability sequenceFork \
  --require-predictor-capability batchCandidates
```

Use the gate without those capability requirements for smoke/debug work. Use
the capability requirements before claiming that the Mac model lane matches the
Wisdom-Weasel fast path.

## MiniVLLM Lessons

MiniVLLM is useful as a design reference, not a Mac runtime dependency.

Relevant local paths:

- `/Volumes/undo 4t/git/learnA/MinivLLM/src/myvllm/engine/block_manager.py`
- `/Volumes/undo 4t/git/learnA/MinivLLM/src/myvllm/engine/scheduler.py`
- `/Volumes/undo 4t/git/learnA/MinivLLM/src/myvllm/engine/llm_engine.py`
- `/Volumes/undo 4t/git/learnA/MinivLLM/HowToApproachvLLM_zh.md`

Borrow these ideas:

- block-based KV ownership;
- prefix-cache hash with parent-prefix hash;
- separate prefill/decode scheduling;
- cache-hit, stale-drop, and memory-pressure metrics.
- separate metrics for raw TTFT and first parsed candidate time.

Do not port these pieces directly into the Mac IME MVP:

- CUDA/Triton kernels;
- CUDA graph replay;
- server-throughput oriented continuous batching;
- multi-user scheduler complexity.

The single-user input-method workload is short, local, and latency-critical.
The useful abstraction is "reuse stable prefix and fork candidates", not "build
a Mac vLLM clone".

## Embedding And RAG Coexistence

The model lane must not starve RAG:

- Keep RAG/FTS synchronous and cheap; it is the factual memory source.
- Run embedding/rerank asynchronously or in batch when possible.
- Prefer small embedding models, FTS prefiltering, and TTL caches before paying
  vector/rerank cost.
- Use WSL or another machine for heavy batch embedding if needed, but avoid
  remote calls for per-keystroke model prediction because tens of milliseconds
  of network latency consumes too much of the 200 ms budget.
- The local model should occupy at most one model side slot by default; RAG
  candidates and Rime candidates keep the UI useful if the model lane is slow.

## Operational Rules

1. Warm the runner before typing. Cold load is not part of the typing budget.
2. Use non-thinking mode. For Ollama, send `think:false`; for chat-template
   servers, set `enable_thinking=false` or equivalent.
3. Keep output tiny. The predictor lane needs one short continuation, not a
   paragraph and not a full explanation.
4. Stream and parse incrementally. Do not display raw JSON syntax as a candidate.
5. Cache stable prompt/KV. Prompt wording alone will not solve repeated prefill.
6. Measure p50 and p95 `firstCandidateMs`, not only raw first token or total
   tokens/s.
7. Circuit-break slow/empty model results. Typing must keep working with Rime
   and RAG only.

## Qwen3.5 Small-Model Rule

Treat Qwen3.5 as a model family, not as a guarantee of instant input-method
behavior. The practical rule for this project is:

```text
qwen3.5:0.8b-mlx
  -> first Mac smoke and UI iteration

qwen3.5:2b-mlx or direct MLX-LM 2B
  -> quality/speed comparison only after the 0.8B path is stable

qwen3.5:4b or larger
  -> do not use in the active typing lane unless p95 TTFC, memory, and quality
     all pass; otherwise keep it for offline compression/rerank experiments
```

There is no need to wait for an `Instant`-named Qwen3.5 artifact. The equivalent
engineering configuration is:

```text
resident runner
non-thinking request
streaming response
max output 4-8 tokens
temperature around 0.1-0.2
stable prompt/prefix cache
RAG/Rime context kept short
```

For Ollama, this means the native provider path with `think:false`,
`keep_alive`, and `RAG_IME_PREDICTOR_STREAM_FIRST=1`. For OpenAI-compatible
or MLX-LM style servers, this means disabling thinking through the chat template
or request body and validating with `predictor-ttft`, not assuming the model card
name is enough.

## Benchmark Metrics

The benchmark should report these separately:

| Metric | Meaning | Target for active typing |
| --- | --- | --- |
| `firstChunkMs` | first raw streamed bytes from the backend | diagnostic only |
| `firstCandidateMs` / `ttfcMs` | first parsed candidate that can be selected | p50 < 150 ms, p95 < 200 ms after warmup |
| `firstUiUpdateMs` | first panel refresh after request start | p95 < 220 ms |
| `fullCandidatesMs` | all model candidates returned | debug only; can be slower |
| `retrievalMs` | FTS/RAG retrieval time | p95 < 50 ms for hot local path |
| `promptTokens` | actual prompt length | keep dynamic tail small |
| `cacheHitRate` | prompt/KV cache hit rate | should rise during repeated typing |
| `staleCancelRate` | old requests dropped after new input | expected non-zero while typing |
| `validCandidateRate` | stream chunks that produce usable candidates | high enough to avoid empty UI flashes |
| `rssMb` | resident memory | must leave room for RAG/embedding queues |
| `mainThreadBlockMs` | IME frontend blocking time | p95 < 16 ms |

Existing command today:

```bash
python3 -m rag_ime.cli predictor-ttft \
  --case "本地 RAG 输入法需要根据历史输入预测候选" \
  --recent-context "用户正在讨论 Mac 本地推理、Qwen3.5 0.8B、MLX、KV cache 和输入法首 token 延迟" \
  --repeat 20 \
  --latency-budget-ms 200
```

Multi-case model matrix:

```bash
python3 -m rag_ime.cli --core-mode fixture \
  bench-ime-ttfc \
  --cases-file docs/eval/ime-ttfc-cases.example.jsonl \
  --provider ollama \
  --base-url http://127.0.0.1:11434 \
  --models qwen3.5:0.8b-mlx,qwen3.5:2b-mlx \
  --repeat 20 \
  --latency-budget-ms 200
```

Future backend matrix should keep the same cases and report the same metrics for:

```text
ollama:qwen3.5:0.8b-mlx
mlx-lm:<small-qwen-mlx-model>
llama.cpp-metal:<same-or-comparable-gguf-model>
```

## Decision For The Next Implementation Step

The next implementation work should not be another prompt rewrite. It should be:

1. keep the Squirrel sidecar doctor coverage strict for predictor env and
   stream-first mode;
2. make direct MLX-LM installation reproducible without proxy waste;
3. run direct MLX-LM cached/uncached `predictor-ttft`;
4. implement or spike a native `llama.cpp`/Metal resident provider in parallel
   once the Squirrel loop is stable enough to consume it;
5. if MLX-LM cannot beat Ollama MLX consistently, default to the native
   `llama.cpp`/Metal provider modeled on Wisdom-Weasel's
   `PrepareSystemPrompt()` and `GenerateCandidatesBatch()`.

## Sources

- MLX-LM README: https://github.com/ml-explore/mlx-lm
- Ollama API: https://github.com/ollama/ollama/blob/main/docs/api.md
- Ollama `qwen3.5`: https://ollama.com/library/qwen3.5
- Ollama MLX preview: https://ollama.com/blog/mlx
- Ollama MLX performance: https://ollama.com/blog/mlx-performance
- Qwen3.5 0.8B model card: https://huggingface.co/Qwen/Qwen3.5-0.8B
- Qwen3.5 2B model card: https://huggingface.co/Qwen/Qwen3.5-2B
- llama.cpp server README: https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md
- llama.cpp public C API: https://github.com/ggml-org/llama.cpp/blob/master/include/llama.h
- MLC LLM REST docs: https://llm.mlc.ai/docs/deploy/rest.html
- MLC LLM CLI docs: https://llm.mlc.ai/docs/deploy/cli.html
- Core ML stateful models: https://apple.github.io/coremltools/docs-guides/source/stateful-models.html
- Apple `MLState`: https://developer.apple.com/documentation/coreml/mlstate
- vLLM automatic prefix caching: https://docs.vllm.ai/en/latest/features/automatic_prefix_caching.html
- Qwen3 technical report: https://arxiv.org/abs/2505.09388
