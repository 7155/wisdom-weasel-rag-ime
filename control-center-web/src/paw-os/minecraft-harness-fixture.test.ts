/// <reference types="node" />

import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

import { agentSnapshotFromResponse } from '@/contracts/agent-reducer';
import { parseRoomEventSnapshot } from '@/contracts/room-reducer';
import { parseAgentEvent, parseAgentMessage, parseRoomEvent } from '@/contracts/validators';

const root = resolve(process.cwd(), 'e2e/fixtures/minecraft-harness-20260825');

function readJson(path: string): unknown {
  return JSON.parse(readFileSync(resolve(root, path), 'utf8'));
}

describe('Minecraft Harness frontend fixture', () => {
  it('keeps the complete real Room chronology contract-valid and contiguous', () => {
    const events = readFileSync(resolve(root, 'room/history.jsonl'), 'utf8')
      .trim().split('\n').map((line) => parseRoomEvent(JSON.parse(line)));
    expect(events).toHaveLength(3261);
    expect(events[0]?.sequence).toBe(1);
    expect(events.at(-1)?.sequence).toBe(3261);
    events.forEach((event, index) => expect(event.sequence).toBe(index + 1));
    expect(parseRoomEventSnapshot(readJson('room/snapshot.json')).events).toHaveLength(373);
  });

  it('keeps four production-shaped Session conversation projections parseable', () => {
    const roles = ['coordinator', 'reviewer', 'core-specialist', 'ui-specialist'];
    for (const role of roles) {
      const raw = readJson(`sessions/${role}.snapshot.json`) as Record<string, unknown>;
      const snapshot = agentSnapshotFromResponse(raw);
      expect(snapshot.messages.length).toBeGreaterThan(0);
      snapshot.messages.forEach(parseAgentMessage);
      snapshot.liveEvents.forEach(parseAgentEvent);
    }
  });

  it('ships a deterministic playable project archive without local private paths', () => {
    const manifest = readJson('manifest.json') as {
      project: { archive: string; archiveSha256: string; fileCount: number };
    };
    const archive = readFileSync(resolve(root, manifest.project.archive));
    expect(manifest.project.fileCount).toBeGreaterThan(40);
    expect(createHash('sha256').update(archive).digest('hex')).toBe(manifest.project.archiveSha256);
    const fixtureText = [
      readFileSync(resolve(root, 'room/history.jsonl'), 'utf8'),
      readFileSync(resolve(root, 'sessions/coordinator.snapshot.json'), 'utf8'),
    ].join('\n');
    expect(fixtureText).not.toContain('/Users/example/');
    expect(fixtureText).not.toContain('/Volumes/example/');
    expect(fixtureText).toContain('room:00000000-0000-4000-8000-000000000001');
  });
});
