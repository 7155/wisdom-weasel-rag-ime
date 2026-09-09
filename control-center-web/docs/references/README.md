# PAWOS frontend references

The PAWOS frontend takes inspiration from React OS. Its desktop code is in
`src/paw-os`; shared feature owners are in `src/features`. Start development at
[CONTRIBUTING.md](../../../CONTRIBUTING.md).

## Supplied packages

| Archive | Product attribution |
| --- | --- |
| [conversation_ui_standalone.zip](packages/conversation_ui_standalone.zip) | [Conversation UI](../../src/features/conversation-ui/ATTRIBUTION.md) |
| [paw-agent-chat-ui-kit-source.zip](packages/paw-agent-chat-ui-kit-source.zip) | [Chat UI Kit](../../src/features/agent/timeline/chat-ui-kit/ATTRIBUTION.md) and [progressive Markdown](../../src/features/agent/timeline/progressive-markdown/ATTRIBUTION.md) |

These original MIT packages retain the LICENSE files inside their archives.
They moved here from the repository root without content changes. Runtime code
uses the attributed source modules, not ZIP imports. The other directories in
this folder retain their own provenance and license files.

[pawos-conversation-baseline.html](pawos-conversation-baseline.html) remains a
visual reference.
