# Evolution Report surface design

This note records the design and interaction rules already implemented for the
standalone Web document at `/evolution-report`. It is a surface-specific guide, not a
new PAWOS product vision and not evidence that the page is installed, running,
foreground-verified, or user-accepted.

## Authority and purpose

- The production-selected render owner is
  `control-center-web/src/features/evolution-report/standalone.tsx`, which wraps
  `index.tsx`; its style owner
  is `evolution-report.css`, and numeric inputs plus formatting helpers live in
  `report-data.ts`.
- The surface is a dated reading projection of retained experiment receipts.
  The receipt and ledger filenames shown in the final section remain the
  authority for the numbers.
- The page is an experiment ledger, not a scorecard or promotional dashboard.
  Its job is to teach a beginner how the system works, show how each result was
  derived, explain Keep or Reject, and state what the evidence cannot prove.
- Retrieval quality and answer-level factual citation quality stay separate. A
  better retrieval ranking cannot be presented as a verified answer or an
  automatic promotion.

## Reading structure

The main explanation is always visible. Do not move the requested principles,
changes, effects, decisions, or evidence limits into disclosures that are
closed by default.

The page uses seven stable, ordered regions:

1. `primer` — plain-language RAG explanation, experiment roles, glossary, and
   the overall before/after contract.
2. `rag` — frozen Validation scope, baseline and candidate values, relative
   improvement calculation, change ledger, interpretation, and boundary.
3. `cloudops` — baseline facts, candidate trade-offs, Reject decision, root
   cause, calculation, and boundary.
4. `trace` — unique-root-cause counting, the eight defect rows, three
   non-counted source/test changes, overlap warning, and boundary.
5. `app` — binding failure and recovery flow, sandbox facts, change ledger, and
   production-accuracy boundary.
6. `cache` — provider-reported token table, corrected calculation, change
   ledger, and canary boundary.
7. `evidence` — authoritative filenames and the evidence-level footnote.

Each region begins with a short index, a descriptive heading, and a one-paragraph
summary. Repeated experiment details use the same sequence wherever applicable:
raw facts or comparison, calculation, `以前 / 改变 / 效果 / 判定`, explanation,
then the explicit no-overclaim boundary.

## Visual hierarchy

- The surface inherits PAWOS semantic tokens rather than defining a private
  palette or type system. The paper background and text tokens establish the
  reading plane; borders and tonal surfaces separate material without a card
  wall or ornamental elevation.
- Content is capped at `1120px` and centered. Desktop spacing uses responsive
  inline padding between `24px` and `64px`.
- The title is the dominant mark (`32px` to `56px`, tight leading and tracking,
  at most about 14 characters per line). Reading copy is constrained to roughly
  `68ch`–`76ch` so the page remains explanatory rather than dashboard-dense.
- Desktop sections use a `132px` index column, a `24px` gap, and a body inset of
  `156px`. Strong horizontal rules separate chapters; soft rules organize rows
  inside a chapter.
- Color is semantic and sparse: accent identifies structure and calculation,
  success identifies positive verified effects, danger identifies Reject or a
  prohibited inference, warning identifies the corrected cache claim, and
  muted neutral treatment identifies locked or unavailable scope.
- Numeric comparisons use tabular figures. Tables retain captions and aligned
  columns; the RAG metric rows pair the raw transition with an understated bar
  and a separately displayed relative delta.

## Interaction and responsive behavior

- The chapter navigation is a sticky row of real buttons. On the standalone
  document, buttons target stable region IDs through `scrollIntoView`; the
  legacy bounded scroll-owner branch remains covered for component tests.
  Scrolling is deliberately immediate (`behavior: auto`) so navigation does
  not add decorative motion.
- All interactive controls use a visible `2px` focus outline with a `3px`
  offset. Sections are labelled regions, process and fact groups have accessible
  names, evidence callout icons that add no text are hidden from assistive
  technology, and data tables keep semantic captions and headers.
- At a viewport/container width of `820px` or less, the five-step gate becomes a vertical
  sequence, section index and content columns collapse, the decision layout
  becomes one column, the defect ledger becomes a two-column reading
  sequence, and the App flow becomes vertical.
- At `560px` or less, inline padding becomes `18px`, title and snapshot stack,
  chapter buttons wrap, metric rows become compact two-row comparisons, four
  baseline facts become a two-by-two grid, dense ledgers become one column, and
  tables remain available through horizontal scrolling rather than destructive
  column removal.
- The only entrance motion is the RAG measurement bar (`620ms` with the shared
  standard easing). It is removed under `prefers-reduced-motion: reduce`.

## Evidence presentation rules

- Always label Validation-only, Held-out-locked, canary, sandbox, source
  candidate, installation, and foreground evidence as different levels. Never
  upgrade one level into another through wording or color.
- Keep baseline and candidate raw values next to derived percentages. Show the
  formula when the interpretation depends on relative change.
- Keep negative trade-offs visible even when another metric improves. The
  CloudOps candidate remains Reject because CA regressed and Tool calls rose,
  despite lower elapsed time and improved Top-3 JRA.
- Keep count definitions visible. The eight Trace defects are unique closed
  root causes; retry counts, test counts, the three additional source/test
  repairs, and overlapping Skill/workflow/Tool categories cannot be added to
  that total.
- Describe the SGG result as a one-fixture deterministic sandbox verification,
  not production Text-to-SQL accuracy. Preserve the zero Provider-call and
  blocked production-write facts as scope evidence.
- Preserve the cache correction: cold input `10,647`, hot input `941` and `963`,
  provider-reported `cacheRead` of `9,728`, and the recomputed reduction range
  `90.96%`–`91.16%`. The earlier `92.7%`–`92.9%` wording remains identified as a
  transcription error.
- End each experiment with a visually explicit boundary statement. The final
  evidence list names receipt files but does not turn the page itself into a
  receipt.

## Guardrails for future edits

- Do preserve the beginner-first order: explain the term and mechanism before
  asking the reader to interpret its number.
- Do keep important explanations and outcomes visible without interaction.
- Do derive displayed percentages from the stored raw inputs where helpers
  exist, and keep corrected claims adjacent to those inputs.
- Do preserve keyboard focus, semantic tables, narrow-window reflow, and reduced
  motion when adding a section.
- Do not replace the ledger with KPI cards, celebratory totals, or a single
  composite score.
- Do not use a green result or an upward delta to imply Keep, installation,
  production impact, Held-out success, or foreground acceptance.
- Do not treat this document, the requirements ledger, the source map, tests,
  screenshots, or built output as a frontend render owner or a runtime receipt.
- Do not mount the report inside System Monitor or map `/evolution-report` to a
  PAWOS App. System Monitor may only open the standalone URL.
