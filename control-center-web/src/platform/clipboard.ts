export async function writeClipboardText(value: string): Promise<void> {
  if (!value) return;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(value);
      return;
    }
  } catch {
    // The native control-center uses a custom WebKit scheme, where the modern
    // Clipboard API may be denied even though a user-triggered copy is valid.
  }
  if (copyWithSelection(value)) return;
  throw new Error('clipboard write is unavailable');
}

function copyWithSelection(value: string): boolean {
  if (typeof document.execCommand !== 'function') return false;
  const active = document.activeElement instanceof HTMLElement ? document.activeElement : null;
  const selection = document.getSelection();
  const ranges = selection ? Array.from({ length: selection.rangeCount }, (_, index) => selection.getRangeAt(index).cloneRange()) : [];
  const textarea = document.createElement('textarea');
  textarea.value = value;
  textarea.setAttribute('readonly', '');
  textarea.setAttribute('aria-hidden', 'true');
  textarea.style.position = 'fixed';
  textarea.style.inset = '0 auto auto -10000px';
  document.body.append(textarea);
  textarea.select();
  let copied = false;
  try {
    copied = document.execCommand('copy');
  } finally {
    textarea.remove();
    if (selection) {
      selection.removeAllRanges();
      for (const range of ranges) selection.addRange(range);
    }
    active?.focus({ preventScroll: true });
  }
  return copied;
}
