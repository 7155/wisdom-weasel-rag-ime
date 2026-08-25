import assert from "node:assert/strict";
import test from "node:test";
import {
  rememberRootChildren,
  restoreInsertedRootPositions,
  splitPositionedChildrenByOffsets,
} from "../dist/core/index.js";

test("splits a finalized root tree back across streaming chunk offsets", () => {
  const children = [
    { type: "element", position: { start: { offset: 0 } } },
    { type: "element", position: { start: { offset: 12 } } },
    { type: "text", position: { start: { offset: 30 } } },
  ];
  const buckets = splitPositionedChildrenByOffsets(children, [0, 10, 25]);
  assert.deepEqual(buckets.map((bucket) => bucket.length), [1, 1, 1]);
});

test("repairs a transformed root element position", () => {
  const original = {
    type: "root",
    children: [
      { type: "paragraph", position: { start: { offset: 4 } } },
    ],
  };
  const file = { data: {} };
  rememberRootChildren(original, file);
  const inserted = { type: "element" };
  const transformed = { type: "root", children: [inserted] };
  restoreInsertedRootPositions(transformed, file);
  assert.deepEqual(inserted.position, { start: { offset: 4 } });
});
