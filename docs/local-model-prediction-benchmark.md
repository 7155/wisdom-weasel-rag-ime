# Local Model Prediction Benchmark

RAG-IME can use a small local OpenAI-compatible model for the short prediction lane, but this lane must stay optional and aggressively bounded. The input method should keep working if the model is slow or unavailable.

## Configure A Local Model

Example for a local Qwen-compatible server:

```bash
export RAG_IME_PREDICTOR_PROVIDER=openai-compatible
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000
export RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B
export RAG_IME_PREDICTOR_PROFILE=instant
export RAG_IME_PREDICTOR_EXTRA_BODY_JSON='{"seed":7}'
```

The prompt asks for short candidates only and the provider fails open on timeout. This carries forward the Wisdom-Weasel lesson we are using as a design constraint: typing must not block on model output.

On the `/rime-suggest` hot path, the sidecar treats both RAG and model work as
budgeted optional side lanes. It budgets local RAG retrieval first, computes the
remaining `latencyBudgetMs`, and only waits that long for the model lane. Slow
RAG falls back to Rime-only or Rime/model display; a slow model returns no
`modelPredictions` for that request while Rime/RAG candidates still display.
This is separate from the provider's static transport timeout, which remains
useful for benchmark and doctor commands.

The provider is wrapped in a small failure cooldown by default:

```bash
export RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=5000
export RAG_IME_PREDICTOR_FAILURE_LATENCY_MS=250
```

If a request fails at the transport layer or returns no candidates after the failure-latency threshold, the next prediction calls are skipped until the cooldown expires. RAG candidates still run. This protects `/rime-suggest` from paying the model timeout repeatedly while a local or WSL endpoint is down. Set `RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0` only when debugging the endpoint itself.

For Qwen-style local servers, `RAG_IME_PREDICTOR_PROFILE=instant` is the recommended first test. It sets:

```text
prompt mode: chat
timeout: 350 ms
max output: 8 tokens
temperature/top_p: 0.15 / 0.85
thinking: disabled through chat_template_kwargs.enable_thinking=false
```

`RAG_IME_PREDICTOR_DISABLE_THINKING=1` can be used separately when you want custom profile settings. The parser still strips `<think>` output as a fallback, but disabling thinking at the server is faster and cleaner.

## Model Choice Note

As of 2026-07-01, the first local IME test should optimize for latency, not the newest model-family name. The Ollama `qwen3.5` library page lists small local tags that are valid candidates for this project:

- first latency smoke: `qwen3.5:0.8b`
- quality/speed middle: `qwen3.5:2b`
- upper local bound: `qwen3.5:4b`
- Mac MLX variants to try when available: `qwen3.5:0.8b-mlx`, `qwen3.5:2b-mlx`, `qwen3.5:4b-mlx`

Reference: https://ollama.com/library/qwen3.5

However, `qwen3.5` is a thinking-model line on Ollama. For IME prediction, this
is a real risk: reasoning tokens delay the first visible candidate and can
produce empty OpenAI-compatible `content`. Use `qwen3.5` only through the native
Ollama provider, which calls `/api/chat` with `think:false`.

Example Ollama route that avoids shell proxy variables during model download:

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  ollama pull qwen3.5:0.8b

env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  OLLAMA_MODELS="/Volumes/undo 4t/ollama-models" \
  ollama serve

export RAG_IME_PREDICTOR_PROVIDER=ollama
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434
export RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b
export RAG_IME_PREDICTOR_PROFILE=instant
```

Current Mac smoke result:

```json
{
  "model": "qwen3.5:0.8b",
  "provider": "local-ollama",
  "downloaded": true,
  "size": "1.0 GB",
  "doctorReadyAt1500msBudget": true,
  "observedWarmPredictionMs": "477-1157",
  "candidates": ["RAG", "智能检索", "知识图谱"]
}
```

This proves the install and adapter path. It does not prove that `qwen3.5:0.8b`
is the right production model. Its candidates are still generic for this IME
case, and observed warm latency around 0.48-1.16 s is above the desired
per-keystroke budget. The next model-quality tests should prefer non-thinking
instruction-tuned small models, especially `qwen2.5:0.5b` and `qwen2.5:1.5b`,
before spending bandwidth on larger thinking models.

### 2026-07-01 Mac Qwen3.5 0.8B Result

The first real Mac comparison used Ollama 0.30.11 with proxy variables unset and
models stored under `/Volumes/undo 4t/ollama-models`.

Downloaded models:

| Model | Local size | Format / quantization | Notes |
| --- | ---: | --- | --- |
| `qwen3.5:0.8b-mlx` | 1.2 GB | MLX / `mxfp8` | 852.88M parameters; preferred Mac TTFT smoke. |
| `qwen3.5:0.8b` | 1.0 GB | GGUF / `Q8_0` | Useful baseline, but less stable for first chunk. |

Sequential warm TTFT on the short IME prompt:

| Model | p50 first chunk | p95 first chunk | p50 total | Result |
| --- | ---: | ---: | ---: | --- |
| `qwen3.5:0.8b-mlx` | 46 ms | 213 ms | 456 ms | Best measured first-visible path; one warm sample exceeded 200 ms. |
| `qwen3.5:0.8b` | 194 ms | 2547 ms | 488 ms | Warm samples can touch 200 ms, but cold/unstable samples are too slow. |

Sequential prediction-quality eval on `docs/eval/codex-history-cases.example.jsonl`
shows that speed alone is not enough:

| Model | Pass rate | Top-1 | MRR | p50 latency | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: |
| `qwen3.5:0.8b-mlx` | 2/34 | 0.059 | 0.059 | 902 ms | 1408 ms |
| `qwen3.5:0.8b` | 4/34 | 0.059 | 0.083 | 1208 ms | 1606 ms |

Interpretation:

- `qwen3.5:0.8b-mlx` is the current best Mac smoke path for first visible model
  output. It proves that sub-200 ms TTFT is realistic on this Mac when the
  model is warm and streaming.
- Full JSON candidate completion still takes hundreds of milliseconds, so the
  IME should stream the first useful side candidate instead of waiting for a
  full response.
- Neither 0.8B model is good enough as the project-memory source. The RAG/FTS
  path must remain the source of truth for project-specific recall.
- The next backend should be a resident MLX-LM or native llama.cpp/Metal
  provider with explicit prompt/KV reuse. More prompt wording will not fix the
  main latency and quality gap by itself.

### 2026-07-01 Follow-up: Warm MLX Tag Beats GGUF/Q8

The current no-proxy local state has both models in
`/Volumes/undo 4t/ollama-models`:

| Model | Ollama id | Local size | Runner path |
| --- | --- | ---: | --- |
| `qwen3.5:0.8b-mlx` | `6a48dd9c06e3` | 1.2 GB | Ollama MLX runner |
| `qwen3.5:0.8b` | `f3817196d142` | 1.0 GB | llama-server / GGUF Q8 |

Rerun command shape:

```bash
env RAG_IME_PREDICTOR_PROVIDER=ollama \
  RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:11434 \
  RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b-mlx \
  RAG_IME_PREDICTOR_PROFILE=instant \
  RAG_IME_PREDICTOR_TIMEOUT_MS=2000 \
  RAG_IME_PREDICTOR_FAILURE_COOLDOWN_MS=0 \
  python3 -m rag_ime.cli predictor-ttft \
    --case "本地 RAG 输入法需要根据历史输入预测候选" \
    --recent-context "用户正在讨论 Mac 本地推理、Qwen3.5 0.8B、MLX、KV cache 和输入法首 token 延迟" \
    --repeat 8 \
    --latency-budget-ms 200
```

Observed on the 2026-07-01 noon rerun:

| Model | Timeout | p50 first chunk | p95 / max first chunk | p50 total | Result |
| --- | ---: | ---: | ---: | ---: | --- |
| `qwen3.5:0.8b-mlx` | 2000 ms | 124 ms | 1264 ms cold/preload sample | 888 ms | Warm samples after runner load are 76-133 ms, so this is the current fastest Mac smoke path. |
| `qwen3.5:0.8b` | 5000 ms | 296 ms | 360 ms | 1646 ms | All samples exceeded the 200 ms first-chunk budget. |

Operational notes:

- The default `instant` timeout is 350 ms. That is correct for product
  fail-open behavior, but too short for loading a cold runner; use
  `RAG_IME_PREDICTOR_TIMEOUT_MS=2000` or higher for benchmark runs.
- Ollama logs showed MLX runner cache hits after the first request, with peak
  memory around 1.1 GB for the MLX tag.
- The GGUF/Q8 route used llama-server and loaded vision/multimodal components,
  which makes it a poorer first-token path on this machine.
- The first streaming text is still often JSON syntax such as `["`, so the
  product UI should stream the first parsed useful candidate, not merely the
  first raw token.

Earlier latency fallback:

```bash
export RAG_IME_PREDICTOR_STREAM_FIRST=1
```

For native Ollama and resident MLX providers, this changes `predict()` from
"wait for complete JSON candidate list" to "return after the first parsed
candidate". The returned prediction carries
`metadata.stream_first_candidate=true` and `metadata.first_candidate_ms`. This
is a latency fallback that may return only one early model candidate. Leave the
flag unset when running model-quality evals that need all candidates. The
production direction is a resident MLX/llama.cpp backend that can return several
short inline model candidates via logits/top-k or forked decoding, while RAG
candidates fill block rows.

Current direct MLX product setting:

```bash
export RAG_IME_PREDICTOR_STREAM_FIRST=0
```

The resident MLX service now tries `candidateMode: next-token-logits` on
`/predict` before any JSON generation. It reads the first generation step's
logprobs, filters top-k Chinese token candidates, and can return several short
model candidates in one response. This is why the Squirrel panel can show a
horizontal LLM lane instead of a single streamed candidate.

Manual tryout on 2026-07-01:

| Path | Result |
| --- | --- |
| `http://127.0.0.1:8767/predict` | `candidateMode: next-token-logits`, 8 model candidates, `fallbackJson=false` |
| `http://127.0.0.1:8766/api/rime-suggest` | 8 visible candidates: 5 `model/inline` followed by 3 `rag/block` rows |
| Capability status | `batchCandidates=true`, `logitsTopK=true`, `sequenceFork=false` |

The stable rule for this project is: configure any candidate through one explicit provider lane, then accept it only if `predictor-doctor`, `predict-benchmark`, `eval-prediction`, `eval-comparison`, and the Rime sidecar latency budget pass.

For release-style checks, make TTFC part of the normal quality gate instead of
leaving it as a manual benchmark:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  quality-gate \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --force-side-candidates \
  --require-model-ttfc \
  --model-ttfc-cases-file docs/eval/ime-ttfc-cases.example.jsonl \
  --model-ttfc-provider ollama \
  --model-ttfc-base-url http://127.0.0.1:11434 \
  --model-ttfc-models qwen3.5:0.8b-mlx \
  --model-ttfc-warmup-runs 1 \
  --model-ttfc-repeat 20 \
  --model-ttfc-latency-budget-ms 200 \
  --max-model-ttfc-p95-ms 200 \
  --max-model-ttfc-over-budget-rate 0
```

This gate reuses `bench-ime-ttfc` logic and fails if the winning model has no
first parsed candidate, p95 first-candidate latency exceeds the threshold, or
any sample is over budget when the over-budget rate is set to zero.
Use `--model-ttfc-warmup-runs` only for the resident input-method path; cold
load remains a separate diagnostic because a login-started sidecar should warm
the model before per-keystroke prediction is enabled.

### 2026-07-01 Strict TTFC Follow-up

The first raw-token measurements were too optimistic for product acceptance:
they counted first model text even when the text was a JSON prefix, a half
token, or a repeat of the current input. The current TTFC path now measures the
first usable side candidate:

- non-JSON streaming text must be candidate-shaped, not a single Chinese
  character or one ASCII letter;
- candidates equal to or contained in the current input are filtered;
- missing candidates count as over-budget samples.

On the local Mac with `qwen3.5:0.8b-mlx`, this made the result more honest:

| Cases | Model | Warmup | Repeat | p50 valid candidate | p95 valid candidate | Missing valid candidates | Result |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |
| `docs/eval/ime-ttfc-cases.example.jsonl` | `qwen3.5:0.8b-mlx` | 1 | 5 | 44 ms | 62 ms | 14/20 | Fast when it produces a valid candidate, but usually repeats mixed English/Chinese input. |

Low temperature did not fix the issue. A direct `/api/generate` raw-prefix probe
was more autocomplete-like for one Chinese case, but still produced questions or
`<think>` fragments on mixed technical inputs. The engineering conclusion is:

- keep `qwen3.5:0.8b-mlx` as a Mac speed smoke model only;
- do not enable the model lane by default until candidate quality passes the
  same strict TTFC and eval gates;
- next test should compare `qwen3.5:2b-mlx` / `4b-mlx`, Qwen2.5 small
  non-thinking models, or a dedicated completion/base model;
- the final low-latency provider still needs resident prompt/KV reuse and
  stale-cancel semantics, not just prompt wording.

## Mac Runtime Order

Do not treat "local model" as one implementation. On Mac, evaluate backends in
this order:

1. **Ollama MLX tag smoke**: try `qwen3.5:0.8b-mlx` first if the tag is
   available. This checks whether Ollama's MLX packaging reduces TTFT without
   new integration code.
2. **Direct MLX-LM resident service**: if Ollama MLX is still too slow or too
   opaque, run MLX-LM directly so the project can use `stream_generate`,
   prompt cache, and first-text timing without OpenAI-compatible overhead.
3. **Native llama.cpp/Metal provider**: if direct MLX is not enough or GGUF
   support is better for the selected model, implement the Wisdom-Weasel style
   provider: stable prompt KV cache plus multi-sequence candidate sampling.
4. **Core ML / MLC LLM research**: keep these as later experiments after the
   Squirrel/Rime loop works; both can be promising but add conversion or build
   complexity.

No-proxy Ollama MLX smoke command:

```bash
env -u HTTP_PROXY -u HTTPS_PROXY -u ALL_PROXY \
  -u http_proxy -u https_proxy -u all_proxy \
  ollama pull qwen3.5:0.8b-mlx
```

Then switch only the model id:

```bash
export RAG_IME_PREDICTOR_PROVIDER=ollama
export RAG_IME_PREDICTOR_MODEL=qwen3.5:0.8b-mlx
python3 -m rag_ime.cli predictor-ttft \
  --case "RAG 输入法" \
  --recent-context "用户正在写本地记忆和候选预测" \
  --repeat 8 \
  --latency-budget-ms 200
```

For multi-case model comparison, prefer the TTFC matrix and score only after an
explicit warmup pass:

```bash
python3 -m rag_ime.cli --core-mode fixture bench-ime-ttfc \
  --cases-file docs/eval/ime-ttfc-cases.example.jsonl \
  --provider ollama \
  --base-url http://127.0.0.1:11434 \
  --models qwen3.5:0.8b-mlx,qwen3.5:0.8b \
  --warmup-runs 1 \
  --repeat 20 \
  --latency-budget-ms 200
```

If this still has p50 first candidate above 200 ms, the next work item is not
more prompt tuning. It is a resident MLX-LM or native llama.cpp provider that
can reuse prompt/KV state explicitly.

Current result: `qwen3.5:0.8b-mlx` can produce raw first text quickly, but after
strict usable-candidate filtering it misses many mixed English/Chinese technical
cases by repeating the current input. The next work item is not "find any model
that can stream quickly"; it is to keep the fast path while improving candidate
quality and avoiding current-input echoes.

Resident MLX service route:

```bash
scripts/setup_mlx_predictor_env.sh

.venv-mlx314sys/bin/python -m rag_ime.cli mlx-predictor-server \
  --model mlx-community/Qwen3-0.6B-4bit \
  --host 127.0.0.1 \
  --port 8767 \
  --prompt-cache

export RAG_IME_PREDICTOR_PROVIDER=mlx
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8767
export RAG_IME_PREDICTOR_MODEL=mlx-community/Qwen3-0.6B-4bit
export RAG_IME_PREDICTOR_PROFILE=instant

python3 -m rag_ime.cli predictor-ttft \
  --case "RAG 输入法" \
  --recent-context "用户正在写本地记忆和候选预测" \
  --repeat 8 \
  --latency-budget-ms 200
```

This service is the first concrete MLX adapter for the project. It loads MLX-LM
once, serves `/predict` and `/predict-stream`, and exposes `/v1/models` for the
existing doctor flow. `--prompt-cache` prepares the stable system-prompt cache
and stores it as a local safetensors file. Each request loads a fresh cache copy
before `generate_step` streaming, so `promptCache.usedForGeneration=true` means
the cached path was actually used for that request without polluting the shared
stable prefix.

Do not use Qwen3.5 VLM weights as the first MLX-LM target. The available
Qwen3.5 0.8B/2B MLX-community routes are image-text / `mlx-vlm` oriented, while
the current RAG-IME predictor service imports `mlx_lm`. Use
`mlx-community/Qwen3-0.6B-4bit` first and escalate to
`mlx-community/Qwen3-1.7B-4bit` only after measuring candidate quality.

Run the small-model matrix after the models are actually downloaded and the endpoint is serving:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-model-matrix \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --base-url http://127.0.0.1:11434/v1 \
  --models qwen3.5:0.8b,qwen3.5:2b,qwen3.5:4b \
  --max-candidates 3 \
  --latency-budget-ms 150
```

The command currently evaluates OpenAI-compatible `/v1` model ids. It does not
download models; use `ollama pull ...` or the equivalent WSL/MLX setup first.
For Ollama `qwen3.5`, prefer `predictor-doctor` with `RAG_IME_PREDICTOR_PROVIDER=ollama`
until the matrix command grows a native-Ollama provider option. Add `--include-cases`
when you need the full per-case failure list.

Some OpenAI-compatible servers need custom request fields or headers. Use:

```bash
export RAG_IME_PREDICTOR_EXTRA_BODY_JSON='{"extra_body_key":"value"}'
export RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON='{"X-Custom-Header":"value"}'
```

Invalid JSON is ignored so a bad optional setting does not break typing.

For a base model or a llama.cpp-compatible server that exposes `/v1/completions`, switch to the completion instant profile:

```bash
export RAG_IME_PREDICTOR_PROFILE=completion-instant
```

In this mode the provider sends `recent_context + current_input` as the prompt and requests `n=max_candidates` completions. That is closer to Wisdom-Weasel's fast base-model path than chat prompting because it avoids a repeated system instruction. It is not the same as a native llama.cpp provider with KV cache reuse; it is the portable OpenAI-compatible step before that provider exists.

## Check Model-Lane Status

Before benchmarking, check whether the model lane is configured:

```bash
python3 -m rag_ime.cli predictor-status
```

Example when no local model endpoint is configured:

```json
{
  "configured": false,
  "providerName": "NullPredictionProvider",
  "providerProfile": "none",
  "promptMode": "none"
}
```

Example after setting a Qwen-style instant profile:

```json
{
  "configured": true,
  "providerName": "local-openai-compatible",
  "providerProfile": "instant",
  "promptMode": "chat",
  "baseUrl": "http://127.0.0.1:8000",
  "model": "Qwen3-0.6B",
  "timeoutMs": 350,
  "maxTokens": 8,
  "cooldown": {
    "enabled": true,
    "cooldownMs": 5000,
    "active": false
  }
}
```

This command only checks local configuration. It does not prove that the model server is alive or returning useful candidates. Use `predict-benchmark` and `eval-prediction` for that.

## Diagnose The Endpoint

After `predictor-status` shows `configured: true`, run:

```bash
python3 -m rag_ime.cli predictor-doctor \
  --case "RAG 输入法" \
  --recent-context "用户正在写本地记忆和候选预测" \
  --latency-budget-ms 150
```

The doctor performs the checks needed before using the model in an IME side lane:

- config: whether `RAG_IME_PREDICTOR_*` is set;
- models endpoint: whether `/v1/models` responds, which ids it lists, and whether the configured model id is present;
- prediction: whether one short request returns parsed candidates within the budget;
- local runners: whether `ollama`, `llama-server`, `lmstudio`, or `mlx_lm.server` are visible in `PATH`.

Example failure on a machine with no configured model:

```json
{
  "schemaVersion": "rag-ime.predictor-doctor.v1",
  "ready": false,
  "summary": {
    "configured": false,
    "endpointReachable": false,
    "hasCandidates": false,
    "withinBudget": true,
    "readyForSidecar": false
  }
}
```

`ready: true` is still not enough to enable model candidates by default. It only means the endpoint is reachable and one short request succeeded. Follow with `predict-benchmark`, `eval-prediction`, and `eval-comparison`.

## Run The Benchmark

```bash
python3 -m rag_ime.cli predict-benchmark \
  --case "RAG 输入法" \
  --case "Squirrel 候选" \
  --case "PROJECT_MEMORY_BLOCK" \
  --recent-context "用户正在写本地记忆和候选预测" \
  --max-candidates 3 \
  --latency-budget-ms 150
```

Output shape:

```json
{
  "schemaVersion": "rag-ime.predict-benchmark.v1",
  "providerName": "local-openai-compatible",
  "providerProfile": "instant",
  "providerConfigured": true,
  "summary": {
    "caseCount": 3,
    "p50LatencyMs": 80,
    "maxLatencyMs": 120,
    "allWithinBudget": true,
    "hasCandidates": true
  }
}
```

## Measure Streaming TTFT

For an input method, total response latency is not enough. The user feels the
delay until the first usable model-side candidate. Use:

```bash
python3 -m rag_ime.cli predictor-ttft \
  --case "RAG 输入法" \
  --recent-context "用户正在写本地记忆和候选预测" \
  --repeat 8 \
  --latency-budget-ms 200
```

Output shape:

```json
{
  "schemaVersion": "rag-ime.predictor-ttft.v1",
  "providerName": "local-ollama",
  "supported": true,
  "summary": {
    "p50FirstChunkMs": 240,
    "p95FirstChunkMs": 408,
    "p50FirstCandidateMs": 255,
    "p95FirstCandidateMs": 430,
    "allWithinBudget": false,
    "overBudgetCount": 8
  }
}
```

The latency budget is evaluated against `firstCandidateMs`. `firstChunkMs`
remains useful for diagnosing transport and raw streaming behavior, but raw JSON
prefixes such as `["` do not count as usable IME candidates.

The current Ollama `qwen3.5:0.8b` baseline can approach but does not reliably
meet the 200 ms target. It is useful for install smoke and TTFT measurement,
but the project should not treat it as the final low-latency provider. The
next implementation target is documented in `docs/model-ttft-kv-cache-plan.md`:
native llama.cpp or MLX with resident model, stable prompt KV/prompt cache, and
batch sampling for multiple short candidates.

## Evaluate Prediction Quality

Latency alone is not enough. The model lane must also prove that it can use the current input plus bounded local history context to produce useful candidates.

Use the same JSONL case format as Codex-history RAG evaluation:

```jsonl
{"id":"local-memory-term","query":"RAG 输入法","recentContext":"用户正在写本地记忆输入法","expectedTerms":["本地记忆"]}
{"id":"agent-hook-term","query":"首次运行注入背景","expectedTerms":["PROJECT_MEMORY_BLOCK"]}
```

Run:

```bash
python3 -m rag_ime.cli --db-path .rag-ime-data/rag-ime.sqlite \
  eval-prediction \
  --cases-file docs/eval/codex-history-cases.example.jsonl \
  --max-candidates 3 \
  --latency-budget-ms 150
```

The command calls the configured prediction provider through the same product path as `suggest-json`: `query` becomes `current_input`, `recentContext` is merged with recent committed input history, and the returned model candidates are evaluated candidate by candidate.

Report shape:

```json
{
  "schemaVersion": "rag-ime.codex-history-eval.v1",
  "metrics": {
    "top1Accuracy": 0.5,
    "meanReciprocalRank": 0.75,
    "noiseRate": 0.0
  },
  "latency": {
    "p50Ms": 82,
    "maxMs": 140
  },
  "prediction": {
    "providerName": "local-openai-compatible",
    "providerProfile": "instant",
    "providerConfigured": true,
    "maxCandidates": 3,
    "latencyBudgetMs": 150,
    "overBudgetCount": 0
  }
}
```

Use `--repeat N` to measure stability and warm-server behavior. Unlike the RAG core, the prediction provider is not cached here; repeated model calls are intentional so latency variance is visible.

## Acceptance Rule

For the Squirrel/Rime sidecar path:

- target p50 under 150 ms for cached or warm local inference;
- target useful top-1 candidates on project-specific terms before enabling the lane by default;
- no UI blocking when a request times out;
- stale responses must be discarded by request sequence on the frontend;
- MLX/RAG side candidates occupy the visible slots first when the semantic signal
  is stable; Rime candidates remain deterministic fallback rows when side lanes
  are slow, empty, or unsafe.
- short LLM candidates render with `displayLayout: inline` so they share one
  horizontal lane; RAG/memory snippets render with `displayLayout: block` so
  sentence-like material stays vertical and readable.
- Qwen-style thinking output and JSON/list output are cleaned before candidate ranking, but the preferred config should still use `RAG_IME_PREDICTOR_PROFILE=instant` or set `RAG_IME_PREDICTOR_DISABLE_THINKING=1`.

The exact model can change later. The benchmark command is the stable gate.
