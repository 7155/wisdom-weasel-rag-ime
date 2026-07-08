# Quarantined Template Data

This directory holds early 20k synthetic/template IME datasets and their
reports. They are kept for audit and negative-example analysis only.

Do not use these files as the primary IME completion training set. The v1 data
contract is real single-user continuation data:

- `prefix` is the already typed foreground text.
- `completion` is only the new suffix to insert.
- The completion must not echo the prefix.
- Prompt-like, assistant-like, and template-combination text is rejected.

The active seed data that is still allowed in v1 should live outside this
quarantine directory and must pass the anti-echo and prompt-leak checks.
