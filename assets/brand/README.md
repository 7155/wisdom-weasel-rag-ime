# Personal Agent Workbench Visual Assets

The product mark and the companion portraits have separate jobs. The abstract
mark identifies the application; the silver-haired companion expresses roles
and runtime state inside the modern editorial-paper workspace. Runtime
portraits use close facial framing, expressive reactions, and high-contrast
role backdrops so they remain recognizable in compact timeline and
collaboration surfaces.

## Runtime Assets

- `paw-os-icon.png`: the current OS icon, supplied as a 1254px planetary paw
  image and retained unchanged. The Electron host selects this source through
  `build_app_icon.sh`; web `app-icon-64.png`, `app-icon-192.png` and
  `app-icon-512.png` are size exports made with `sips`. `app-icon.svg` embeds the
  192px export for browser compatibility. The PAWOS system mark and Story site
  use the same 192px image.
- `paw-macos-icon-v2.svg`: editable PAW macOS icon master, with a porcelain
  ground, blue globe, continuous inclined orbit and small guiding star.
  `paw-macos-icon-v2.png` is its retained 1024px export. The current OS uses
  `paw-os-icon.png`; adapter and individual App identities remain separate.
  Re-export this earlier design with
  `rsvg-convert --width 1024 --height 1024 assets/brand/paw-macos-icon-v2.svg --output assets/brand/paw-macos-icon-v2.png`.
- `rag-ime-icon.png`: the legacy build filename for a silver-tail orbit around an emerald working
  spark, retained for adapter builds that still select the legacy default in
  `build_app_icon.sh`. The Electron PAW host selects its native icon explicitly. The image
  is a product mark rather than a document glyph or role portrait, keeping app
  identity and companion identity visually distinct.
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
