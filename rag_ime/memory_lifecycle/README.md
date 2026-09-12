# Memory lifecycle

This package adds import, export, source exclusion, forgetting, daily reports
and resumable projection refreshes to PAW's existing Memory tables. Canonical
content stays in `input_events`, `agent_memory_evidence` and `memory_atoms`.
Reports are derived views; imports do not approve facts or invoke a model.

Start with a database initialized through PAW's normal migration owner. Run
`python -m rag_ime.memory_lifecycle --help` for the command list, then use an
existing database with `--db PATH` and a subcommand's `--help` for its options.
Imports default to a dry run; inspect that result before adding `--commit`.
Exports contain private Memory data and belong outside the source repository.

The CLI, capture owners and Gateway share the privacy checks in `privacy.py`.
Session-only and private-context inputs are excluded before storage. Source
forgetting maintains revocations so importing an old package cannot silently
restore forgotten content.

`refresh.py` owns leased daily-report and retrieval-projection jobs. These use
the maintenance journal with `memory-refresh:` identities; the model curation
owner resumes only its separate `memory-maintenance:` jobs. The Gateway starts
the refresh worker only in the process that owns execution.

Verify the package with:

```bash
python -m unittest tests.test_memory_lifecycle tests.test_memory_lifecycle_integration
```
