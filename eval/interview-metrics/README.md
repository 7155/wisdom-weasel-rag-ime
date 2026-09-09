# Agent evaluation records

This directory contains structured Memory, Knowledge, Agent Lab, and Trace
evaluation data. The directory name is retained for compatibility with the
existing evaluation scripts and receipt references.

- [evidence-ledger.v1.json](evidence-ledger.v1.json) indexes datasets, metrics,
  commands, evidence levels, and successful, failed, or interrupted runs.
- [agent-experiments.v1.json](agent-experiments.v1.json) records candidate
  experiments and their evaluation conditions.
- [runs/](runs/) contains individual experiment receipts.

Run the local data checks from the repository root:

```bash
python3 scripts/check_interview_metrics.py
python3 scripts/check_interview_agent_experiments.py
python3 -m unittest tests.test_interview_metrics
```

These commands validate saved records without calling model Providers. Replaying
an experiment may require its original dataset, environment, and configured
Provider; each receipt describes its own inputs and scope.

Compare task quality before cost. Keep synthetic cases, candidate-aware
validation, held-out evaluation, source tests, and installed-product results
separate. Recorded costs are estimates unless a receipt explicitly identifies
billing data. Development diaries and presentation drafts are local-only.
