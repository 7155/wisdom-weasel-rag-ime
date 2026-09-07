# Memory topic continuity — 2026-09-06

Memory curation could split an established topic into another Book when the old
Book fell outside the bounded body recall. Catalog consolidation lacked an
explicit Book merge operation, and old generated summaries could carry retired
claims forward. Recovery prompts also omitted parts of the topic rule.

## Result

- Incremental curation receives the complete compact Book identity index in
  addition to bounded bodies. Stable IDs, unique aliases and valid redirects
  preserve identity even when a Book has no semantic groups.
- The Agent chooses coherent long-lived topics from current members. A Book
  can contain complementary subproblems and decisions while each Atom remains
  independently retrievable and correctable. Shared project, app, date or
  similar wording alone is insufficient. Explicit empty scope values are
  preserved; incompatible scopes remain separate.
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

## Conversation visibility and existing-topic action — 2026-09-06

Real context traces recorded context-pack counts while the conversation receipt
expected a memory-source count, so successful bootstrap recalls were hidden.
A later steer trace could also hide the original recall in the same turn.
Trace metadata now records the actual source count and bootstrap outcome; the
conversation retains the most recent meaningful receipt and distinguishes
bootstrap, compaction recall, reuse, empty results, disabled memory and failure.
Historical traces without a source count show that memory was loaded without
inventing a count or elapsed time. Source links retain whole identifiers.

The memory library defaults to active Books and keeps the historical filters.
Its existing-topic consolidation action uses the current governed catalog path,
model settings, configured application policy and rollback. It skips new source,
timeline and lexicon work so an evidence backlog does not delay catalog repair.

Verification passed 37 focused backend tests, six Session delivery regressions,
nine receipt UI tests, and 80 memory-feature and route tests. The shared Session
workspace tests also passed, including explicit memory Tool visibility. Frontend
type checking, generated contracts, project harness, import boundaries and route
ownership passed. These checks establish source behavior; installed and real
foreground acceptance require a fresh canary after installation.

## Automatic aggregation — 2026-09-07

The earlier same-question-axis rule accidentally imposed Atom-level granularity
on Books. It mostly removed duplicate topics while keeping related subtopics
fragmented. Topic granularity is an organizational choice for the Agent to make
from content, rather than a routine question for the user.

Incremental, catalog, recovery and verifier prompts now share one aggregation
contract. It permits related subproblems in a stable work area or product
capability, reuses a suitable existing Book, and preserves every current Atom,
source and scope. It does not impose a topic-count quota or merge unrelated
content under a catch-all title. The catalog digest includes the policy revision
so a changed policy reconsiders the catalog once; repeated runs under the same
policy and content still skip the model call.

The change passed 161 organizer, compiler, scheduler and owner-curation tests,
plus two focused Gateway cache regressions. These checks cover scope, member
preservation, freshness and repeat behavior; a real model run is still required
to measure the resulting topic organization.

The first production aggregation proposed 19 Book groups and passed its semantic
verifier, but four groups contained historical member references outside the
Books' authority scope. Final validation rejected the batch; a missing run ID in
the failure observation then hid the validation result. The compiler now excludes
each incompatible group with its member references recorded, while preserving
independent valid groups. Final inspection and transactional scope checks remain
in place. Atom owner and privacy fields now reach both model and verifier inputs.
Failed plans retain their own run identity and validation error; an observation
failure cannot replace the primary result or misreport a committed merge.

Replaying the frozen production decisions locally yields 15 valid groups covering
32 source Books, with four skipped groups recorded and no data mutation. Focused
regressions cover independent group application, unchanged Atoms, retained
incompatible Books, model scope fields, and failure receipts. This replay is
diagnostic evidence; production application still requires the governed Runtime.

The repaired production run applied 15 groups: active topics changed from 86 to
55, while all 636 Atom IDs, protected fact/source fields and 293 active/approved
memories remained unchanged. Each target retained the exact union of current
members from its original Book and merged sources; 31 source Books retained
their superseded history. Four incompatible groups stayed unchanged with
member-scope warnings. This is local Runtime evidence from build 1443, not a
public distribution claim.

## Conversation memory switch — 2026-09-07

The composer Tool picker already offered a Memory switch, but unrestricted
profiles overrode explicit Session choices and bootstrap only checked the global
Memory setting. The current-conversation tool preference now takes precedence
over unrestricted defaults. Memory bootstrap, compaction recall, provider context
and explicit Tool execution resolve that same preference. Turning it off filters
an existing memory pack without deleting it; restoring the default can reuse the
same pack. Global Memory controls, per-Tool permissions and required Pi tools
remain their own boundaries. The picker describes the exact behavior.

Verification passed 29 focused backend tests and three Tool picker tests,
including the enabled/disabled/default round trip in a full-trust Session,
compaction, retained context and rejected stale memory calls. Installed switch
acceptance requires a fresh foreground toggle after this source update.
