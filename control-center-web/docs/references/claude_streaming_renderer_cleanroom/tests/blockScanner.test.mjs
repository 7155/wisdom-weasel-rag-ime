import assert from "node:assert/strict";
import test from "node:test";
import {
  INITIAL_SCAN_STATE,
  resolveProgressiveChunks,
  scanIncrementalMarkdown,
  splitSettledMarkdown,
} from "../dist/core/index.js";

test("commits a completed paragraph and leaves the active tail mutable", () => {
  const text = "First paragraph\n\nSecond para";
  const state = scanIncrementalMarkdown(INITIAL_SCAN_STATE, text, true);
  assert.deepEqual(state.chunks, [{ text: "First paragraph", offset: 0 }]);
  assert.equal(state.committedEnd, "First paragraph\n\n".length);
  assert.deepEqual(resolveProgressiveChunks(text, true, true, state), {
    completedChunks: state.chunks,
    streamingChunk: "Second para",
    streamingChunkOffset: "First paragraph\n\n".length,
  });
});

test("preserves completed chunk object identity across append-only updates", () => {
  const first = scanIncrementalMarkdown(
    INITIAL_SCAN_STATE,
    "One\n\nTwo",
    true,
  );
  const originalChunk = first.chunks[0];
  const second = scanIncrementalMarkdown(first, "One\n\nTwo grows", true);
  assert.equal(second.chunks[0], originalChunk);
  assert.equal(second.cursor.offset >= first.cursor.offset, true);
});

test("does not split inside an unfinished fenced code block", () => {
  const text = "```ts\nconst x = 1;\n\nstill code";
  const state = scanIncrementalMarkdown(INITIAL_SCAN_STATE, text, true);
  assert.equal(state.chunks.length, 0);
  assert.equal(state.cursor.codeFence?.char, "`");
});

test("keeps list and table bodies together until a safe exit", () => {
  const listText = "- one\n- two\n\nAfter";
  const listState = scanIncrementalMarkdown(
    INITIAL_SCAN_STATE,
    listText,
    true,
  );
  assert.deepEqual(listState.chunks, [{ text: "- one\n- two", offset: 0 }]);

  const tableText = "| a | b |\n|---|---|\n| 1 | 2 |\n\nAfter";
  const tableState = scanIncrementalMarkdown(
    INITIAL_SCAN_STATE,
    tableText,
    true,
  );
  assert.equal(tableState.chunks.length, 1);
  assert.match(tableState.chunks[0].text, /^\| a \| b \|/);
});

test("resets incremental state after a non-prefix rewrite", () => {
  const first = scanIncrementalMarkdown(
    INITIAL_SCAN_STATE,
    "Alpha\n\nBeta",
    true,
  );
  const rewritten = scanIncrementalMarkdown(first, "Gamma\n\nDelta", true);
  assert.deepEqual(rewritten.chunks, [{ text: "Gamma", offset: 0 }]);
  assert.notEqual(rewritten.chunks[0], first.chunks[0]);
});

test("settled split includes the final remainder", () => {
  assert.deepEqual(splitSettledMarkdown("One\n\nTwo"), [
    { text: "One", offset: 0 },
    { text: "Two", offset: 5 },
  ]);
});
