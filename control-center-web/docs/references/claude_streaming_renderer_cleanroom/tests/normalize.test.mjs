import assert from "node:assert/strict";
import test from "node:test";
import { normalizeStreamingMarkdown } from "../dist/core/index.js";

test("normalizes bullet glyphs", () => {
  assert.equal(normalizeStreamingMarkdown("• item\n • nested"), "- item\n - nested");
});

test("hides a possibly incomplete setext underline while streaming", () => {
  assert.equal(
    normalizeStreamingMarkdown("Heading\n---", { isStreaming: true }),
    "Heading",
  );
  assert.equal(
    normalizeStreamingMarkdown("Heading\n---", { isStreaming: false }),
    "Heading\n---",
  );
});

test("makes an outer fence wider than nested same-width examples", () => {
  const input = [
    "```markdown",
    "```js",
    "alert(1)",
    "```",
    "```",
  ].join("\n");
  const output = normalizeStreamingMarkdown(input, {
    nestedCodeBlockMode: "code-in-markdown",
  });
  const lines = output.split("\n");
  assert.ok((lines[0]?.match(/^`+/)?.[0].length ?? 0) > 3);
  assert.equal(lines[1], "```js");
});
