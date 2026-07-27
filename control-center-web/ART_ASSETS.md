# Personal Agent Workbench art assets

## Product direction

Art identifies a long-term input-method companion; it does not fill operational whitespace.
User-confirmed input, memories, preferences, and project evidence remain the source of product
understanding. Images must never imply passive surveillance, microphone listening, TTS, or
access to private Session reasoning.

## Avatar-only contract

The production pack contains four original anime companion portraits. They are used only where
identity matters: the partner directory, Session turns, Room members, mentions, and compact brand
marks. `public/companions/manifest.json` records each shipped portrait's dimensions, byte size, and
SHA-256 digest. `tests/test_persona_art_assets.py` verifies the files rather than trusting the
manifest.

Functional empty states do not use bitmap artwork. Room, task, memory, knowledge, handoff, recovery,
and error surfaces use the shared `EmptyState` primitive with a Lucide icon, a short title, necessary
copy, and a direct action when one exists. This keeps work surfaces quiet, spacious, and consistent
with the Cafe interaction model without turning blank panels into illustration galleries.

## Delivery rules

- Keep portrait assets under `public/companions/personas/`.
- Do not add `public/companions/scenes/` or a scene resolver for functional empty states.
- Add a bitmap only after a durable identity slot exists; use icons and layout for controls and state.
- Keep each portrait below the manifest budget and the complete shipped pack below its total budget.
- Source generation files and contact sheets are not bundled with the application.
- Voice is input-only; no image may imply that Agents or Rooms speak aloud.

## Runtime integration

Use `resolvePersonaAsset()` for partner imagery. The TypeScript registry owns runtime lookup while the
JSON manifest remains the packaging and audit contract; render code does not fetch the manifest.

```tsx
<PersonaAvatar persona={persona} presence="thinking" />
```
