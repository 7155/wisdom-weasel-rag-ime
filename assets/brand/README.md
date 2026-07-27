# RAG-IME Visual Assets

The current product identity uses a silver-haired, teal-eyed companion with a
modern editorial-paper workspace. Runtime portraits use role-specific
backgrounds so the face, pale hair, and persona state remain recognizable in
small navigation, timeline, and collaboration surfaces.

## Runtime Assets

- `rag-ime-icon.png`: high-contrast close-up master used to build the macOS
  `.icns` files and derive the PWA icons. Keep the face inside the central safe
  area so macOS, browser, and maskable crops preserve recognition.
- `macos/Shared/Assets/CompanionStates/`: tight UI crops for idle, listening,
  thinking, success, and warning states.
- `macos/Shared/Assets/CompanionStatesFull/`: matching full-body art retained as
  the character reference set and for future large presentation surfaces.

The web portraits deliberately include contrasting editorial backdrops rather
than transparency; this prevents pale hair from disappearing into light paper
at 22–72 px. Runtime state remains a separate UI signal and must not be baked
into the portrait.
