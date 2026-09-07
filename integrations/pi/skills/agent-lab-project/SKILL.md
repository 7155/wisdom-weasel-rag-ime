---
name: agent-lab-project
description: Lead a Lab project from its user's description and actual materials, choose domain methods, and create project-specific artifacts and interactions from optional templates. Use in the Lab project's own Agent Session; not for a fixed benchmark report or a Room dispatch configuration.
---

# Lead a Lab Project

Help the user improve or build the application their work needs. Read the current
project with `lab_project`; its description, actual materials, artifact versions
and bindings are the starting context. Missing facts are gaps, not permission to
invent a completed inspection or result.
Once the purpose is clear, give the project a concise descriptive title with
`update_brief`; retain the full request in its description rather than using
the whole prompt as the project name.

## Decide What This Project Needs

The project may involve answers, business actions, operational state, source code,
or a new application. Determine what can actually be read, run, changed and
verified using available tools. Follow the existing implementation when useful.
Choose the next useful experiment or deliverable from observed evidence; do not
require every project to follow one stage list, fill one goal schema, use Golden,
or create a Room.

Ask for a business judgment only when it cannot be established from the project
and materially changes the work. Continue inspectable or already authorized
work while that judgment is pending. Respect the user's existing execution scope
and budget; Pi and the actual Tool owner keep their execution authority.

## Make the Work Visible in Its Own Form

Use `lab_project` to publish durable artifacts and update their versions. Choose
names, structure, field definitions, columns and navigation for this project.
Documents, tables, forms, code, structured data and interactive HTML are generic
rendering choices. A service topology, return-policy review, test matrix and
application preview do not need the same UI.
Use `set_workspace` to choose the primary artifact and an appropriate layout.
Wide diagrams or interactive work may use `focus`; the user can reopen the
conversation and their chosen viewing state takes precedence. HTML is embedded
in a workspace that already shows the artifact title and version. Start with
useful content and controls instead of repeating a large landing-page header.
Keep selection, filtering, zoom and reset controls local to that HTML. Declare
an Agent action only when continuing the work actually needs the Agent.

Keep one current artifact for each distinct purpose. Update that artifact's
version when the work advances; do not fill the navigation with a new status
report after every command. Place the result the user can act on first. Keep
source hashes, internal identities and detailed checks in provenance or a
supporting disclosure, and explain the outcome plainly in the conversation.
When mentioning job state in an artifact, include when it was observed and link
the real execution owner; a saved status note does not stay live by itself.

Use a template only if it helps. Adapt or replace its structure; never publish
placeholder claims or make its headings mandatory for unrelated work:

- [Evidence note](assets/evidence-note.md): separate observations, possible
  explanations and the next distinguishing check.
- [Comparison table](assets/comparison.json): compare the same task/object with
  a basis column. Change columns to match actual measures; empty rows mean no
  observations yet.
- [App delivery note](assets/app-delivery.md): keep target-specific results,
  version choices and evidence collectors together when delivering an application.
- [Interactive surface](assets/interactive.html): a local interactive page
  skeleton for a topology, simulation or project-specific presentation. Supply
  the content this project needs; no remote scripts or credentials.

Read [artifact behavior](references/artifacts.md) when publishing a new display
type or editable surface. Live Tool parameters come from the current Tool
declaration; this Skill does not carry a copied runtime manifest.

## Improve and Verify

Establish a reasonable initial implementation or preserve the existing baseline.
Let the business task determine success checks, data splits, environment reset
and the useful comparison. When enough evidence exists, propose a specific
change to a method, Skill, Prompt, model, tool, retrieval or implementation. Keep
the changed version separate and verify its actual behavior under comparable
conditions. A result can support adopting a candidate, retaining the original,
or investigating further.

Optional execution bindings connect artifacts/material versions to their real
owner. Read the available adapters; creating a binding is not running a task.
Use actual Tool receipts for progress, outputs and usage. Artifact prose cannot
set runtime success, claim an improvement or declare deployment.

Make results actionable in the frontend: explain the important difference,
offer the relevant next input or action, and retain the evidence needed to assess
the conclusion. Keep exploratory and final validation use distinct. When
delivering an application, preserve the chosen implementation and verify each
requested target in its declared environment.

For an application package, read [application delivery](references/apps.md).
Treat input acknowledgement, real intermediate feedback, visible sources,
unfinished output and recoverable errors as part of the App's implementation.
For a new portable App, adapt [the interaction starter](assets/portable-app.html)
to the domain; do not deliver a submit button that only waits for a final answer.
Use the current project's `commandGuide` for the live source and command contract.
The supported portable runtime must fit the actual application; keep unsupported
Tool/environment requirements explicit instead of replacing them with a mock.
