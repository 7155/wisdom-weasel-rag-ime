import assert from "node:assert/strict";
import test from "node:test";
import {
  advanceToSafeBoundary,
  computeReleaseCeiling,
  findSafeInlineBoundary,
} from "../dist/core/index.js";

test("holds unresolved inline constructs", () => {
  assert.equal(findSafeInlineBoundary("**unfinished"), 0);
  assert.equal(findSafeInlineBoundary("[label](https://exa"), 0);
  assert.equal(findSafeInlineBoundary("`partial code"), 0);
  assert.equal(findSafeInlineBoundary("-"), 0);
});

test("releases closed inline constructs", () => {
  assert.equal(findSafeInlineBoundary("**done**"), 8);
  assert.equal(findSafeInlineBoundary("`done`"), 6);
  assert.equal(findSafeInlineBoundary("hello world "), 12);
});

test("caps hold-back for pathological unfinished input", () => {
  const text = `**${"x".repeat(1_000)}`;
  assert.equal(computeReleaseCeiling(text, 600), text.length - 600);
});

test("advances monotonically to a safe boundary", () => {
  const text = "one two three four five ";
  const ceiling = computeReleaseCeiling(text);
  const first = advanceToSafeBoundary(text, 0, ceiling, 8);
  const second = advanceToSafeBoundary(text, first, ceiling, 8);
  assert.ok(first > 0);
  assert.ok(second > first);
  assert.ok(second <= ceiling);
});
