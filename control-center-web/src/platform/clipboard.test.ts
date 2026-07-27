import { afterEach, describe, expect, it, vi } from 'vitest';
import { writeClipboardText } from './clipboard';

describe('writeClipboardText', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: undefined });
  });

  it('uses the modern clipboard API when WebKit exposes it', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });

    await writeClipboardText('澄');

    expect(writeText).toHaveBeenCalledWith('澄');
  });

  it('falls back to a user-selection copy when the custom scheme denies clipboard access', async () => {
    const writeText = vi.fn().mockRejectedValue(new DOMException('denied'));
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText } });
    const execCommand = vi.fn().mockReturnValue(true);
    Object.defineProperty(document, 'execCommand', { configurable: true, value: execCommand });

    await writeClipboardText('回退复制');

    expect(execCommand).toHaveBeenCalledWith('copy');
    expect(document.querySelector('textarea[aria-hidden="true"]')).toBeNull();
  });
});
