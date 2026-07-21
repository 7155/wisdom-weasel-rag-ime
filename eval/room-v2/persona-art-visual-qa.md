# Room v2 original anime companion art QA

Artifact: `eval/room-v2/art/anime-companion-pack-v2-contact-sheet.webp`

Contact-sheet order: Firstlight, Present, Future, Flash, Room onboarding; structured handoff, memory timeline, authorized knowledge retrieval, task acceptance, safe recovery.

The pack was generated for this product with OpenAI built-in `image_gen`. It is an original bright fantasy-comedy anime ensemble and does not use an external character reference.

## Delivery inventory

| UI asset | Relative path | Dimensions | Bytes | SHA-256 | Intended slot |
|---|---|---:|---:|---|---|
| Firstlight | `control-center-web/public/companions/personas/companion-firstlight-v2.webp` | 640 x 640 | 80,028 | `2740539c3623116521cff5052cd0b57c49dc34e954fe18ad006bf2ca8d8fff31` | Role card, details, Session/Room avatar |
| Present | `control-center-web/public/companions/personas/companion-present-v2.webp` | 640 x 640 | 89,908 | `bda60bcc300fb6854e827e1db01739e7b76b4b5c1e339dcaa58483eb3b2604c1` | Role card, details, Session/Room avatar |
| Future | `control-center-web/public/companions/personas/companion-future-v2.webp` | 640 x 640 | 83,490 | `071ef1f2119640edb8e13d1526f6331c90fbc3fc0dcbe64932c157c7cfe7a91a` | Role card, details, Session/Room avatar |
| Flash | `control-center-web/public/companions/personas/companion-flash-v2.webp` | 640 x 640 | 90,180 | `29db94d978dcc6bb5764ad45dc6b5b446ec65451a2ae4ce5dfdaf860a98cdde5` | Role card, details, Session/Room avatar |
| Room onboarding | `control-center-web/public/companions/scenes/room-ensemble-onboarding-v2.webp` | 960 x 640 | 147,394 | `46e29a6bca57b2397ad7b8a61b9fea414b880eb30ca4c450c8a71e2ad7d04cb1` | Room Posts empty state and onboarding |
| Structured handoff | `control-center-web/public/companions/scenes/room-structured-handoff-v2.webp` | 960 x 640 | 128,086 | `347b848b7433a353f6443c9d8eea801359859a3373616aa926bf47efbaa3161a` | Room execution empty state and handoff |
| Memory timeline | `control-center-web/public/companions/scenes/memory-evidence-timeline-v2.webp` | 960 x 640 | 86,918 | `5e816450437a2d40252c37845543c99076910649f5f18228fe6fceadc55f3b91` | Memory evidence empty state |
| Knowledge retrieval | `control-center-web/public/companions/scenes/knowledge-authorized-retrieval-v2.webp` | 960 x 640 | 122,098 | `35ff43e002551abad2d97842ae10653d5e4c25c88c022d9ab08cecdfef0f8157` | Knowledge library empty state |
| Task acceptance | `control-center-web/public/companions/scenes/task-evidence-acceptance-v2.webp` | 960 x 640 | 121,742 | `8ea61f5ab134cb35520cdd09f6b6d0b02107741856e474186ef4e0f7f65a2677` | Planning task empty state and acceptance |
| Safe recovery | `control-center-web/public/companions/scenes/recovery-safe-resume-v2.webp` | 960 x 640 | 126,768 | `fc48bda14f6eac0b5e73c8e22fba80d2b5e5146194f8f18174f47562e293a111` | Room runtime error and recovery |

Generated runtime pack: 1,076,612 bytes. The 223,562-byte contact sheet is a QA artifact and is not shipped by the Control Center build.

## Visual inspection

- PASS: all four partners remain recognizable in circular avatar crops through hair color, silhouette, clothing accents, and task prop; identity is not carried by color alone.
- PASS: portraits and scenes share the same bright workshop, archive, navy uniform, brass instrument, and daylight vocabulary without becoming recolors of one image.
- PASS: no animal avatar, watermark, external logo, readable pseudo-interface, microphone, speaker, headphones, TTS, or speaking-agent imagery appears.
- PASS: Room onboarding shows four distinct collaborators around one real task. Handoff visibly passes a bounded artifact from the current implementer to an independent reviewer.
- PASS: memory and knowledge scenes show selection rather than indiscriminate dumping. History and library material remain in the background while a small useful set reaches the active task.
- PASS: task acceptance separates implementation from review. Recovery contains the failure, preserves evidence and checkpoint material, and avoids a catastrophic visual state.
- PASS: important faces, hands, artifacts, and evidence remain inside the central crop-safe area at desktop and mobile sizes.
- PASS: all delivered files are RGB lossy WebP. The manifest records dimensions, byte budgets, SHA-256 hashes, intended slots, and the contact-sheet hash.

## Small-size residual risk

At 28 px, props and evidence gestures disappear before the face silhouette does. Runtime meaning therefore remains in the adjacent role name and status text; art provides identity and tone, never the only semantic label.
