import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { previewPersonas } from '../preview-data';
import { PersonaAvatar, stickerAsset } from './PersonaAvatar';
import { personaAssetManifest, resolvePersonaAsset } from './persona-assets';

describe('Persona timeline assets', () => {
  it('maps all four fixed roles onto distinct Wisdom Weasel portraits', () => {
    expect(personaAssetManifest.schemaVersion).toBe('rag-ime.persona-assets.v4');
    expect(personaAssetManifest.assets['rag-ime-timeline-past-v1'].timeline).toBe('past');
    expect(personaAssetManifest.assets['rag-ime-timeline-present-v1'].timeline).toBe('present');
    expect(personaAssetManifest.assets['rag-ime-timeline-future-v1'].timeline).toBe('future');
    expect(personaAssetManifest.assets['rag-ime-timeline-flash-v1'].timeline).toBe('flash');
    expect(personaAssetManifest.assets['rag-ime-timeline-past-v1'].phaseLabel).toBe('初识阶段');
    expect(personaAssetManifest.assets['rag-ime-timeline-present-v1'].phaseLabel).toBe('此刻阶段');
    expect(personaAssetManifest.assets['rag-ime-timeline-future-v1'].phaseLabel).toBe('构筑阶段');
    expect(resolvePersonaAsset('rag-ime-timeline-past-v1', 'thinking')).toBe('/companions/personas/wisdom-weasel-luna-v1.webp');
    expect(resolvePersonaAsset('rag-ime-timeline-present-v1', 'done')).toBe('/companions/personas/wisdom-weasel-terra-v1.webp');
    expect(resolvePersonaAsset('rag-ime-timeline-future-v1', 'idle')).toBe('/companions/personas/wisdom-weasel-sol-v1.webp');
    expect(resolvePersonaAsset('rag-ime-timeline-flash-v1', 'listening')).toBe('/companions/personas/wisdom-weasel-flash-v1.webp');
    expect(new Set([
      resolvePersonaAsset('rag-ime-timeline-past-v1', 'idle'),
      resolvePersonaAsset('rag-ime-timeline-present-v1', 'idle'),
      resolvePersonaAsset('rag-ime-timeline-future-v1', 'idle'),
      resolvePersonaAsset('rag-ime-timeline-flash-v1', 'idle'),
    ]).size).toBe(4);
  });

  it('fails soft to Zhiyou at the present timeline while preserving legacy stickers', () => {
    expect(resolvePersonaAsset('future-persona-v9', 'warning')).toBe('/companions/personas/wisdom-weasel-terra-v1.webp');
    expect(stickerAsset('rag-ime-companion-warning')).toBe('/companions/RagImeCompanionWarning.png');
  });

  it('renders the timeline names with their manifest-selected portraits', () => {
    render(<>{previewPersonas.map((persona) => <PersonaAvatar key={persona.roleId} persona={persona} />)}</>);
    expect(screen.getByAltText('智鼬·此刻头像').getAttribute('src')).toBe('/companions/personas/wisdom-weasel-terra-v1.webp');
    expect(screen.getByAltText('智鼬·初识头像').getAttribute('src')).toBe('/companions/personas/wisdom-weasel-luna-v1.webp');
    expect(screen.getByAltText('智鼬·未来头像').getAttribute('src')).toBe('/companions/personas/wisdom-weasel-sol-v1.webp');
    expect(screen.getByAltText('智鼬·闪念头像').getAttribute('src')).toBe('/companions/personas/wisdom-weasel-flash-v1.webp');
  });
});
