# Local Model Prediction Benchmark

RAG-IME can use a small local OpenAI-compatible model for the short prediction lane, but this lane must stay optional and aggressively bounded. The input method should keep working if the model is slow or unavailable.

## Configure A Local Model

Example for a local Qwen-compatible server:

```bash
export RAG_IME_PREDICTOR_PROVIDER=openai-compatible
export RAG_IME_PREDICTOR_BASE_URL=http://127.0.0.1:8000
export RAG_IME_PREDICTOR_MODEL=Qwen3-0.6B
export RAG_IME_PREDICTOR_TIMEOUT_MS=800
export RAG_IME_PREDICTOR_MAX_TOKENS=12
```

The prompt asks for short candidates only and the provider fails open on timeout. This carries forward the Wisdom-Weasel lesson we are using as a design constraint: typing must not block on model output.

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

## Acceptance Rule

For the Squirrel/Rime sidecar path:

- target p50 under 150 ms for cached or warm local inference;
- no UI blocking when a request times out;
- stale responses must be discarded by request sequence on the frontend;
- Rime candidates remain first, model predictions only fill spare side-candidate slots.

The exact model can change later. The benchmark command is the stable gate.
