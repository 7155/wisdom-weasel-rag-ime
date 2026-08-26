import { StrictMode, type ReactNode } from 'react';
import { act, renderHook } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { useConversationQueue } from './use-conversation-queue';

describe('useConversationQueue', () => {
  it('sends a queued draft exactly once when sendNow runs in StrictMode', () => {
    const send = vi.fn();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <StrictMode>{children}</StrictMode>
    );
    const { result } = renderHook(
      () => useConversationQueue({
        busy: true,
        conversationId: 'session-strict-queue',
        send,
      }),
      { wrapper },
    );

    act(() => {
      result.current.enqueue('调整当前执行方向');
    });
    const queuedId = result.current.queue[0]?.id;
    expect(queuedId).toBeTruthy();

    act(() => result.current.sendNow(queuedId!));

    expect(send).toHaveBeenCalledTimes(1);
    expect(send).toHaveBeenCalledWith('调整当前执行方向');
    expect(result.current.queue).toHaveLength(0);
  });
});
