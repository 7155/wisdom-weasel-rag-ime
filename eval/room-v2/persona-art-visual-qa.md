# Companion portrait asset QA

The shipped companion pack uses seven original WebP portraits generated for
Personal Agent Workbench. Runtime identity is carried by the adjacent name and
status text; the portrait supplies visual continuity and is never the only
semantic signal.

## Delivery inventory

| Companion/state | Relative path | Dimensions | Bytes | SHA-256 |
|---|---|---:|---:|---|
| 澄·初 | `control-center-web/public/companions/personas/companion-firstlight-v9.webp` | 640 x 640 | 49,330 | `25c2da7d715a2c373e5b0637b89eed896308dca992bf20661ecb528f1a98145e` |
| 澄·今 | `control-center-web/public/companions/personas/companion-present-v9.webp` | 640 x 640 | 40,648 | `d125a8558a67ec268ac33106549e60b09ca78bb7adb73907fba470c7b21f14a2` |
| 澄·远 | `control-center-web/public/companions/personas/companion-future-v9.webp` | 640 x 640 | 51,440 | `d083b1da5a7572bfb73e8e68a1ccaf666a29966f8fa1be4a93ad158a3f17affd` |
| 澄·瞬 | `control-center-web/public/companions/personas/companion-flash-v9.webp` | 640 x 640 | 42,056 | `b1ab6e92828ba20308540f9508029893ee97ebec45c0afb6673bc1815b531028` |
| 澄·今 / 思考 | `control-center-web/public/companions/personas/companion-present-thinking-v9.webp` | 640 x 640 | 39,610 | `867e037c9cc0358acf75b6c49170d134563a26182db89fad434ff51244f104ad` |
| 澄·今 / 完成 | `control-center-web/public/companions/personas/companion-present-done-v9.webp` | 640 x 640 | 39,568 | `56a553a2d559bbdfe1d7f24ad766a3cae3e2de666019c4cf25bde0be7e97478e` |
| 澄·今 / 警告 | `control-center-web/public/companions/personas/companion-present-warning-v9.webp` | 640 x 640 | 41,330 | `1f1dab2942a27cba4cbdc8c5cd1995bbfaf6f5377606dc4dc55f19bfe3e8f586` |

The unique runtime portrait pack is 303,982 bytes. The manifest references
only these files; superseded v2/v4/v5/v6 portraits are deliberately not
shipped.

## Visual inspection

- PASS: all four companions remain distinguishable in circular crops through
  hair silhouette, clothing, expression, and background contrast.
- PASS: idle, thinking, done, and warning states remain recognizable at 36 px
  and 72 px without relying on text inside the image.
- PASS: the portraits contain no watermark, external logo, readable
  pseudo-interface, microphone, speaker, or TTS imagery.
- PASS: important facial features stay inside the crop-safe area across
  desktop and mobile views.
- PASS: all files are 640 x 640 RGB lossy WebP and remain within the checked
  asset budget.

## Small-size residual risk

At 28 px, clothing details disappear before the face silhouette does. The UI
therefore keeps the companion name and status as accessible text; portrait art
never carries state or identity alone.
