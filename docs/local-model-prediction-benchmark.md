# Local Model Prediction Benchmark

RAG-IME can use a small local OpenAI-compatible model for the short prediction lane, but this lane must stay optional and aggressively bounded. The input method should keep working if the model is slow or unavailable.

## Configure A Local Model

Example for a local Qwen-compatible server:

```bash
export RAG_IME_PREDICTOR_PROVIDER=openai-compatible
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000
export RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B
export RAG_IME_PREDICTOR_PROMPT_MODE=chat
export RAG_IME_PREDICTOR_TIMEOUT_MS=800
export RAG_IME_PREDICTOR_MAX_TOKENS=12
export RAG_IME_PREDICTOR_EXTRA_BODY_JSON='{"seed":7,"chat_template_kwargs":{"enable_thinking":false}}'
```

The prompt asks for short candidates only and the provider fails open on timeout. This carries forward the Wisdom-Weasel lesson we are using as a design constraint: typing must not block on model output.

Some OpenAI-compatible servers need custom request fields or headers. Use:

```bash
export RAG_IME_PREDICTOR_EXTRA_BODY_JSON='{"extra_body_key":"value"}'
export RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON='{"X-Custom-Header":"value"}'
```

Invalid JSON is ignored so a bad optional setting does not break typing.

For a base model or a llama.cpp-compatible server that exposes `/v1/completions`, switch to prefix-completion mode:

```bash
export RAG_IME_PREDICTOR_PROMPT_MODE=completion
```

In this mode the provider sends `recent_context + current_input` as the prompt and requests `n=max_candidates` completions. That is closer to Wisdom-Weasel's fast base-model path than chat prompting because it avoids a repeated system instruction. It is not the same as a native llama.cpp provider with KV cache reuse; it is the portable OpenAI-compatible step before that provider exists.

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
- Rime candidates remain first, model predictions only fill spare side-candidate slots.
- Qwen-style thinking output and JSON/list output are cleaned before candidate ranking, but the preferred config should still disable thinking at the model server.

The exact model can change later. The benchmark command is the stable gate.
