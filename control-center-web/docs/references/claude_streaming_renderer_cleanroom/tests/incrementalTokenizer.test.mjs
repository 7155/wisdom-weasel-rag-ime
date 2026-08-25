import assert from "node:assert/strict";
import test from "node:test";
import { IncrementalLineTokenizer } from "../dist/core/index.js";

function createCountingTokenizer(counter) {
  return {
    key: "counting-v1",
    initialState: 0,
    tokenizeLine(line, stateBefore) {
      counter.calls += 1;
      return {
        tokens: [{ content: line.toUpperCase() }],
        stateAfter: stateBefore + 1,
      };
    },
  };
}

test("tokenizes only newly completed physical lines during streaming", () => {
  const counter = { calls: 0 };
  const engine = new IncrementalLineTokenizer(createCountingTokenizer(counter));

  const first = engine.update("a\nb", { streaming: true });
  assert.equal(counter.calls, 1);
  assert.equal(first.completeLines.length, 1);
  assert.equal(first.partialText, "b");
  const stableLine = first.completeLines[0];

  const second = engine.update("a\nb grows", { streaming: true });
  assert.equal(counter.calls, 1);
  assert.equal(second.completeLines[0], stableLine);

  const third = engine.update("a\nb grows\nc", { streaming: true });
  assert.equal(counter.calls, 2);
  assert.equal(third.completeLines.length, 2);
});

test("finalizes the unfinished line exactly once per settled update", () => {
  const counter = { calls: 0 };
  const engine = new IncrementalLineTokenizer(createCountingTokenizer(counter));
  engine.update("a\nb", { streaming: true });
  const settled = engine.update("a\nb", { streaming: false });
  assert.equal(counter.calls, 2);
  assert.deepEqual(settled.partialTokens, [{ content: "B" }]);
});

test("invalidates cache from the first changed complete line", () => {
  const counter = { calls: 0 };
  const engine = new IncrementalLineTokenizer(createCountingTokenizer(counter));
  engine.update("a\nb\nc", { streaming: true });
  assert.equal(counter.calls, 2);
  engine.update("a\nB changed\nc", { streaming: true });
  assert.equal(counter.calls, 3);
});
