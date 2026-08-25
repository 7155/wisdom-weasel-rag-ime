import { describe, expect, it } from 'vitest';
import workbenchCss from './paw-os-workbench-migrated-v1.css?raw';

// One PAWOS UI contract: a single cobalt accent, not a competing purple
// flourish layered on top of it. Project Workbench previously mixed its
// cobalt identity (--paw-wb-accent, matching [data-app='project-workbench']
// in paw-os.css) with an unrelated violet (#6850d9) across four decorative
// gradients — a second, dead-var-only hue that read as a second theme.
describe('Project Workbench stays on one cobalt accent', () => {
  it('never declares or references the retired violet decoration token', () => {
    expect(workbenchCss).not.toMatch(/--paw-wb-violet/);
    expect(workbenchCss).not.toContain('6850d9');
    expect(workbenchCss).not.toContain('104 80 217');
  });

  it('keeps the ambient canvas, project mark and metrics divider on the shared cobalt hue', () => {
    expect(workbenchCss).toMatch(
      /radial-gradient\(1000px 520px at 98% -8%, rgb\(49 94 172 \/ 7%\), transparent 58%\)/,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-project-lead__mark\s*\{[^}]*background:\s*linear-gradient\(135deg, rgb\(49 94 172 \/ 16%\), rgb\(49 94 172 \/ 11%\)\);/s,
    );
    expect(workbenchCss).toMatch(
      /\.paw-wb-metrics::before\s*\{[^}]*background:\s*linear-gradient\(90deg, transparent 2%, rgb\(49 94 172 \/ 45%\) 30%, rgb\(49 94 172 \/ 34%\) 70%, transparent 98%\);/s,
    );
  });
});
