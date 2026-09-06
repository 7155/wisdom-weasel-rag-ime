# Project Artifact Behavior

The container understands rendering primitives, not a business schema. Each
artifact has a title, a project-defined `kind`, a `view`, its `content`, optional
summary and optional template reference. A template reference declares which
template was adapted; it is not an execution or quality receipt.

Choose the content shape for the view:

| View | Content |
| --- | --- |
| `markdown` | Markdown string; use evidence links and normal readable prose |
| `table` | `columns` with `key`/`label`, `rows` using those keys, optional caption |
| `form` | Project-defined `fields`, current `values`, optional description |
| `code` | Source string, language and optional filename |
| `html` | Self-contained HTML string, displayed in an isolated iframe |
| `json` | Any valid JSON value when a specialized view would not help |

Form fields define their own key and label. Types are `text`, `long_text`,
`number`, `boolean`, `select` and `multiselect`; selection fields supply options.
Fields may include descriptions, placeholders and required status. Choose fields
for the current user decision rather than reproducing a universal business form.

An artifact may declare actions with a unique action ID, label and natural-language
request for the project Agent. The container uses these declarations to route
user interaction with the exact artifact/version. A custom HTML view can send
`{type: 'paw.lab.artifact.action', actionId, values}` to its parent; the parent
accepts only actions declared on that artifact, and presents/sends them through
the owning Agent interaction. HTML cannot invoke privileged tools directly.

Keep HTML self-contained: no external fetch, remote scripts, parent DOM access
or credentials. JavaScript may operate on the artifact's own data and UI. For
real execution, use the declared Agent interaction and the corresponding Tool.

Read the current project revision before a command. Updating an existing
artifact also identifies its expected artifact revision. On conflict, preserve
the user's draft and reconcile with the current version; do not overwrite a
newer artifact. Reuse the exact request identity after an uncertain response.

Project navigation references real artifact IDs. Publishing a background result
does not need to change the user's current focus. A comparison or preview does
not implicitly select a candidate for delivery.
