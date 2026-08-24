import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it } from 'vitest';
import { TooltipProvider } from '@/components/primitives';
import { DiffPreview } from './DiffPreview';

afterEach(cleanup);

const PATCH = `diff --git a/src/a.ts b/src/a.ts
--- a/src/a.ts
+++ b/src/a.ts
@@ -1,3 +1,4 @@
 line1
-old
+new
+added
 line3
`;

describe('DiffPreview', () => {
  it('summarizes real added/removed counts per patch and per file', () => {
    render(<TooltipProvider><DiffPreview content={PATCH} /></TooltipProvider>);
    expect(screen.getByText('1 个文件 · +2 −1')).toBeInTheDocument();
    expect(screen.getByText('修改 · +2 −1')).toBeInTheDocument();
  });

  it('copies the exact received patch text', async () => {
    const user = userEvent.setup();
    render(<TooltipProvider><DiffPreview content={PATCH} /></TooltipProvider>);
    await user.click(screen.getByRole('button', { name: '复制补丁原文' }));
    expect(await screen.findByRole('button', { name: '复制补丁原文：已复制' })).toBeInTheDocument();
    await expect(navigator.clipboard.readText()).resolves.toBe(PATCH);
  });
});
