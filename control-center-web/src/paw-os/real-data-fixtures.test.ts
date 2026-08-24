/// <reference types="node" />

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const fixturesPath = resolve(process.cwd(), '..', 'docs/handoffs/pawos/PAWOS_WEB_MODEL_REAL_DATA_FIXTURES.md');

describe('PAWOS web-model real data fixtures', () => {
  it('keeps every JSON and JSONL document parseable', () => {
    const source = readFileSync(fixturesPath, 'utf8');
    const fences = [...source.matchAll(/```(json|jsonl)\n([\s\S]*?)```/g)];
    expect(fences.length).toBeGreaterThan(30);

    for (const [, kind, body] of fences) {
      const documents = kind === 'jsonl' ? body.trim().split(/\n+/) : [body.trim()];
      for (const document of documents.filter(Boolean)) expect(() => JSON.parse(document)).not.toThrow();
    }
  });

  it('contains multiple continuous Session and Room conversations', () => {
    const source = readFileSync(fixturesPath, 'utf8');
    expect(source.match(/^### 场景包 S\d：/gm)).toHaveLength(2);
    expect(source.match(/^### 场景包 [AB]：/gm)).toHaveLength(2);
    expect(source).toContain('peer-message-ask');
    expect(source).toContain('peer-message-reply');
    expect(source).toContain('compaction_completed');
  });
});
