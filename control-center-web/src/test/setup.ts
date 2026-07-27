import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';

Object.defineProperty(window, 'scrollTo', {
  configurable: true,
  value: () => undefined,
  writable: true,
});

Object.defineProperty(globalThis, 'ResizeObserver', {
  configurable: true,
  value: class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
  writable: true,
});

Object.defineProperties(HTMLElement.prototype, {
  hasPointerCapture: { configurable: true, value: () => false },
  releasePointerCapture: { configurable: true, value: () => undefined },
  setPointerCapture: { configurable: true, value: () => undefined },
  scrollIntoView: { configurable: true, value: () => undefined },
});

afterEach(() => {
  for (const store of (globalThis as { __RAG_DRAFT_STORES__?: Array<{ clear(): void }> }).__RAG_DRAFT_STORES__ ?? []) {
    store.clear();
  }
});
