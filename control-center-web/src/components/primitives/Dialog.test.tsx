import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { describe, expect, it } from 'vitest';
import { Button } from './Button';
import { Dialog, DialogContent, DialogTitle } from './Dialog';

function ControlledDialog() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button onClick={() => setOpen(true)}>查看详情</Button>
      <Dialog onOpenChange={setOpen} open={open}>
        <DialogContent>
          <DialogTitle>详情</DialogTitle>
          <Button>弹窗操作</Button>
        </DialogContent>
      </Dialog>
    </>
  );
}

describe('Dialog', () => {
  it('returns focus to the opener when a controlled dialog closes', async () => {
    const user = userEvent.setup();
    render(<ControlledDialog />);

    const opener = screen.getByRole('button', { name: '查看详情' });
    await user.click(opener);
    expect(screen.getByRole('dialog', { name: '详情' })).toBeVisible();

    await user.keyboard('{Escape}');

    expect(screen.queryByRole('dialog', { name: '详情' })).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });
});
