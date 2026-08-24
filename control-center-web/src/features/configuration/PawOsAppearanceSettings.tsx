import { Check } from 'lucide-react';
import { ManagementSection } from '@/features/overview/management-ui';

export function PawOsAppearanceSettings() {
  return (
    <ManagementSection
      title="PAWOS 外观"
      description="当前先跑通一套明亮、轻透的默认外观；多主题适配将在后续单独完成。"
    >
      <div className="paw-os-theme-settings" role="radiogroup" aria-label="PAWOS 主题">
        <label
          className="paw-os-theme-option"
          data-paw-os-theme-preview="blueprint"
          data-selected="true"
        >
          <input checked name="paw-os-theme" readOnly type="radio" value="blueprint" />
          <span className="paw-os-theme-option__preview" aria-hidden="true">
            <i />
            <i />
            <i />
          </span>
          <span className="paw-os-theme-option__copy">
            <strong>默认明亮</strong>
            <small>明亮桌面、彩色 App 身份与清晰内容层级。</small>
          </span>
          <Check className="paw-os-theme-option__check" aria-hidden="true" size={17} />
        </label>
      </div>
    </ManagementSection>
  );
}
