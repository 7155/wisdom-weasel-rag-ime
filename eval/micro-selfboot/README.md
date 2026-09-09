# Small-task Agent evaluation

[tasks.v1.json](tasks.v1.json) defines bounded tasks for testing Agent execution,
continuation, collaboration, and application export. The runner preserves task
outcomes and resource usage so unsuccessful attempts remain inspectable.

Run from the repository root with a new output directory:

```bash
python3 scripts/run_paw_micro_eval.py --output-root /tmp/paw-micro-example
python3 -m unittest tests.test_agent_lab_micro
```

Live evaluation uses configured Providers and consumes their quota:

```bash
python3 scripts/run_paw_micro_eval.py --output-root /tmp/paw-micro-live-example --live
```

Use `--help` for task selection and other runner options. Evaluate task success
and continuity before token or cost savings. Small samples and local checks do
not establish general model improvements or installed-product acceptance.
Development workboards and run narratives remain local-only.
