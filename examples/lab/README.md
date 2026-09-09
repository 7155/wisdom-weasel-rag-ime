# Add a Lab scene

`ExactMatchTrial` is a small, offline adapter for JSONL answer fixtures. It uses
PAW's existing `TrialAdapter.prepare/execute` contract and registration mapping;
it does not change the scheduler, cancellation or result store.

```bash
uv run --locked python -m examples.lab.exact_match
uv run --locked python -m unittest tests.test_lab_extension_example
```

The supplied three-case fixture deliberately contains one wrong answer. The job
completes with `qualityVerdict: reject` and score `2/3`; execution completion is
separate from quality acceptance.

- **Input:** a fixture filename below the root granted to the adapter. Each JSONL
  row has `actual` and `expected` strings. The example caps rows and line size.
- **Public output:** evaluator version, progress, counts and score. The resolved
  path and answer contents stay in private input; they are absent from the App API.
- **Lifetime:** the Application owns workers and must be closed by its caller.
  The adapter owns its open fixture handle and closes it before returning or
  raising. It polls cancellation between rows; a running cancellation remains
  `cancelling` until execution and cleanup finish.
- **Failure/replay:** existing Lab rules sanitize errors, persist terminal
  results and reuse a matching request identity. Reading or replaying a job
  never grants permission to rerun it. Unknown settlement remains interrupted.
- **Compatibility:** the report names `exact-match.v1`; existing job schemas and
  immutable result records are unchanged. Evolve the adapter/report contract
  explicitly if another scene needs different input or permissions.

Production registration uses the existing `eval_lab_trial_adapters` argument to
`AgentService`. An explicit mapping replaces defaults, so include every scene the
host intends to expose. The example's `main` registers one adapter directly with
`AgentLabTrialApplication` to keep it independent of the rest of the workbench.
