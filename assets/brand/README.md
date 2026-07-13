# RAG-IME Visual Assets

The current companion is an original chibi input-method assistant. Its design
centers on a fountain pen, candidate paper, and a keyboard charm rather than a
water motif. It is inspired by the broad comedic-helper archetype only; it does
not reproduce an existing anime character, costume, symbol, or pose.

## Runtime Assets

- `rag-ime-icon.png`: close-up master used to build the macOS `.icns` files.
- `macos/Shared/Assets/CompanionStates/`: tight UI crops for idle, listening,
  thinking, success, and warning states.
- `macos/Shared/Assets/CompanionStatesFull/`: matching full-body art retained as
  the character reference set and for future large presentation surfaces.

The compact assets have transparent backgrounds and must be rendered without a
circle or status badge. Runtime state is communicated by the character pose;
system color remains available for rails, text, and accessibility contrast.
