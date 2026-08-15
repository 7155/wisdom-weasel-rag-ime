import { fireEvent, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { startControlCenter } from './start-control-center';

afterEach(() => {
  document.body.innerHTML = '';
  vi.restoreAllMocks();
});

describe('startControlCenter', () => {
  it('mounts the application after its split entry is available', async () => {
    document.body.innerHTML = '<div id="root"><div class="app-boot">正在准备工作台</div></div>';
    const mountControlCenter = vi.fn();

    await startControlCenter({ load: async () => ({ mountControlCenter }) });

    expect(mountControlCenter).toHaveBeenCalledWith(document.getElementById('root'));
  });

  it('replaces a failed entry import with a focused recovery action', async () => {
    document.body.innerHTML = '<div id="root"><div class="app-boot">正在准备工作台</div></div>';
    const reload = vi.fn();
    vi.spyOn(console, 'error').mockImplementation(() => undefined);

    await startControlCenter({
      load: async () => { throw new Error('chunk request failed'); },
      reload,
    });

    expect(screen.getByRole('heading', { name: '工作台没有打开' })).toBeInTheDocument();
    expect(screen.queryByText('chunk request failed')).not.toBeInTheDocument();
    const retry = screen.getByRole('button', { name: '重新载入' });
    expect(retry).toHaveFocus();

    fireEvent.click(retry);
    expect(reload).toHaveBeenCalledOnce();
  });
});
