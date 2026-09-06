# Application delivery

An application is a versioned implementation with its own interface, method,
inputs and results. A report, download manifest or imagined preview is not an
application. Use the project's actual execution directory for its source.

Read `commandGuide.prepare_app` from the current project. The portable source
contract keeps an HTML entry, one App method in SKILL.md, explicitly selected
context files and declared operations together. The HTML can present any useful
domain interaction; the platform does not dictate the business form or output.
Give SKILL.md standard frontmatter with a lowercase hyphenated `name` and a
`description`. Put the method version in its heading and evidence; do not label
a changed method as the original baseline. Keep business instructions in the
body and avoid leaving template placeholders in the frozen method.

The HTML calls `window.pawApp.invoke(actionId, values)` and handles the returned
`text`, `usage` and optional receipt. Show input labels, loading, recoverable
errors and the resulting business content. Do not ask users to inspect JSON
unless structured data is the result they need. Handle Markdown or structured
answers without inserting untrusted model output as executable HTML.

Use actual application method and data versions. A change in the method, model
or context makes a new application version. The selected frozen version is
shared by PAW and standalone exports; source edits cannot alter an old package.
Keep measured experiment references with the project's evidence and state the
limits of comparability when the target runtime changes.

Preparation freezes and checks files. The delivery page supports actual preview,
PAW activation, version selection, rollback by activating an older version,
deactivation with records retained, and ZIP export. Invocation results come from
Pi settlement receipts. Source preparation never proves an invocation succeeded.
Use `lab_project` read with `appId` to inspect this project's frozen versions
and call summaries. Read a chosen `appCallId` for the actual input, output,
usage and settlement receipt before describing PAW execution as verified.
Standalone receipts come from that exported server; PAW receipts do not prove
the independent target ran. Keep these two target checks explicit.
The optional [delivery note](../assets/app-delivery.md) keeps each observation
with its target, version and evidence collector. Use it when several targets or
recovery checks would otherwise become mixed in the final summary. A completed
check stays completed; do not restore a generic pending checklist over its receipt.

The initial portable runtime supports declared text generation operations. It
does not provide external business writes or arbitrary local commands. If this
project needs those, preserve that requirement and choose an appropriate real
adapter or source-isolated native Extension App; do not ship a fake Tool result.

The standalone export includes a Python standard-library server and requires
an OpenAI-compatible endpoint and credentials supplied by the target environment.
Do not put credentials, local databases or machine configuration in App sources.
Open the exported package in its target environment and complete a real task
before reporting that target as verified. Report both targets separately.

The standalone runtime saves call inputs and receipts in a private local SQLite
file and never silently replays an unconfirmed call after restart. The optional
`window.pawApp.history()` returns the latest 20 receipts (`requestId`, `actionId`,
`input`, `state`, `result`, `message`). Use it when available to offer restoration
of the user's input and completed business result in the App's own interface.
Treat old-version receipts as historical results. Surface actual recoverable
errors, and preserve unknown outcomes instead of promising that no call occurred.
An invoke error may carry `state` and `requestId`. When the state is unconfirmed,
or no definite failure is known, explain that the outcome is not yet confirmed
and offer history or original-request reconciliation before a new submission.
