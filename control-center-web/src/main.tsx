import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { App } from '@/app/App';
import { bootstrapControlCenter } from '@/app/bootstrap';

bootstrapControlCenter();

const root = document.getElementById('root');

if (!root) {
  throw new Error('Missing #root mount point');
}

createRoot(root).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
