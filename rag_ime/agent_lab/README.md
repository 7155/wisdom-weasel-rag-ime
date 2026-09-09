# Agent Lab module map

Lab owns task-specific evaluation and delivery. Pi owns Session execution;
Knowledge owns indexing/retrieval; `db` owns migrations and connections.
`agent_service.py` wires these owners together. Import the concrete submodule;
`__init__.py` intentionally performs no service initialization or re-exports.

| Capability | Modules |
| --- | --- |
| Projects and intake | `projects`, `project_application`, `project_materials`, `project_artifacts`, `history` |
| Trial lifecycle | `trials`, `trial_execution`, `scene_recipes` |
| Reference evaluation | `golden`, `golden_execution`, `golden_pi`, `experiments`, `cost`, `candidate_evidence`, `optimal_path` |
| Scenario adapters | `micro`, `medium`, `cloudops`, `room_comparison`, `room_merge`, `memory_trial`, `memory_pi`, `rag_trial` |
| Knowledge preparation | `knowledge`, `knowledge_data` |
| Persistent optimization experience | `optimization_knowledge`, `optimization_distillation` |
| Application delivery | `apps`, `app_sources`, `app_assets`, `app_runtime`, `app_knowledge_runtime` |

`app_sources` freezes explicitly selected application files and exports the
standard-library `app_runtime` as `app.py`. Its frontend resources come from
`control-center-web/.generated/portable-agent-ui`, built from the shared
`features/agent/portable` controls. Knowledge exports copy the existing
`knowledge_library` owner and the standalone `app_knowledge_runtime` adapter.
These lookups resolve from this package rather than the former flat directory.

Existing `agent_lab_*` SQL names, versioned schemas and frozen evidence remain
unchanged. Historical source fingerprints describe their original revisions.

See the [offline JSONL adapter example](../../examples/lab/README.md) for a
complete registration, cancellation and cleanup check without a Provider.

Run the focused regression suite from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_agent_lab*.py'
pnpm --dir control-center-web build:app-ui
```
