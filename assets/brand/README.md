# Personal Agent Workbench Visual Assets

The product mark and the companion portraits have separate jobs. The abstract
mark identifies the application; the silver-haired companion expresses roles
and runtime state inside the modern editorial-paper workspace. Runtime
portraits use close facial framing, expressive reactions, and high-contrast
role backdrops so they remain recognizable in compact timeline and
collaboration surfaces.

## Runtime Assets

- `rag-ime-icon.png`: the legacy build filename for a silver-tail orbit around an emerald working
  spark, used to build the macOS `.icns` files and derive the PWA icons. It is
  retained so existing release scripts do not need a path migration. The image
  is a product mark rather than a document glyph or role portrait, keeping app
  identity and companion identity visually distinct.
- `rag-ime-icon.svg`: the flat vector of that same mark — one crescent, one
  spark, the same `#022D3E` ground and the same full-bleed square as the PNG.
  It is the editable source; the PNG stays the release input the `.icns` build
  reads. Both files have to keep denoting one mark, so a change to either is a
  change to both.
- `macos/Shared/Assets/CompanionStates/`: tight UI crops for idle, listening,
  thinking, success, and warning states.
- `macos/Shared/Assets/CompanionStatesFull/`: matching full-body art retained as
  the character reference set and for future large presentation surfaces.

The web portraits deliberately use distinct hair silhouettes, outfits,
expressions, and contrasting graphic backdrops rather than transparency. This
keeps the four roles individually recognizable and prevents pale hair from
disappearing into light paper at 32–120 px. The primary chat companion also has
restrained state-reaction portraits so thinking, completion, and warning
states feel alive without looping mascot motion. Product chrome displays
functional local-runtime status instead of repeating either the app icon or a
companion portrait.
