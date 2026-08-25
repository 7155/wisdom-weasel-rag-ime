import { describe, expect, it } from 'vitest';
import agentFeatureCss from '../../features/agent/agent.css?raw';
import sessionSubagentCss from '../../features/agent/delegation/session-subagent.css?raw';
import configurationCss from '../../features/configuration/configuration.css?raw';
import contextDebugCss from '../../features/context-debug/context-debug.css?raw';
import diagnosticsCss from '../../features/diagnostics/diagnostics.css?raw';
import filesCss from '../../features/files/paw-os-files-app.css?raw';
import filesSource from '../../features/files/PawOsFilesApp.tsx?raw';
import activityTimelineCss from '../../features/memory/activity-timeline.css?raw';
import memoryCss from '../../features/memory/memory.css?raw';
import knowledgeCss from '../../features/knowledge/knowledge.css?raw';
import observabilityCss from '../../features/observability/observability.css?raw';
import pluginsCss from '../../features/plugins/plugins.css?raw';
import satelliteCss from '../../features/paw-os/paw-os-satellite.css?raw';
import terminalCss from '../../features/terminal/paw-os-terminal-app.css?raw';
import appCss from './paw-apps.css?raw';
import pawOsAppSource from '../PawOsApp.tsx?raw';
import primitiveCss from '../../components/primitives/primitives.css?raw';
import workspaceCss from '../../design/workspace.css?raw';
import agentCompositionCss from '../styles/paw-os-agent-composition.css?raw';
import agentFxCss from '../styles/paw-os-agent-fx.css?raw';
import agentMigratedCss from '../styles/paw-os-agent-migrated-v1.css?raw';
import agentNextCss from '../styles/paw-os-agent-next.css?raw';
import pawOsCss from '../styles/paw-os.css?raw';
import motionCss from '../styles/paw-os-motion.css?raw';
import roomFocusCss from '../styles/paw-os-room-focus.css?raw';
import roomMigratedCss from '../styles/paw-os-room-migrated-v1.css?raw';
import shellMigratedCss from '../styles/paw-os-shell-migrated-v1.css?raw';
import systemMigratedCss from '../styles/paw-os-sys-apps-migrated-v1.css?raw';
import toolsMigratedCss from '../styles/paw-os-tools-files-migrated-v1.css?raw';
import webmodelCss from '../styles/paw-os-webmodel-v1.css?raw';
import workbenchMigratedCss from '../styles/paw-os-workbench-migrated-v1.css?raw';

type SemanticBlock = {
  css: string;
  marker: string;
  selectors: readonly string[];
};

const semanticReceipts: ReadonlyArray<{
  app: string;
  blocks: readonly SemanticBlock[];
  sizes: readonly number[];
}> = [
  {
    app: 'Agent',
    blocks: [{ css: appCss, marker: 'agent', selectors: ['.paw-agent-row', '.paw-session-workspace__header', '.paw-unified-composer > textarea'] }],
    sizes: [13, 14, 15],
  },
  {
    app: 'Memory',
    blocks: [{ css: memoryCss, marker: 'memory', selectors: ["main[data-route-id='memory'][data-paw-os-app] .memory-preferences__actions > span"] }],
    sizes: [13],
  },
  {
    app: 'App Center',
    blocks: [{ css: pluginsCss, marker: 'app-center-lifecycle', selectors: ["main[data-route-id='plugins'][data-paw-os-app]", '.plugin-lifecycle__approval', '.capability-disclosure'] }],
    sizes: [13, 14, 15],
  },
  {
    app: 'Monitor',
    blocks: [
      { css: observabilityCss, marker: 'monitor-observability', selectors: ["main[data-route-id='observability'][data-paw-os-app]"] },
      { css: contextDebugCss, marker: 'monitor-context', selectors: ["main.context-debug-feature[data-route-id='context-debug'][data-paw-os-app='system-monitor']"] },
      { css: diagnosticsCss, marker: 'monitor-diagnostics', selectors: ["main[data-route-id='diagnostics'][data-paw-os-app]"] },
    ],
    sizes: [13, 14, 15],
  },
  {
    app: 'Settings',
    blocks: [{ css: configurationCss, marker: 'settings-configuration', selectors: ["main[data-route-id='configuration'][data-paw-os-app]", '.configuration-section-nav', '.configuration-subagents__error'] }],
    sizes: [13, 14, 15],
  },
];

function semanticBlock({ css, marker }: SemanticBlock): string {
  const startMarker = `/* UR-102 ${marker} semantic typography */`;
  const endMarker = `/* UR-102 ${marker} semantic typography end */`;
  const start = css.indexOf(startMarker);
  const end = css.indexOf(endMarker, start + startMarker.length);
  expect(start, `${marker} semantic block start`).toBeGreaterThan(-1);
  expect(end, `${marker} semantic block end`).toBeGreaterThan(start);
  return css.slice(start, end);
}

describe('PAWOS semantic type roles', () => {
  it('keeps the Ego execution layer owned by the tools-migrated final owner', () => {
    expect(toolsMigratedCss).toContain('.paw-browser-agent-field');
    expect(toolsMigratedCss).toContain('.paw-browser-agent-capsule');
    expect(toolsMigratedCss).toContain(".paw-browser-viewport[data-agent-state='active']");
    expect(toolsMigratedCss).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.paw-browser-agent-field/);
    expect(toolsMigratedCss).toMatch(/\.paw-desktop-root \.paw-window-shell\[data-app='browser'\] \.paw-omnibox-form input\s*\{[^}]*background:\s*transparent;[^}]*border:\s*0;/s);
  });

  it('keeps Browser structure and final visual polish free of retired competing owners', () => {
    expect(appCss).not.toMatch(/\.paw-browser-app\s*\{/);
    expect(appCss).not.toContain('.paw-browser-address');
    expect(motionCss).not.toContain('.paw-browser-address');
    expect(webmodelCss).not.toMatch(/\.paw-window-shell\[data-app='browser'\]\s+(?::is|\.)/);
    expect(pawOsAppSource).not.toContain("./styles/paw-os-apps-composition.css");
    expect(pawOsAppSource).not.toContain("./styles/paw-os-apps-next.css");
    expect(pawOsCss).not.toContain("@import '../apps/paw-apps.css'");
    expect(pawOsCss).not.toMatch(/transition:\s*width[^;]*height/);
    expect(pawOsCss).not.toContain(".paw-window-shell[data-app='browser'] .paw-direct-browser");
    expect(appCss).not.toContain('.paw-browser-awaiting strong');
    expect(appCss).not.toContain('.paw-browser-awaiting p');
    expect(appCss).not.toContain('.paw-browser-no-trace p');
    expect(toolsMigratedCss).toMatch(/\.paw-desktop-root \.paw-direct-browser\s*\{[^}]*container:\s*paw-browser\s*\/\s*inline-size;/s);
    expect(toolsMigratedCss).toMatch(/\.paw-desktop-root \.paw-direct-browser\s*\{[^}]*--paw-browser-chrome:\s*var\(--paw-app-nav,[^)]+\);[^}]*background:\s*var\(--paw-app-surface,/s);
    expect(toolsMigratedCss).toMatch(/@container paw-browser \(max-width:\s*620px\)[\s\S]*?\.paw-desktop-root \.paw-browser-toolbar/);
    expect(toolsMigratedCss).toMatch(/\.paw-desktop-root \.paw-browser-menu-narrow-only\s*\{[^}]*display:\s*none;/s);
    expect(toolsMigratedCss).toMatch(/@container paw-browser \(max-width:\s*620px\)[\s\S]*?\.paw-desktop-root \.paw-browser-menu-narrow-only\s*\{[^}]*display:\s*flex;/s);
    expect(toolsMigratedCss).toMatch(/\.paw-desktop-root \.paw-browser-agent-stream\s*\{[^}]*background:\s*#fff;[^}]*backdrop-filter:\s*none;/s);
    expect(toolsMigratedCss).toMatch(/\.paw-desktop-root \.paw-browser-history,\s*\.paw-desktop-root \.paw-browser-settings\s*\{[^}]*background:\s*#eef1f5;[^}]*backdrop-filter:\s*none;/s);
    expect(toolsMigratedCss).toMatch(/\.paw-desktop-root \.paw-browser-error\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:/s);
  });

  it('keeps installed Agent raw, code, and terminal readers on a readable code colour pair', () => {
    const paperRule = agentMigratedCss.indexOf("pre:not(.agent-code-block__content)");
    const codeSurfaceRule = agentMigratedCss.indexOf('Installed Agent code surfaces keep their text/background pair');
    expect(paperRule).toBeGreaterThan(-1);
    expect(codeSurfaceRule).toBeGreaterThan(paperRule);
    expect(agentMigratedCss.slice(codeSurfaceRule)).toMatch(/\.agent-tool-raw-result__body > pre,[\s\S]*?\.agent-tool-raw-result__virtual-scroll pre,[\s\S]*?\.agent-tool-code-result > pre,[\s\S]*?\.agent-tool-terminal-result > pre[\s\S]*?background:\s*var\(--color-code-bg\);[\s\S]*?color:\s*var\(--color-code-text\);/s);
  });

  it('keeps ordinary App windows above the desktop Dock', () => {
    expect(pawOsCss).toMatch(/\.paw-dock\s*\{[^}]*z-index:\s*8;/s);
    expect(shellMigratedCss).not.toMatch(/\.paw-dock\s*\{[^}]*z-index/s);
  });

  it('keeps desktop chrome and Dock visual ownership out of retired compatibility layers', () => {
    expect(pawOsAppSource).not.toContain("./styles/paw-os-composition.css");
    expect(webmodelCss).not.toMatch(/\.paw-desktop-root \.paw-dock\s*\{/);
    expect(webmodelCss).not.toMatch(/\.paw-desktop-root \.paw-window-shell(?:\[[^\]]+\])? \.paw-window\s*\{/);
    expect(webmodelCss).not.toMatch(/\.paw-desktop-root \.paw-window-titlebar\s*\{/);
    expect(webmodelCss).not.toMatch(/\.paw-desktop-root \.paw-menu-bar\s*\{/);
    expect(pawOsCss).toMatch(/\.paw-window-titlebar\s*\{[^}]*grid-template-columns:\s*var\(--paw-titlebar-lead, 76px\) minmax\(0, 1fr\) minmax\(0, auto\);/s);
    expect(shellMigratedCss).toMatch(/\.paw-desktop-root \.paw-window-titlebar\s*\{[^}]*background:\s*#fff;/s);
    expect(shellMigratedCss).toMatch(/\.paw-desktop-root \.paw-window-shell\[data-app\] \.paw-window-titlebar\s*\{[^}]*background:\s*var\(--paw-app-nav,/s);
    expect(shellMigratedCss).toMatch(/\.paw-desktop-root \.paw-traffic-lights > button\s*\{[^}]*border-radius:\s*50%;[^}]*background:\s*transparent;/s);
    expect(shellMigratedCss).toMatch(/\.paw-desktop-root \.paw-dock button::before\s*\{\s*content:\s*none;/s);
  });

  it('keeps the redesigned OS shell opaque, cool and flicker-free', () => {
    // One chrome scale: the 34px menu token owns the viewport offset.
    expect(pawOsCss).toContain('--paw-menu-h: 34px');
    expect(pawOsCss).toContain('--paw-titlebar-h: 40px');
    expect(shellMigratedCss).not.toMatch(/\.paw-menu-bar\s*\{[^}]*height:/s);
    // Windows are opaque working surfaces: no blur stack and no transparency
    // fade for inactive windows, so drag/resize can never flicker.
    expect(pawOsCss).toMatch(/\.paw-window\s*\{[^}]*backface-visibility:\s*hidden;/s);
    expect(shellMigratedCss).toMatch(/\.paw-desktop-root \.paw-window-shell \.paw-window\s*\{[^}]*background:\s*#fff;/s);
    expect(shellMigratedCss).not.toMatch(/\.paw-window-shell[^{]*\.paw-window\s*\{[^}]*backdrop-filter/s);
    expect(shellMigratedCss).not.toMatch(/:not\(\[data-active\]\)[^{]*\.paw-window\s*\{[^}]*opacity/s);
    expect(pawOsCss).not.toMatch(/transition:\s*all/);
    expect(shellMigratedCss).not.toMatch(/transition:\s*all/);
    // Live drag/resize freezes chrome glass: menu bar and Dock must not
    // re-sample a moving window through backdrop-filter (pointer starvation).
    expect(shellMigratedCss).toMatch(/\.paw-desktop-root\[data-window-interaction\] \.paw-menu-bar\s*\{[^}]*backdrop-filter:\s*none;/s);
    expect(shellMigratedCss).toMatch(/\.paw-desktop-root\[data-window-interaction\] \.paw-dock\s*\{[^}]*backdrop-filter:\s*none;/s);
    expect(pawOsCss).toMatch(/\.paw-desktop-root\[data-window-interaction\] \.paw-window-shell:not\(\[data-interaction\]\)\s*\{[^}]*pointer-events:\s*none;/s);
    // Reduced-motion may still force stillness; material never needs force.
    expect(shellMigratedCss).not.toMatch(/(?:background|border|color|opacity|border-radius)[^;{}]*!important/);
    // Warm-paper leftovers stay retired from every shell owner.
    for (const css of [pawOsCss, shellMigratedCss, motionCss]) {
      expect(css).not.toContain('rgba(27, 21, 18');
      expect(css).not.toContain('rgba(250, 247, 236');
      expect(css).not.toContain('#f3efe6');
      expect(css).not.toContain('--comp8-');
    }
    // Live flow direction and arrival signals survived the polish retirement
    // in the structural owner, including their reduced-motion story.
    expect(pawOsCss).toMatch(/g\[data-live\] \.paw-room-window-flow__base\s*\{[^}]*animation:\s*paw-window-flow-march/s);
    expect(pawOsCss).toMatch(/\[data-flow-state='arrival'\] \.paw-window-title > strong::after\s*\{[^}]*animation:\s*paw-window-flow-arrival-blink/s);
    expect(pawOsCss).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*g\[data-live\] \.paw-room-window-flow__base/);
  });

  it('keeps portalled controls above the PAWOS desktop stacking context', () => {
    expect(pawOsCss).toMatch(/\.paw-desktop-root\s*\{[^}]*z-index:\s*1000;/s);
    expect(primitiveCss).toMatch(/\.ui-dialog__overlay\s*\{[^}]*z-index:\s*1099;/s);
    expect(primitiveCss).toMatch(/\.ui-dialog\s*\{[^}]*z-index:\s*1100;/s);
    expect(primitiveCss).toMatch(/\.ui-select__content\s*\{[^}]*z-index:\s*1110;/s);
    expect(primitiveCss).toMatch(/\.ui-toast__viewport\s*\{[^}]*z-index:\s*1120;/s);
  });

  it('stacks Project planning controls and keeps the primary action icon-only at narrow widths', () => {
    const compactDetailCss = workbenchMigratedCss.slice(
      workbenchMigratedCss.indexOf('@container paw-native-stage (max-width: 1050px)'),
      workbenchMigratedCss.indexOf('@container paw-native-stage (max-width: 760px)'),
    );
    expect(compactDetailCss).toMatch(/\.paw-wb-detail__compact-toggle\s*\{\s*display:\s*inline-flex;/s);
    expect(compactDetailCss).toMatch(/\.paw-wb-detail__body\s*\{[^}]*max-height:\s*0;[^}]*visibility:\s*hidden;[^}]*transition:\s*max-height/s);
    expect(compactDetailCss).toMatch(/\.paw-wb-detail\[data-expanded='true'\] \.paw-wb-detail__body\s*\{[^}]*max-height:\s*1200px;[^}]*opacity:\s*1;[^}]*visibility:\s*visible;/s);
    const mediumProjectCss = workbenchMigratedCss.slice(
      workbenchMigratedCss.indexOf('@container paw-native-stage (max-width: 760px)'),
      workbenchMigratedCss.indexOf('@container paw-native-stage (max-width: 520px)'),
    );
    expect(mediumProjectCss).toMatch(/\.paw-wb-planning-tools\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0, 1fr\);/s);
    expect(mediumProjectCss).toMatch(/\.paw-wb-planning-tools__actions\s*\{[^}]*overflow-x:\s*auto;/s);
    expect(mediumProjectCss).toMatch(/\.paw-wb-documents\[data-reader-open='true'\] \.paw-wb-document-index\s*\{\s*display:\s*none;/s);
    expect(appCss).toMatch(/\.paw-native-stage\s*\{[^}]*container-name:\s*paw-native-stage;[^}]*container-type:\s*inline-size;/s);
    const narrowProjectCss = workbenchMigratedCss.slice(workbenchMigratedCss.indexOf('@container paw-native-stage (max-width: 520px)'));
    expect(narrowProjectCss).toMatch(/\.paw-wb-primary > span\s*\{\s*display:\s*none;/s);
    expect(narrowProjectCss).not.toContain('.paw-wb-primary { font-size: 0; }');
    expect(narrowProjectCss).toMatch(/\.paw-wb-planning-tools\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0, 1fr\);/s);
    expect(narrowProjectCss).toMatch(/\.paw-wb-planning-tools__date,[\s\S]*?\.paw-wb-planning-tools__actions\s*\{[^}]*overflow-x:\s*auto;/s);
    expect(narrowProjectCss).toMatch(/\.paw-wb-documents\[data-reader-open='true'\] \.paw-wb-document-index\s*\{\s*display:\s*none;/s);
    expect(narrowProjectCss).toMatch(/\.paw-wb-schedules-dialog \.planning-wake-form,\s*\.paw-wb-schedules-dialog \.planning-wake-row\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);/s);
  });

  it('keeps generic paper polish retired and removes retired native owners', () => {
    expect(pawOsAppSource).not.toContain('./styles/paw-os-polish.css');
    expect(agentCompositionCss).not.toContain('.paw-window-shell[data-app] .paw-native-app');
    expect(agentCompositionCss).not.toContain('.paw-window-shell[data-app] .paw-native-nav');
    expect(agentCompositionCss).not.toContain(".paw-window-shell[data-app='files'] .paw-files-tree");
  });

  it('does not ship the retired generic Project and suite prototypes', () => {
    for (const selector of [
      '.paw-app-rail',
      '.paw-workflow',
      '.paw-partner-grid',
      '.paw-transcript',
      '.paw-composer {',
      '.paw-resource-grid',
      '.paw-native-suite',
      '.paw-page-frame',
      '.paw-page-body',
      '.paw-primary-action',
      '.paw-work-document-detail',
      '.paw-memory-detail',
      '.paw-native-empty',
      '.paw-empty-compact',
      '.paw-native-nav > header',
      '.paw-native-nav > footer',
    ]) expect(appCss).not.toContain(selector);
  });

  it('leaves System App content to its current feature and migrated style owners', () => {
    for (const retiredSelector of [
      '.paw-feature-app',
      '.paw-feature-content',
      '.paw-feature-nav',
      '.paw-appearance-settings',
      '.paw-metric-strip',
      '.paw-health-strip',
      '.paw-native-timeline',
      '.paw-approval-list',
      '.paw-library-shelves',
      '.paw-memory-overview',
      '.paw-memory-cards',
      '.paw-knowledge-status',
      '.paw-library-detail',
      '.paw-relation-canvas',
      '.paw-search-canvas',
      '.paw-ingest-flow',
      '.paw-input-stage',
      '.paw-input-preview',
      '.paw-voice-status',
      '.paw-candidate-line',
      '.paw-voice-deck',
      '.paw-package-list',
      '.paw-context-deck',
      '.paw-diagnostics-grid',
      '.paw-theme-gallery',
      '.paw-agent-settings',
    ]) expect(appCss).not.toContain(retiredSelector);
    expect(systemMigratedCss).toContain(".paw-system-app[data-system-app='app-center']");
    expect(systemMigratedCss).toContain(".paw-system-app[data-system-app='system-monitor']");
    expect(systemMigratedCss).toContain(".paw-system-app[data-system-app='system-settings']");
  });

  it('keeps Memory as one native surface and gives Role Books a readable list measure', () => {
    expect(memoryCss).toMatch(
      /main\[data-route-id='memory'\]\[data-paw-os-app='memory'\] \.memory-second-brain \.memory-view-tabs[\s\S]*?border:\s*0;/s,
    );
    expect(memoryCss).toMatch(
      /\.memory-second-brain \.(?:memory-role-book-workspace)[\s\S]*?grid-template-columns:\s*minmax\(300px, \.82fr\) minmax\(0, 1\.18fr\);/s,
    );
    expect(memoryCss).toMatch(
      /\.memory-second-brain\[data-view='catalog'\] \.memory-layer-detail > \.ui-empty-state\s*\{[\s\S]*?min-height:\s*0;/s,
    );
  });

  it('keeps Knowledge library layout roots full-width and leaves document tabs explicit', () => {
    expect(knowledgeCss).toMatch(
      /main\.knowledge-feature--migrated-v1\[data-paw-os-app='knowledge'\] \.knowledge-library__tabs,[\s\S]*?width:\s*100%;[\s\S]*?border:\s*0;/s,
    );
    expect(knowledgeCss).toMatch(
      /main\.knowledge-feature--migrated-v1\[data-paw-os-app='knowledge'\] \.knowledge-library__tabs > \[role='tabpanel'\][\s\S]*?display:\s*block;[\s\S]*?flex:\s*none;/s,
    );
    expect(knowledgeCss).toMatch(/\.knowledge-markdown-preview[\s\S]*?background:\s*#fff;/s);
    expect(knowledgeCss).toMatch(
      /\.paw-window-shell\[data-app='knowledge'\] main\.knowledge-feature--migrated-v1\[data-paw-os-app='knowledge'\] \.knowledge-document-tabs[\s\S]*?display:\s*grid;[\s\S]*?width:\s*100%;/s,
    );
    expect(knowledgeCss).toMatch(
      /\.knowledge-document-tabs > \[role='tabpanel'\]\[hidden\][\s\S]*?display:\s*none;/s,
    );
  });

  it('lets a lone installed Package use both App Center catalogue tracks', () => {
    expect(pluginsCss).toMatch(
      /\.paw-desktop-root \.paw-system-app\[data-system-app='app-center'\] \.plugin-lifecycle__installed > \.installed-plugin:only-child\s*\{[^}]*grid-column:\s*1 \/ -1;/s,
    );
  });

  it('collapses System App navigation from the owning PAW window width', () => {
    expect(systemMigratedCss).not.toContain('@container paw-system-app');
    expect(systemMigratedCss).toMatch(
      /@container paw-window \(max-width: 720px\)[\s\S]*?\.paw-desktop-root \.paw-system-app\s*\{[^}]*grid-template-columns:\s*54px minmax\(0, 1fr\);/s,
    );
    // The rail may drop its labels, but never a live decision or health count.
    expect(systemMigratedCss).toMatch(
      /@container paw-window \(max-width: 720px\)[\s\S]*?button > span:not\(\.paw-system-app__nav-badge\)\s*\{\s*display:\s*none;/s,
    );
    expect(systemMigratedCss).toMatch(
      /@container paw-window \(max-width: 720px\)[\s\S]*?\.paw-system-app__nav-badge\s*\{[^}]*position:\s*absolute;/s,
    );
    expect(systemMigratedCss).toMatch(
      /@container paw-window \(max-width: 520px\)[\s\S]*?\.paw-system-app \.(?:mgmt-metrics)\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);/s,
    );
    expect(systemMigratedCss).not.toContain('.paw-system-app *::before');
    expect(systemMigratedCss).not.toContain('animation-duration: .001ms !important');
    expect(systemMigratedCss).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.paw-system-app \.mgmt-section\s*\{\s*animation:\s*none;/s,
    );
  });

  it('keeps Files and Terminal layout contracts owned by their feature styles', () => {
    expect(filesSource).not.toContain("./paw-os-files-next.css");
    expect(filesCss).toMatch(/@container paw-files \(max-width: 860px\)[\s\S]*?\.paw-files-app__workspace\s*\{[^}]*grid-template-columns:\s*minmax\(0, 1fr\);[\s\S]*?\.paw-files-tree\s*\{[^}]*max-height:\s*40%;/s);
    expect(filesCss).not.toMatch(/@media \(max-width: 860px\)[\s\S]*?\.paw-files-app__workspace/);
    expect(filesCss).toContain('--color-canvas: #f4f6f8');
    expect(filesCss).toMatch(/\.paw-files-preview\s*\{[^}]*background:\s*#fff;/s);
    expect(toolsMigratedCss).not.toContain('.paw-desktop-root .paw-files-app');
    expect(terminalCss).toMatch(/\.paw-terminal-console\s*\{[\s\S]*?grid-template-rows:\s*minmax\(0, 1fr\);/s);
    expect(terminalCss).toMatch(/\.paw-terminal-console\[data-session\]\s*\{[\s\S]*?grid-template-rows:\s*minmax\(0, 1fr\) 30px;/s);
    expect(terminalCss).toContain('--paw-terminal-bg: #101216');
    expect(terminalCss).toMatch(/\.paw-terminal-statusbar\s*\{[^}]*display:\s*flex;[^}]*overflow:\s*hidden;/s);
    expect(terminalCss).toMatch(/@container paw-terminal \(max-width:\s*560px\)/);
    expect(toolsMigratedCss).not.toContain('.paw-desktop-root .paw-terminal-app');
    for (const retiredSelector of [
      '.paw-terminal-console__subbar',
      '.paw-terminal-meta',
      '.paw-terminal-output',
      '.paw-terminal-ansi-content',
      '.paw-terminal-connecting',
      '.paw-terminal-input-bar',
      '.paw-prompt-symbol',
    ]) expect(terminalCss).not.toContain(retiredSelector);
  });

  it('keeps native page navigation free of the retired warm-paper identity rail', () => {
    expect(pawOsAppSource).not.toContain('paw-os-apps-composition.css');
  });

  it('keeps retired paper and migrated utility layers from restyling the final Terminal surface', () => {
    expect(pawOsAppSource).not.toContain('paw-os-apps-next.css');
    expect(terminalCss).toContain('.paw-terminal-console');
    expect(toolsMigratedCss).not.toContain('.paw-desktop-root .paw-terminal-app');
  });

  it('keeps Browser chrome typography readable', () => {
    const browserStart = appCss.indexOf('.paw-browser-tab-main');
    const browserEnd = appCss.indexOf('/* CDP Live View */');
    const browserCss = appCss.slice(browserStart, browserEnd);

    expect(browserStart).toBeGreaterThan(-1);
    expect(browserEnd).toBeGreaterThan(browserStart);
    expect(browserCss).not.toMatch(/font-size:\s*(?:10|11|12)px/);
    expect(browserCss).toContain('font-size: 14px');
    expect(browserCss).toContain('font-size: 13px');
    expect(browserCss).toContain('font-size: 15px');
  });

  it.each(semanticReceipts)('$app final PAWOS selectors preserve semantic type roles', ({ blocks, sizes }) => {
    const combined = blocks.map((part) => {
      const block = semanticBlock(part);
      expect(block).not.toMatch(/font-size:\s*(?:8|9|10|11|12)px/);
      for (const selector of part.selectors) expect(block).toContain(selector);
      return block;
    }).join('\n');
    for (const size of sizes) expect(combined).toContain(`font-size: ${size}px`);
  });

  it.each([
    ['agent', agentMigratedCss],
    ['room', roomMigratedCss],
    ['room-focus', roomFocusCss],
    ['shell', shellMigratedCss],
    ['browser-files-terminal', toolsMigratedCss],
    ['workbench', workbenchMigratedCss],
    ['system-apps', systemMigratedCss],
    ['memory', memoryCss],
    ['memory-activity', activityTimelineCss],
    ['knowledge', knowledgeCss],
  ])('%s final owner declares readable roles at the owning selectors', (_surface, css) => {
    expect(css).not.toMatch(/font-size:\s*(?:9\.5|10|10\.5|11|11\.5)px/);
    expect(css).not.toContain('UR-087 readable typography floor');
  });

  it('keeps final Agent controls at 13px and metadata at 12px or larger', () => {
    expect(agentMigratedCss).toMatch(/\.paw-session-workspace__tools > nav > button\s*\{[^}]*font-size:\s*13px;/s);
    expect(agentMigratedCss).toMatch(/\.paw-agent-trace-v1__filters button\s*\{[^}]*font-size:\s*13px;/s);
    expect(agentMigratedCss).not.toMatch(/font(?:-size)?:[^;]*(?:9\.5|10|10\.5|11|11\.5)px/);
  });

  it('keeps the Agent rail opaque and lays its portalled control beside window chrome', () => {
    expect(agentMigratedCss).toMatch(
      /\.paw-window-titlebar \.paw-agent-rail-toggle\s*\{[^}]*position:\s*static;[^}]*flex:\s*0 0 30px;/s,
    );
    expect(agentMigratedCss).toMatch(
      /\.paw-window-shell\[data-app='agent'\] \.paw-agent-rail\s*\{[^}]*background:\s*#f6f8fb;[^}]*backdrop-filter:\s*none;/s,
    );
    expect(agentCompositionCss).not.toMatch(/\[data-app='agent'\] \.paw-agent-rail[^{]*\{[^}]*rgba\([^)]*,\s*\.5\)/s);
  });

  it('uses one bounded motion contract without clipping open nested Tool evidence', () => {
    expect(agentFeatureCss).toMatch(
      /\.agent-smooth-reveal\s*\{[^}]*height 220ms cubic-bezier\(0\.34, 1\.4, 0\.64, 1\)/s,
    );
    expect(agentFeatureCss).toMatch(
      /\.agent-smooth-reveal\[data-state='open'\]\s*\{[^}]*overflow:\s*visible/s,
    );
    expect(agentFxCss).toMatch(
      /\.agent-turn-work__reveal\s*\{[^}]*height 220ms var\(--paw-chat-spring/s,
    );
    expect(agentFxCss).toMatch(
      /\.paw-activity__detail\s*\{[^}]*height 220ms var\(--paw-chat-spring/s,
    );
    expect(agentFxCss).toMatch(
      /@media \(prefers-reduced-motion: reduce\)[\s\S]*\.paw-activity\[data-state='running'\] \.paw-activity__label\s*\{[^}]*animation:\s*none/s,
    );
    // Session ↔ Room 消息流视觉统一：Room chronology reveals ride the exact
    // shared .agent-smooth-reveal spring — the Room stylesheet must not
    // declare a second reveal timing of its own.
    expect(roomMigratedCss).not.toMatch(/chronology__(?:detail-)?reveal[^{}]*\{[^}]*transition/s);
    expect(roomMigratedCss).toContain('--paw-chat-spring: cubic-bezier(.34, 1.4, .64, 1);');
  });

  it('scopes the virtualized turn entrance to the newest item and keeps streaming bands un-blurred', () => {
    // Virtualized turns remount on plain scrolling; an unscoped entrance
    // replays a full-viewport fade (flicker). Only the appended turn arrives.
    expect(motionCss).toMatch(
      /@starting-style\s*\{[^{}]*\.paw-session-workspace__conversation \[data-index\]:last-child \.agent-turn/s,
    );
    expect(motionCss).not.toMatch(
      /@starting-style\s*\{[^{}]*\.paw-session-workspace__conversation \.agent-turn[,\s]/s,
    );
    // The bands that sit on the streaming timeline stay near-opaque without a
    // stacked backdrop-filter, so streamed tokens are not re-blurred per frame.
    expect(agentMigratedCss).toMatch(
      /\.paw-desktop-root \.paw-session-workspace__header\s*\{[^}]*backdrop-filter:\s*none;/s,
    );
    expect(agentMigratedCss).toMatch(
      /\.paw-desktop-root \.paw-session-workspace__composer\s*\{[^}]*backdrop-filter:\s*none;/s,
    );
    expect(appCss).toMatch(
      /\.paw-room-workspace__header\s*\{[^}]*backdrop-filter:\s*none;/s,
    );
  });

  it('does not reserve the Composer twice inside the separated Agent timeline', () => {
    const separatedTimelineRules = [...agentMigratedCss.matchAll(
      /\.paw-session-workspace__conversation\[data-message-flow='separated'\] \.agent-timeline\s*\{([^}]*)\}/gs,
    )].map((match) => match[1] ?? '');

    expect(separatedTimelineRules.length).toBeGreaterThan(0);
    expect(separatedTimelineRules.join('\n')).not.toMatch(
      /padding(?:-bottom)?:\s*[^;]*120px/,
    );
  });

  it('keeps retired Agent prototype generations out of the active App stylesheet', () => {
    for (const selector of [
      '.paw-new-work',
      '.paw-composer-mode',
      '.paw-option-menu',
      '.paw-model-menu',
      '.paw-conversation-trace',
      '.paw-agent-flow-map',
    ]) expect(appCss).not.toContain(selector);

    expect(agentFxCss).toContain('.paw-desktop-root .paw-chatfx .paw-user-message');
    expect(agentFxCss).toContain('.paw-desktop-root .paw-chatfx .fx-pill.danger');
    expect(agentFxCss).toContain('.paw-desktop-root .paw-chatfx .fx-pill.vio');
    expect(agentFxCss).toContain('.paw-desktop-root .paw-chatfx .fx-context-chip');
    expect(agentFxCss).not.toMatch(/(^|})\s*(?::root|html|body|\*)\s*\{/m);
    // The repeated "Agent/状态" caption row left the fx DOM entirely; no owner
    // may keep styling (or hiding) it inside the separated conversation.
    expect(agentMigratedCss).not.toContain(".agent-assistant-turn__body > header");
    expect(webmodelCss).not.toContain(".agent-assistant-turn__body > header");
  });

  it('keeps dead Agent status and Composition 8 selectors out of live owners', () => {
    expect(agentNextCss).not.toMatch(/\.agent-activity-row[^{}]*data-status/);
    expect(workspaceCss).toContain('.agent-activity-row [data-state]');
    expect(workspaceCss).not.toContain('.agent-tool-step [data-state]');

    expect(agentCompositionCss).not.toMatch(/\.agent-assistant-pending \.paw-comp8-shape/);
    expect(agentCompositionCss).not.toContain('@keyframes paw-comp8-shape-hop');
    expect(agentCompositionCss).toContain('.agent-assistant-pending::after');
    expect(agentCompositionCss).toContain('.paw-desktop-root .paw-os-satellite');
    expect(agentCompositionCss).not.toContain(".paw-window-shell[data-app='agent'] .paw-agent-rail");
    expect(agentMigratedCss).toContain(".paw-window-shell[data-app='agent'] .paw-agent-rail");
  });

  it('keeps the retired approval-block renderer out of the Agent rich owner', () => {
    expect(agentFeatureCss).not.toMatch(/\.agent-approval-block(?:__actions)?/);
    expect(agentFxCss).toContain('.fx-approval');
  });

  it('keeps the real Agent turn navigator available and adapts it to the Session window', () => {
    expect(agentMigratedCss).not.toMatch(/\.paw-session-workspace__trace \.an-trace-rail\s*\{[^}]*display:\s*none;/s);
    expect(agentNextCss).not.toContain('.an-trace-rail { display: none; }');
    expect(agentNextCss).toMatch(/@container paw-session-workspace \(max-width: 680px\)[\s\S]*?\.an-trace\s*\{[^}]*flex-direction:\s*column;/s);
    expect(agentNextCss).toMatch(/@container paw-session-workspace \(max-width: 680px\)[\s\S]*?\.an-trace-rail\s*\{[^}]*display:\s*grid;/s);
  });

  it('keeps Agent Home full-height on the same cold surface as Session and Trace', () => {
    expect(agentNextCss).not.toContain('warm paper');
    expect(agentNextCss).not.toContain('#f4efdd');
    expect(agentNextCss).not.toContain('rgba(27, 21, 18');
    expect(agentNextCss).toContain('--an-paper: #f6f8fb');
    expect(agentNextCss).toContain('--an-paper-bright: #fff');
    expect(agentNextCss).toMatch(/\.an-home-root\s*\{[^}]*height:\s*100%;/s);
    expect(agentNextCss).toMatch(/@container paw-agent-shell \(max-width: 680px\)[\s\S]*?\.an-home-wrap/s);
  });

  it('gives each Agent tool panel a real header row and a readable metadata floor', () => {
    expect(appCss).toMatch(/\.paw-session-workspace__side > \.agent-status-panel,[\s\S]*?\.paw-session-workspace__side > \.agent-files-panel\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\);/s);
    expect(agentFeatureCss).not.toMatch(/font(?:-size)?:[^;\n]*(?:10|11)px/);
    expect(sessionSubagentCss).not.toMatch(/font(?:-size)?:[^;\n]*(?:10|11)px/);
  });

  it('keeps the imported Room owner at a 12px metadata floor and 14–16px reading/control roles', () => {
    expect(roomMigratedCss).not.toMatch(/font(?:-size)?:[^;]*(?:10|10\.5|11|11\.5)px/);
    expect(roomFocusCss).not.toMatch(/font(?:-size)?:[^;]*(?:10|10\.5|11|11\.5)px/);
    // The Room reading size matches the Session assistant text (16px/24px),
    // one conversation type scale across both streams. The Room now reaches it
    // by theming the shared conversation surface rather than by owning a
    // second set of message rules.
    expect(roomMigratedCss).toMatch(/\.ccui-assistant-body\s*\{[^}]*font-size:\s*16px;[^}]*line-height:\s*24px;/s);
    expect(roomMigratedCss).toMatch(/\.paw-room-workspace--migrated-v1 \.ccui-conversation-surface\s*\{[^}]*--ccui-text:\s*var\(--paw-chat-text\);/s);
    expect(roomMigratedCss).not.toContain('.paw-room-chronology');
    expect(roomMigratedCss).toMatch(/@container paw-room-workspace \(max-width: 520px\)[\s\S]*?\.paw-room-workspace__objective > div > small\s*\{[^}]*font-size:\s*12px;/s);
    expect(roomFocusCss).toMatch(/\.paw-room-focus-overview__inspector\s*\{[^}]*animation:\s*paw-room-focus-inspector-enter 180ms cubic-bezier\(\.23, 1, \.32, 1\)/s);
    expect(roomFocusCss).toMatch(/@media \(prefers-reduced-motion: reduce\)[\s\S]*?\.paw-room-focus-overview__inspector\s*\{\s*animation:\s*none;/s);
  });

  it('keeps Room satellite governance readable without the retired inline tool shell', () => {
    expect(appCss).not.toContain('.paw-room-workspace:not([data-panel=\'none\'])');
    expect(appCss).not.toContain('.paw-room-workspace__side');
    expect(appCss).not.toContain('.paw-room-workspace__tool-header');
    expect(appCss).not.toContain('.paw-room-workspace__tool-content');
    expect(appCss).toMatch(/\.paw-room-governance article strong\s*\{[^}]*font-size:\s*14px;/s);
    expect(appCss).toMatch(/\.paw-room-governance article small\s*\{[^}]*font-size:\s*12px;/s);
    expect(appCss).toMatch(/\.paw-room-governance select, \.paw-room-governance input\s*\{[^}]*font-size:\s*13px;/s);
  });

  it('keeps Room panel and participant satellites at the 12px metadata floor', () => {
    const roomSatelliteCss = satelliteCss.slice(
      satelliteCss.indexOf('.paw-os-satellite--room-panel'),
      satelliteCss.indexOf('@keyframes paw-participant-packet-in'),
    );

    expect(roomSatelliteCss).not.toMatch(/font(?:-size)?:[^;]*(?:10|10\.5|11|11\.5)px/);
    expect(roomSatelliteCss).toMatch(/\.paw-participant-chat__timeline article > header time\s*\{[^}]*font-size:\s*12px;/s);
    expect(roomSatelliteCss).toMatch(/\.paw-os-satellite__feedback\s*\{[^}]*font-size:\s*12px;/s);
  });

  it('lets the Room conversation reclaim the column retired with the inline tool panel', () => {
    expect(roomMigratedCss).toMatch(/\.paw-room-workspace--migrated-v1 \.paw-room-workspace__body\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/s);
  });

  it('projects the consolidated Sol console into the room-panel satellite without dead flow styles', () => {
    expect(satelliteCss).toMatch(/\.paw-os-satellite__room-panel-body > \.paw-room-focus-overview\s*\{[^}]*min-height:\s*100%;/s);
    for (const css of [roomMigratedCss, satelliteCss, appCss]) {
      expect(css).not.toContain('.paw-room-flow');
      expect(css).not.toContain('.paw-room-execution');
      expect(css).not.toContain('.paw-room-work-tree');
    }
  });

  it('opens the Room tools aside on the same edge as the control cluster that opens it', () => {
    // Named areas, so the trailing side survives any body re-ordering.
    expect(roomMigratedCss).toMatch(
      /:not\(\[data-panel='none'\]\) \.paw-room-workspace__body\s*\{[^}]*grid-template-areas:\s*'room-main room-tools';/s,
    );
    expect(roomMigratedCss).toMatch(/\.paw-room-tools\[data-side='trailing'\]\s*\{[^}]*grid-area:\s*room-tools;/s);
    expect(roomMigratedCss).toMatch(/\.paw-room-workspace__main\s*\{\s*grid-area:\s*room-main;\s*\}/s);
    // The cluster is trailing in the portalled titlebar and in the fallback
    // header alike — never leading against a trailing panel.
    expect(roomMigratedCss).toMatch(
      /\.paw-room-workspace__header > \.paw-room-window-chrome\s*\{[^}]*justify-content:\s*flex-end;/s,
    );
    expect(roomMigratedCss).not.toMatch(
      /\.paw-room-workspace__header > \.paw-room-window-chrome\s*\{[^}]*justify-content:\s*flex-start;/s,
    );
  });

  it('gives every Room window one traffic-light language and no isolated card close', () => {
    // Focus-card satellites inherit the shared titlebar instead of redefining
    // a shorter bar with buttons hidden behind nth-child.
    expect(roomMigratedCss).not.toContain('.paw-focus-card-close');
    expect(roomMigratedCss).not.toMatch(
      /\[data-frame-mode='focus-card'\][^{]*\.paw-traffic-lights button:nth-child\(\d\)[^{]*\{[^}]*display:\s*none;/s,
    );
    expect(roomMigratedCss).not.toMatch(
      /\[data-frame-mode='focus-card'\] \.paw-window-titlebar\s*\{[^}]*grid-template-columns:/s,
    );
    // Leading App chrome docks after the lights so the shared nth-child
    // red/yellow/green rules keep landing on close/minimize/maximize.
    expect(pawOsCss).toMatch(/\.paw-window-leading-slot\s*\{[^}]*margin-inline-start:/s);
    // Direct-child scoping, so docked App chrome never inherits a light's
    // ring, fill or 12px circle.
    expect(shellMigratedCss).toMatch(/\.paw-traffic-lights > button:nth-child\(1\)\s*\{[^}]*#f04438/s);
    for (const css of [pawOsCss, shellMigratedCss, roomMigratedCss]) {
      expect(css).not.toMatch(/\.paw-traffic-lights(?::[a-z-]+)? button/);
    }
    // 退出协作聚焦 shares the leading edge with every window's red light.
    expect(roomMigratedCss).toMatch(
      /\.paw-collaboration-focus-exit\s*\{[^}]*right:\s*auto;[^}]*left:\s*14px;/s,
    );
    // The focus modebar reads in the same column rhythm as a titlebar.
    expect(roomMigratedCss).toMatch(
      /\.paw-room-focus-modebar\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*148px minmax\(0, 1fr\) minmax\(0, auto\);/s,
    );
    // The SOL badge is dormant unless the Room owner published a live host.
    expect(roomMigratedCss).toMatch(
      /\.paw-window-layer\[data-room-focus\]:not\(:has\(\.paw-room-window-chrome\[data-coordinator\]\)\) \.paw-room-focus-modebar strong\s*\{[^}]*display:\s*none;/s,
    );
  });

  it('keeps one 12px traffic-light hit target on every window that docks App chrome', () => {
    // A light never flex-shrinks, so the main Room's close target measures the
    // same as a satellite's even when the cluster outgrows its column.
    expect(pawOsCss).toMatch(/\.paw-traffic-lights > button\s*\{[^}]*flex:\s*0 0 12px;/s);
    // Only the column gives ground, through one token every titlebar reads.
    expect(pawOsCss).toMatch(
      /\.paw-window-titlebar:has\(\.paw-window-leading-slot:not\(:empty\)\)\s*\{[^}]*--paw-titlebar-lead:\s*auto;/s,
    );
    for (const css of [pawOsCss, roomMigratedCss, agentMigratedCss, toolsMigratedCss]) {
      // No titlebar may pin its leading track past the shared token, or its
      // lights start shrinking again the moment an App docks a control.
      expect(css).not.toMatch(/\.paw-window-titlebar[^{]*\{[^}]*grid-template-columns:\s*\d+px/s);
    }
  });

  it('preserves explicit Focus frames and resize handles throughout the 721–820px gap', () => {
    const narrowStart = pawOsCss.indexOf('@media (max-width: 820px)');
    const narrowEnd = pawOsCss.indexOf('@media (max-width: 700px)', narrowStart);
    const narrowShellCss = pawOsCss.slice(narrowStart, narrowEnd);

    expect(narrowShellCss).toContain('.paw-window-shell:not([data-overview]):not([data-focus-layout])');
    expect(narrowShellCss).toContain('.paw-window-shell:not([data-focus-layout]) .paw-window-resize');
    expect(narrowShellCss).not.toMatch(/(?:^|\n)\s*\.paw-window-resize\s*\{/);
  });

  it('keeps a narrow satellite title visible when no App chrome competes for the row', () => {
    expect(pawOsCss).toMatch(
      /@container paw-window \(max-width: 620px\)\s*\{\s*\.paw-window-titlebar:has\(\.paw-window-chrome-slot:not\(:empty\)\) \.paw-window-title\s*\{[^}]*visibility:\s*hidden;[^}]*opacity:\s*0;/s,
    );
    expect(pawOsCss).not.toMatch(
      /@container paw-window \(max-width: 620px\)\s*\{\s*\.paw-window-title\s*\{[^}]*visibility:\s*hidden;/s,
    );
  });

  it('imports every final Knowledge Markdown owner and keeps readable prose throughout the cascade', () => {
    expect(knowledgeCss).toMatch(/\.knowledge-markdown-body\s*\{[^}]*font-size:\s*14px;/s);
    expect(knowledgeCss).toMatch(/main\.knowledge-feature\[data-paw-os-app='knowledge'\] \.knowledge-markdown-body,[\s\S]*?font-size:\s*15px;/s);
    expect(knowledgeCss).toMatch(/main\.knowledge-feature--migrated-v1\[data-paw-os-app='knowledge'\] \.knowledge-markdown-body\s*\{[^}]*font-size:\s*15px;/s);
  });

  it('keeps narrow Agent chrome on one row and the shared tool surface inside the window', () => {
    expect(agentMigratedCss).not.toContain('height: 72px');
    expect(agentMigratedCss).not.toContain('.paw-session-workspace__actions');
    expect(agentMigratedCss).toMatch(/@container paw-window \(max-width: 420px\)[\s\S]*?\.paw-session-workspace__runtime[\s\S]*?display:\s*none;/);
    expect(agentMigratedCss).toMatch(/@container paw-session-workspace \(max-width: 520px\)[\s\S]*?\.paw-session-workspace__side[\s\S]*?width:\s*100%;[\s\S]*?height:\s*min\(52%, 340px\);/);
  });

  it('keeps migrated descriptions and metadata on deliberate direct roles', () => {
    expect(shellMigratedCss).toMatch(/\.paw-launchpad section > div > button small\s*\{[^}]*font-size:\s*14px;[^}]*line-height:\s*1\.45;/s);
    expect(workbenchMigratedCss).toMatch(/\.paw-wb-document-reader__authority p\s*\{[^}]*font-size:\s*15px;[^}]*line-height:\s*1\.6;/s);
    expect(systemMigratedCss).toMatch(/\.paw-agent-mode__copy small\s*\{[^}]*font-size:\s*13px;[^}]*line-height:\s*1\.55;/s);
    expect(terminalCss).toMatch(/\.paw-terminal-statusbar\s*\{[^}]*font-size:\s*13px;[^}]*line-height:\s*1\.4;/s);
    expect(memoryCss).toMatch(/\.memory-lineage-panel > div:first-child > p,[\s\S]*?font-size:\s*14px;[\s\S]*?line-height:\s*1\.55;/);
    expect(memoryCss).toMatch(/\.memory-pipeline__note span\s*\{[^}]*font-size:\s*14px;[^}]*line-height:\s*1\.5;/s);
    expect(knowledgeCss).toMatch(/\.knowledge-graph__inspector > p\s*\{[^}]*font-size:\s*14px;[^}]*line-height:\s*1\.65;/s);
    expect(knowledgeCss).toMatch(/\.knowledge-chunk-grid p\s*\{[^}]*font-size:\s*14px;[^}]*line-height:\s*1\.62;/s);
  });
});
