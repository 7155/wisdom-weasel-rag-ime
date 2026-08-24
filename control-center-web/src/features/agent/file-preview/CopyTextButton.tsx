import { Check, Clipboard, TriangleAlert } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { writeClipboardText } from '@/platform/clipboard';

type CopyState = 'idle' | 'copied' | 'failed';

/**
 * One shared copy affordance for rich results and trace evidence. It copies the
 * exact text the surface already shows (post-redaction, post-truncation), so a
 * copy can never leak more than the screen does.
 */
export function CopyTextButton({
  className,
  label,
  value,
}: {
  className?: string;
  label: string;
  value: string;
}) {
  const [state, setState] = useState<CopyState>('idle');
  const resetRef = useRef(0);
  useEffect(() => () => window.clearTimeout(resetRef.current), []);

  async function copy(): Promise<void> {
    let next: CopyState = 'copied';
    try {
      await writeClipboardText(value);
    } catch {
      next = 'failed';
    }
    setState(next);
    window.clearTimeout(resetRef.current);
    resetRef.current = window.setTimeout(() => setState('idle'), 1_600);
  }

  const text = state === 'copied' ? '已复制' : state === 'failed' ? '复制失败' : '复制';
  return (
    <button
      aria-label={state === 'idle' ? `复制${label}` : `复制${label}：${text}`}
      className={['agent-copy-text', className].filter(Boolean).join(' ')}
      data-state={state}
      disabled={!value}
      onClick={() => void copy()}
      title={value ? undefined : '没有可复制的内容'}
      type="button"
    >
      {state === 'copied'
        ? <Check aria-hidden="true" size={13} />
        : state === 'failed'
          ? <TriangleAlert aria-hidden="true" size={13} />
          : <Clipboard aria-hidden="true" size={13} />}
      <span>{text}</span>
    </button>
  );
}
