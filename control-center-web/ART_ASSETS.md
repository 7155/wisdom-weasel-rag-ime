# Wisdom Weasel art assets

## Product direction

The art system depicts a governed input-method companion, not an all-seeing assistant. User-confirmed input, memories, preferences, and project evidence form a timeline. A task opens a bounded gate, only the useful evidence crosses it, Agents collaborate through explicit handoffs, and the result returns to the cursor.

The images must never imply passive surveillance, microphone listening, TTS, or access to private Session reasoning. Voice input remains a separate user-controlled input surface.

## Why this pack has six generated assets

The Cat Cafe source uses four practical asset layers:

1. runtime member portraits under `packages/web/public/avatars/`;
2. a small setup-state illustration family under `packages/web/public/images/setup-cat-*.png`;
3. stateful concierge sprites under `packages/web/public/concierge/`;
4. a small number of feature-specific scene backgrounds.

Wisdom Weasel has no persistent pet or speaking-agent state machine, so copying the concierge sprite inventory would add weight without a product slot. The first organic pack therefore contains:

- four role portraits used by Avatar, Role cards, Room mentions, and Session turns;
- one Room/DuoAgent handoff scene for Room onboarding or an empty Room;
- one governed evidence-timeline scene for Memory onboarding or an empty timeline.

Add a new bitmap only after a named UI slot exists. Prefer Lucide icons and CSS for controls, states, and diagrams.

## Character system

| Role | Visual identity | Runtime meaning |
|---|---|---|
| Wisdom Weasel · Future | black and ivory stoat, solar gold, precise construction arcs | Sol, highest intelligence, deliberate and slow, hardest architecture |
| Wisdom Weasel · Present | chestnut pine marten, jade teal, evidence slips meeting a cursor | Terra, high intelligence, balanced speed, implementation and verification |
| Wisdom Weasel · First Meeting | silver sable, moon indigo, three bounded clue points | Luna, medium-high intelligence, fast investigation and orientation |
| Wisdom Weasel · Flash | sand ferret, coral, long folded evidence ribbon | DeepSeek Flash, huge context and extreme speed, not for complex work |

All four are adult anthropomorphic mustelids in restrained technical clothing. They share rendering, crop, background density, and cursor/evidence motifs while remaining distinguishable by fur, silhouette, accent, gesture, and task metaphor.

## Generation and delivery contract

- Generated with OpenAI built-in `image_gen` for this project. No existing commercial character image was supplied as an identity reference.
- Portrait source: square RGB PNG. Delivered as 640 x 640 lossy WebP at quality 82.
- Scene source: landscape RGB PNG. Delivered as 960 x 720 or 960 x 640 lossy WebP at quality 80.
- The generated pack must remain below 256 KiB; each portrait below 64 KiB; each scene below 96 KiB.
- `public/companions/manifest.json` records byte size, dimensions, SHA-256, and intended slots. `project-art-files.test.ts` verifies the files rather than trusting the manifest.
- Portraits are eager only when visible in the current role/session. Scene illustrations should be lazy-loaded and must not become page backgrounds.
- The source PNGs remain generation artifacts and are intentionally not bundled into the application.

## Prompt recipe

The shared production prompt requested a premium editorial 2.5D painterly character, crisp mustelid silhouette, realistic fur accents, adult proportions, centered head-and-shoulders crop, generous circular-crop padding, minimal charcoal-green backdrop, and a small cursor/evidence metaphor.

Every prompt explicitly excluded words, logos, watermarks, UI screenshots, microphones, speakers, headphones, speech bubbles, cameras, eye/surveillance imagery, omniscient motifs, TTS, sexualization, child or chibi proportions, oversized eyes, and plush-mascot styling.

The role deltas were:

- Sol: calm systems architect, one solar cursor point, precise construction arcs.
- Terra: practical field engineer, two selected evidence slips resolved into one teal cursor.
- Luna: fast clue-runner, exactly three bounded clue points on a short moonlit path.
- Flash: long but folded evidence ribbon, rapid scan ending in one coral cursor; explicitly no complex architecture.

The Room scene preserved Sol and Terra identities and showed two private work lanes, one guarded handoff aperture, and one public cursor-ready delivery. The Memory scene used no character: sealed history remained dim while only three useful fragments crossed a bounded user-control gate into a small context packet.

## Integration

Use `resolvePersonaAsset()` for role imagery and `resolveProjectScene()` for the two scene slots. Do not load the JSON manifest at render time; it is the packaging and audit contract.

```tsx
const scene = resolveProjectScene('room-duoagent-handoff');
<img src={scene.source} width={scene.width} height={scene.height} alt={scene.alt} loading="lazy" />
```
