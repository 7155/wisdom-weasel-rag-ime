#!/usr/bin/env node
import { createHash } from "node:crypto";
import { readdir, readFile, stat } from "node:fs/promises";
import path from "node:path";

const target = path.resolve(process.argv[2] ?? ".");
const markers = [
  ["completedChunks", 12],
  ["streamingChunkOffset", 12],
  ["openFenceTailGrafted", 14],
  ["streamingTextRootChildren", 10],
  ["long-animation-frame", 8],
  ["chat.code_stream_render", 10],
  ["completeLines", 7],
  ["requestAnimationFrame", 2],
  ["useDeferredValue", 3],
  ["md:finalize", 5],
  ["progressive-markdown", 3],
  ["standard-markdown", 2],
];

async function* walk(directory) {
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      yield* walk(absolute);
    } else if (entry.isFile() && /\.(?:m?js|html)$/.test(entry.name)) {
      yield absolute;
    }
  }
}

const candidates = [];
for await (const file of walk(target)) {
  const metadata = await stat(file);
  if (metadata.size > 25 * 1024 * 1024) continue;
  const source = await readFile(file, "utf8").catch(() => "");
  if (!source) continue;

  const hits = [];
  let score = 0;
  for (const [marker, weight] of markers) {
    let count = 0;
    let cursor = 0;
    while ((cursor = source.indexOf(marker, cursor)) >= 0) {
      count += 1;
      cursor += marker.length;
    }
    if (count > 0) {
      hits.push({ marker, count });
      score += weight + Math.min(count - 1, 3);
    }
  }
  if (score === 0) continue;

  candidates.push({
    file: path.relative(target, file),
    bytes: metadata.size,
    score,
    sha256: createHash("sha256").update(source).digest("hex"),
    hits,
  });
}

candidates.sort((left, right) => right.score - left.score || right.bytes - left.bytes);
console.log(
  JSON.stringify(
    {
      root: target,
      markerCount: markers.length,
      candidates: candidates.slice(0, 50),
    },
    null,
    2,
  ),
);
