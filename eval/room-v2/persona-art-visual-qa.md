# Room v2 persona art visual QA

Artifact: `eval/room-v2/wisdom-weasel-art-contact-sheet-v1.webp`

Contact-sheet order: Sol, Terra, Luna, Flash; Room/DuoAgent handoff; governed evidence timeline.

## Delivery inventory

| UI asset | Relative path | Dimensions | Bytes | SHA-256 | Intended slot |
|---|---|---:|---:|---|---|
| Sol / Future | `control-center-web/public/companions/personas/wisdom-weasel-sol-v1.webp` | 640 x 640 | 33,170 | `79e1e29cb2a7499ac7dd30abe67a559b64544e75bbeb22d7cb71f6c972798f3b` | Role card, details, Session/Room avatar |
| Terra / Present | `control-center-web/public/companions/personas/wisdom-weasel-terra-v1.webp` | 640 x 640 | 34,808 | `03ae115e9acbb9d5d812fa8cfbf3cad0f79d8cd193eeff74a564f932142ee853` | Role card, details, Session/Room avatar |
| Luna / First Meeting | `control-center-web/public/companions/personas/wisdom-weasel-luna-v1.webp` | 640 x 640 | 25,756 | `1ecff3b890ccb4171c9c61290b5268b3a42ab3ab85fdeac391c0670f409ad4e7` | Role card, details, Session/Room avatar |
| DeepSeek Flash | `control-center-web/public/companions/personas/wisdom-weasel-flash-v1.webp` | 640 x 640 | 42,436 | `36630f13593937581cf095989fc54123c5eb966d165d0e6bb2b2b6da829742f2` | Role card, details, Session/Room avatar |
| Room handoff | `control-center-web/public/companions/scenes/room-duoagent-handoff-v1.webp` | 960 x 720 | 50,044 | `9200d59edf444f03bc801c03c258dcb103620eddc9928fe0f109afe5b0d93e93` | Room empty state or onboarding |
| Evidence timeline | `control-center-web/public/companions/scenes/memory-evidence-timeline-v1.webp` | 960 x 640 | 14,526 | `aecd38532da39c66f651ac4cd42ee7f5b18ebb0c46f5ffd0139e46721e313f80` | Memory overview or empty state |

Generated runtime pack: 200,740 bytes. Contact sheet is a QA artifact and is not shipped by the control-center build.

## Visual inspection

- PASS: all four characters remain recognizable in a 320 px contact-sheet row and have strong face/ear silhouettes for circular avatar crops.
- PASS: role identity is redundant across fur, accent color, gesture, and task metaphor; it does not depend on color alone.
- PASS: the series is cohesive but the four portraits are not recolors of one image.
- PASS: no readable words, accidental pseudo-logo, watermark, or garbled text is visible.
- PASS: no microphone, speaker, headphones, speech bubble, camera, surveillance eye, TTS, or speaking-agent imagery is present.
- PASS: all characters use adult proportions and restrained technical clothing; there is no child/chibi or sexualized treatment.
- PASS: Room scene has two visibly separate work areas, one guarded central handoff, a bounded evidence artifact, and a cursor-ready public result. It does not expose a private transcript.
- PASS: Memory scene keeps most history dim and sealed; exactly three selected fragments cross the bounded gate into a compact packet and cursor result. The lock control communicates governance rather than passive collection.
- PASS: dark backgrounds retain sufficient subject separation, and no important face, ear, handoff, gate, or cursor is outside the central crop-safe area.
- PASS: all delivered files are RGB lossy WebP. Automated tests verify dimensions, bytes, hashes, and pack budgets.

## Small-size residual risk

At 28 px, the evidence gestures intentionally disappear before the face silhouette does. Runtime capability meaning must still be carried by the adjacent role name and text; the image is identity, not the only semantic label.
