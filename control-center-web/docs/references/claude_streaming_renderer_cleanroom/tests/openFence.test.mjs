import assert from "node:assert/strict";
import test from "node:test";
import { detectOpenFenceTail } from "../dist/core/index.js";

test("detects an unfinished top-level fenced code tail", () => {
  const result = detectOpenFenceTail("Intro\n\n```ts\nconst x = 1;");
  assert.ok(result);
  assert.equal(result.language, "ts");
  assert.equal(result.prefix, "Intro\n\n");
  assert.equal(result.value, "const x = 1;");
  assert.equal(result.openingLineStart, 7);
});

test("returns null once the fence closes", () => {
  assert.equal(
    detectOpenFenceTail("```python\nprint('ok')\n```"),
    null,
  );
});

test("supports tilde fences and longer closing markers", () => {
  const open = detectOpenFenceTail("~~~~js\nalert(1)");
  assert.equal(open?.marker, "~");
  assert.equal(open?.markerLength, 4);
  assert.equal(detectOpenFenceTail("~~~~js\nalert(1)\n~~~~~"), null);
});
