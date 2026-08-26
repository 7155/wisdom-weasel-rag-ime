import { act, cleanup, render } from '@testing-library/react';
import { afterEach, describe, expect, it } from 'vitest';
import { useShallow } from 'zustand/react/shallow';
import { createAgentProjection } from '@/contracts/agent-reducer';
import { useAgentLiveStore } from '@/features/agent/state/live-store';
import { sessionWorkspaceProjectionSlice } from './PawSessionWorkspace';

afterEach(() => {
  cleanup();
  useAgentLiveStore.setState({ projections: {} });
});

describe('PawSessionWorkspace streaming subscription', () => {
  it('does not rerender the whole workspace for an unrelated streaming message identity change', () => {
    const sessionId = 'session-perf';
    const base = createAgentProjection(sessionId);
    useAgentLiveStore.setState({ projections: { [sessionId]: base } });
    let renders = 0;

    function WorkspaceProjectionProbe() {
      useAgentLiveStore(useShallow((state) => sessionWorkspaceProjectionSlice(state, sessionId)));
      renders += 1;
      return null;
    }

    render(<WorkspaceProjectionProbe />);
    expect(renders).toBe(1);

    act(() => {
      useAgentLiveStore.setState({
        projections: {
          [sessionId]: {
            ...base,
            messagesById: {
              ...base.messagesById,
              'assistant-stream': {
                schemaVersion: 'rag-ime.agent-message.v1',
                id: 'assistant-stream',
                sessionId,
                turnId: 'turn-stream',
                role: 'assistant',
                status: 'streaming',
                blocks: [],
                attachments: [],
                citations: [],
                createdAtMs: 1,
              },
            },
          },
        },
      });
    });

    expect(renders).toBe(1);
  });
});
