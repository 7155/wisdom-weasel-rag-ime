---
name: zhanggui-wenshu
description: Answer, reconcile, and explain business metrics inside the 掌柜问数 PAWOS App. Use when a Session created by 掌柜问数 asks for经营数据问答、跨表对账或指标解释. Do not use for generic coding, modifying PAWOS, or treating SGG fixture data as production business truth.
---

# 掌柜问数

Work inside the ordinary Pi Session created by the App. The selected App mode
changes presentation and the first-turn contract; it does not create a second
Agent loop or grant access to data that the Session cannot already read.

## Source Contract

1. Identify the metric, entity, time range, unit, and requested comparison.
2. Use only sources available to this Session. Keep source labels and time
   ranges beside the values they support.
3. If the necessary ledger, Knowledge base, file, or Tool is missing, say what
   is missing and stop before inventing a number.
4. SGG `fixture-v2` is a public offline self-test only. Never answer a real
   business question from that fixture unless the user explicitly asks to run
   the sandbox example.

## Modes

- **问数**: answer with the value first, then unit, time range, calculation
  basis, and evidence. Separate exact values from estimates.
- **对账**: show both sources, normalized keys/units, matched totals,
  differences, likely causes, and unresolved rows. Never silently choose one
  source as truth.
- **解释**: state the observed change, formula, evidence-backed contributors,
  alternative explanations, and what evidence would discriminate them.

Render concise Markdown. Tables are appropriate for multi-row comparisons;
one answer or one submitted conclusion stays a standalone result.

## Ask-Data Pipeline

Use the following bounded pipeline when the Session can reach structured data.
It is a clean-room PAW workflow based on the observable SGG product stages; it
does not import SGG source code or create a second LangGraph runtime.

1. Extract business keywords, metric aliases, dimensions, filters, and time
   range from the request.
2. Retrieve table, column, metric, and representative value metadata through
   the Session's authorized Knowledge, files, or database Tool. Run independent
   metadata lookups concurrently only when their Tool owner supports it.
3. Merge and filter the retrieved metadata. Keep conflicting metric definitions
   visible and ask for the user's choice when the conflict changes the answer.
4. Add current date, database dialect, unit, and reporting-calendar context.
5. Generate one read-only query. Reject multiple statements, DDL/DML, unknown
   tables or columns, and unbounded detail queries before execution.
6. Execute only through an available approved Tool. If no database execution
   Tool exists, return the proposed query and missing capability; never invent
   rows. On a real validation/execution error, make at most one evidence-based
   correction before returning the failure and Trace handoff.
7. Present the final value or table with source, unit, filters, time range and
   any caveat. Shared PAW Tool cards own progress; do not duplicate a fake
   progress state inside prose.

## Self-Test And Repair

For the registered self-test, call the installed `sandbox` Tool with
`suiteId=sgg` and `suiteRevision=fixture-v2`. Retain the SandboxRun, Trace, and
EvalRun identities. A passing fixture proves the offline contract only, not
foreground installation or real-data correctness.

When the fixture fails, hand its frozen evidence to Trace Agent. Repair only
after the candidate confirmation, inside the Extension App owner directory,
then rerun the exact same SGG revision. Do not compare scores after changing
the fixture, input fingerprint, or revision.
