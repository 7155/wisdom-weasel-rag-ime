import { afterEach, describe, expect, it } from 'vitest';
import { ControlTransportHttpError } from '@/platform/http-transport';
import type { ControlRequest } from '@/platform/transport';
import { MockControlTransport } from '@/test/mock-transport';
import { clearTraceDiagnosticStart, deliverTraceDiagnosticPrompt, readTraceDiagnosticStart, saveTraceDiagnosticStart, traceDiagnosticPromptAccepted, type TraceDiagnosticPrompt } from './diagnostic-start';

afterEach(clearTraceDiagnosticStart);

const initial = (): TraceDiagnosticPrompt => ({ sessionId: 'session:diagnostic', clientMessageId: 'client:original', message: '冻结的原诊断请求', state: 'ready' });
const empty = () => ({ ok: true, sessionId: 'session:diagnostic', items: [], liveEvents: [], messageQueue: { steering: [], followUp: [] } });

describe('Trace diagnostic prompt recovery', () => {
  it.each(['empty', 'unavailable', 'foreign'] as const)('does not resend an unknown admission when its snapshot is %s', async (kind) => {
    let attempt: TraceDiagnosticPrompt = { ...initial(), state: 'unknown' };
    const transport = new MockControlTransport({ routes: { 'agent.session.snapshot': () => {
      if (kind === 'unavailable') throw new TypeError('snapshot unavailable');
      return { ...empty(), ...(kind === 'foreign' ? { sessionId: 'session:other' } : {}) };
    } } });
    await expect(deliverTraceDiagnosticPrompt(attempt, transport, (next) => { attempt = next; })).rejects.toThrow(/核对|查无记录/);
    expect(attempt).toEqual({ ...initial(), state: 'unknown' });
    expect(transport.requests.map(({ request }) => request.pathId)).toEqual(['agent.session.snapshot']);
  });

  it.each(['message', 'queue'] as const)('settles exact %s evidence without re-posting the prompt', async (kind) => {
    let attempt: TraceDiagnosticPrompt = { ...initial(), state: 'unknown' };
    const snapshot = kind === 'message'
      ? { ...empty(), items: [{ id: 'durable:user', role: 'user', clientMessageId: attempt.clientMessageId }] }
      : { ...empty(), messageQueue: { steering: [], followUp: [{ clientMessageId: attempt.clientMessageId }] } };
    const transport = new MockControlTransport({ routes: { 'agent.session.snapshot': () => snapshot } });
    await deliverTraceDiagnosticPrompt(attempt, transport, (next) => { attempt = next; });
    expect(attempt.state).toBe('accepted');
    expect(transport.requests.map(({ request }) => request.pathId)).toEqual(['agent.session.snapshot']);
  });

  it('does not infer acceptance from matching text, another client id, or a foreign Session', () => {
    const snapshot = { ...empty(), items: [{ role: 'user', clientMessageId: 'client:other', text: initial().message }], messageQueue: { followUp: [initial().message] } };
    expect(traceDiagnosticPromptAccepted(snapshot, initial().sessionId, initial().clientMessageId)).toBe(false);
    expect(traceDiagnosticPromptAccepted({ ...snapshot, sessionId: 'session:other', items: [{ role: 'user', clientMessageId: initial().clientMessageId }] }, initial().sessionId, initial().clientMessageId)).toBe(false);
  });

  it('creates one retry successor only for a matching durable failed receipt and retains that successor after an unknown ACK', async () => {
    let attempt = initial();
    let posts = 0;
    const transport = new MockControlTransport({ routes: {
      'agent.session.snapshot': () => empty(),
      'agent.session.prompt': (request: ControlRequest) => {
        const body = request.body as Record<string, unknown>;
        if (posts++ === 0) throw new ControlTransportHttpError('agent.session.prompt', 409, 'Failed before acceptance', {
          code: 'AGENT_COMMAND_FAILED', commandReceipt: { state: 'failed', clientMessageId: body.clientMessageId, causeCode: 'RUNTIME_NOT_CONFIGURED' },
        });
        throw new TypeError('ACK lost');
      },
    } });
    await expect(deliverTraceDiagnosticPrompt(attempt, transport, (next) => { attempt = next; })).rejects.toThrow('Failed before acceptance');
    expect(attempt.state).toBe('failed');
    await expect(deliverTraceDiagnosticPrompt(attempt, transport, (next) => { attempt = next; })).rejects.toThrow('ACK lost');
    const retryId = attempt.clientMessageId;
    expect(retryId).not.toBe(initial().clientMessageId);
    expect(attempt).toMatchObject({ retryOfClientMessageId: initial().clientMessageId, message: initial().message, state: 'unknown' });
    await expect(deliverTraceDiagnosticPrompt(attempt, transport, (next) => { attempt = next; })).rejects.toThrow('查无记录不能证明未执行');
    expect(attempt.clientMessageId).toBe(retryId);
    const prompts = transport.requests.filter(({ request }) => request.pathId === 'agent.session.prompt');
    expect(prompts).toHaveLength(2);
    expect(prompts[1]!.request.body).toMatchObject({ clientMessageId: retryId, retryOfClientMessageId: initial().clientMessageId, message: initial().message });
  });

  it('retains the original report, Session and exact prompt through a page reload until acceptance', () => {
    const report = { sessionId: initial().sessionId, reportId: 'trace-report:original', targets: [{ id: 'source' }], primaryTarget: { id: 'source' }, target: { id: 'source' } };
    const context = { report, prompt: { ...initial(), state: 'unknown' as const } };
    saveTraceDiagnosticStart(context);
    expect(readTraceDiagnosticStart()).toEqual(context);
    saveTraceDiagnosticStart({ report, prompt: { ...initial(), state: 'accepted' } });
    expect(readTraceDiagnosticStart()).toBeNull();
  });
});
