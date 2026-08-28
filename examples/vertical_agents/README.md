# Vertical Agent sandbox fixtures

These are public, deterministic scenario manifests for exercising the future
vertical-Agent builder. They are not production applications and contain no
model credentials, network calls, or real business data.

Each manifest declares the capabilities a profile is allowed to use, the RAG
and Memory checks that must be visible in its TraceEnvelope, and the sandbox
boundary under which a self-build/test run may execute. `sgg.json` and
`zhanggui-wenshu.json` intentionally share the same harness so a new vertical
profile cannot silently bypass the trace foundation.

`tests/test_vertical_agent_sandbox.py` runs both public profiles end to end in a
temporary directory: it creates a real local Knowledge base through
`RagBenchmarkSandbox`, imports the profile document, performs offline lexical
retrieval, emits a completed `TraceEnvelope`, persists a frozen ground-truth
`EvalRun`, and creates a `SandboxRun` referencing both. The Memory evidence in
this run is deliberately a `producerKind: fixture` receipt; no production
Memory store or Provider is opened.
