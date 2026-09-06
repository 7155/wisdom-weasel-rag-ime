# Memory topic continuity — 2026-09-06

Memory curation could split an established topic into another Book when the old
Book fell outside the bounded body recall. Catalog consolidation lacked an
explicit Book merge operation, and old generated summaries could carry retired
claims forward. Recovery prompts also omitted parts of the topic rule.

## Result

- Incremental curation receives the complete compact Book identity index in
  addition to bounded bodies. Stable IDs, unique aliases and valid redirects
  preserve identity even when a Book has no semantic groups.
- A topic requires the same stable object and question or decision axis. A
  shared project, broad label, app, date or similar wording is insufficient.
  Explicit empty scope values are preserved. Ambiguous or incompatible matches
  retain the Atom without inventing a parallel Book.
- Governed catalog merges keep an existing target, current member union, source
  provenance and redirects. Projections, retrieval dependencies and rollback
  follow the same operation. Summaries are rebuilt from current members.
- Main, recovery, semantic repair and independent verification prompts retain
  the same identity rules. Invalid response text now triggers recovery instead
  of becoming an empty catalog decision; valid empty JSON remains compatible.
- An independently accepted semantic verdict with only a mistyped digest gets
  one isolated response repair. Parse failures, semantic rejection, missing
  evidence and wrong action counts cannot enter this shortcut. A persistent
  digest error remains rejected.

Existing Atom updates, explicit forgetting, manual review, configured automatic
application and rollback remain available. Age alone does not delete memory.

## Verification

The final combined installation candidate passed 195 focused tests:

```bash
python3 -m unittest tests.test_memory_curation tests.test_deepseek_memory_organizer
python3 -m unittest tests.test_memory_book_compiler tests.test_memory_projection_consistency tests.test_memory_projection_lifecycle
python3 -m unittest tests.test_owner_memory_curation tests.test_personal_memory_owner_flow tests.test_personal_memory_application tests.test_owner_memory_maintenance
```

The suites passed 50, 71 and 74 tests respectively. Additional independent checks
covered seven identity/scope cases, ten projection cases, six verifier boundaries
and nine response-parser compatibility/rejection cases.

Actual governed Luna runs used private databases and frozen inputs:

| Replay | Observed result |
| --- | --- |
| Incremental, normal path | Reused the ninth existing Book outside eight recalled bodies; retained the new Atom. |
| Catalog, normal path | Merged an existing pair, retained four original Atom rows, kept distinct-topic controls separate, repeated without a model call and rolled back. |
| Incremental recovery | After an explicitly injected malformed response, two real recovery/verifier requests selected the project Book over a similar global-scope control. |
| Catalog recovery | Real recovery, verifier and digest-repair requests preserved members, topic separation, repeat behavior and rollback. The initial malformed response was a declared fixture. |
| Recorded verifier error | One real recovery request corrected a recorded digest typo without rewriting the semantic decision. |

These are bounded behavioral checks, not an unbiased performance comparison or
a claim about every production Book. Test replays did not write production
memory. The existing background schedule was preserved.

## Self-hosting and installation boundary

Ordinary PAWOS Pi Sessions produced the source changes and regression tests. A
real Trace Agent reviewed frozen prompt/source evidence; the parent reconciled
findings, preserved an existing summary-correction change, ran independent
checks and integrated the result.

Development required recovery assistance after Runtime failures. One failure
was confirmed as a Node heap OOM during JSON serialization; compaction succeeded
but admission state prevented continuing that Session. This memory patch does
not fix that Runtime failure or establish unattended self-hosting.

The local backend was installed from the combined candidate with a truthful
dirty-source marker. All 737 installed backend files matched that candidate;
the 304-file Gateway and native frontend trees remained identical. Sidecar,
Gateway and the Session listing route passed health checks. This is local
installation evidence, not native foreground or public distribution acceptance.

The accepted project index is [O6 in OUTCOMES](../../OUTCOMES.md).
