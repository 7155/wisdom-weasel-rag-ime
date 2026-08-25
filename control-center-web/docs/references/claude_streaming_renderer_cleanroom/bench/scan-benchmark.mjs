import { performance } from "node:perf_hooks";
import {
  INITIAL_SCAN_STATE,
  scanIncrementalMarkdown,
} from "../dist/core/index.js";

function makeDocument(paragraphs = 600) {
  const blocks = [];
  for (let index = 0; index < paragraphs; index += 1) {
    blocks.push(
      `## Section ${index}\n\nParagraph ${index} contains a few words and a value: ${index}.\n\n` +
        (index % 20 === 0
          ? `\`\`\`ts\nexport const value${index} = ${index};\n\`\`\`\n\n`
          : ""),
    );
  }
  return blocks.join("");
}

function streamSlices(text, step = 24) {
  const slices = [];
  for (let end = step; end < text.length; end += step) slices.push(text.slice(0, end));
  slices.push(text);
  return slices;
}

const text = makeDocument(Number(process.argv[2] ?? 600));
const slices = streamSlices(text, Number(process.argv[3] ?? 24));

let state = INITIAL_SCAN_STATE;
let started = performance.now();
for (const slice of slices) state = scanIncrementalMarkdown(state, slice, true);
const incrementalMs = performance.now() - started;

started = performance.now();
for (const slice of slices) scanIncrementalMarkdown(INITIAL_SCAN_STATE, slice, true);
const fullRescanMs = performance.now() - started;

console.log(
  JSON.stringify(
    {
      documentChars: text.length,
      updates: slices.length,
      chunks: state.chunks.length,
      incrementalMs: Number(incrementalMs.toFixed(2)),
      fullRescanMs: Number(fullRescanMs.toFixed(2)),
      speedup: Number((fullRescanMs / Math.max(incrementalMs, 0.001)).toFixed(2)),
    },
    null,
    2,
  ),
);
