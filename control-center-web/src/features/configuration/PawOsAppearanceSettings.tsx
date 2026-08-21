import { Check } from 'lucide-react';
import { pawOsThemes, usePawOsAppearance } from '@/design/paw-os-themes';
import { ManagementSection } from '@/features/overview/management-ui';

export function PawOsAppearanceSettings() {
  const { setTheme, theme } = usePawOsAppearance();

  return (
    <ManagementSection
      title="PAWOS 外观"
      description="三套风格只改变 PAWOS 的呈现，不改变 Session、Room 或输入法运行状态。"
    >
      <div className="paw-os-theme-settings" role="radiogroup" aria-label="PAWOS 主题">
        {pawOsThemes.map((definition) => {
          const selected = definition.id === theme;
          return (
            <label
              className="paw-os-theme-option"
              data-paw-os-theme-preview={definition.id}
              data-selected={selected || undefined}
              key={definition.id}
            >
              <input
                checked={selected}
                name="paw-os-theme"
                onChange={() => setTheme(definition.id)}
                type="radio"
                value={definition.id}
              />
              <span className="paw-os-theme-option__preview" aria-hidden="true">
                <i />
                <i />
                <i />
              </span>
              <span className="paw-os-theme-option__copy">
                <strong>{definition.label}</strong>
                <small>{definition.description}</small>
              </span>
              <Check className="paw-os-theme-option__check" aria-hidden="true" size={17} />
            </label>
          );
        })}
      </div>
    </ManagementSection>
  );
}
