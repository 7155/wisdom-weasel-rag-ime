import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { previewPersonas } from '../preview-data';
import { PersonaAvatar, stickerAsset } from './PersonaAvatar';
import { personaAssetManifest, resolvePersonaAsset } from './persona-assets';

describe('Persona timeline assets', () => {
  it('maps the three compatibility roles onto regenerated character portraits', () => {
    expect(personaAssetManifest.schemaVersion).toBe('rag-ime.persona-assets.v3');
    expect(personaAssetManifest.assets['rag-ime-timeline-past-v1'].timeline).toBe('past');
    expect(personaAssetManifest.assets['rag-ime-timeline-present-v1'].timeline).toBe('present');
    expect(personaAssetManifest.assets['rag-ime-timeline-future-v1'].timeline).toBe('future');
    expect(personaAssetManifest.assets['rag-ime-timeline-past-v1'].modelAffinity).toBe('5.6 Luna');
    expect(personaAssetManifest.assets['rag-ime-timeline-present-v1'].modelAffinity).toBe('5.6 Terra');
    expect(personaAssetManifest.assets['rag-ime-timeline-future-v1'].modelAffinity).toBe('5.6 Sol');
    expect(resolvePersonaAsset('rag-ime-timeline-past-v1', 'thinking')).toContain('/src/assets/personas/luna-v2.webp');
    expect(resolvePersonaAsset('rag-ime-timeline-present-v1', 'done')).toContain('/src/assets/personas/terra-v2.webp');
    expect(resolvePersonaAsset('rag-ime-timeline-future-v1', 'idle')).toContain('/src/assets/personas/sol-v2.webp');
  });

  it('fails soft to Zhiyou at the present timeline while preserving legacy stickers', () => {
    expect(resolvePersonaAsset('future-persona-v9', 'warning')).toContain('/src/assets/personas/terra-v2.webp');
    expect(stickerAsset('rag-ime-companion-warning')).toBe('/companions/RagImeCompanionWarning.png');
  });

  it('renders the timeline names with their manifest-selected portraits', () => {
    render(<>{previewPersonas.map((persona) => <PersonaAvatar key={persona.roleId} persona={persona} />)}</>);
    expect(screen.getByAltText('智鼬·此刻头像').getAttribute('src')).toContain('/src/assets/personas/terra-v2.webp');
    expect(screen.getByAltText('智鼬·初识头像').getAttribute('src')).toContain('/src/assets/personas/luna-v2.webp');
    expect(screen.getByAltText('智鼬·未来头像').getAttribute('src')).toContain('/src/assets/personas/sol-v2.webp');
  });
});
