import { Check, Leaf, Monitor, Sparkles } from 'lucide-react';
import { useMotionPreference, type MotionPreference } from '@/design/motion';
import { useTheme, type ThemePreference } from '@/design/themes';
import { ManagementSection } from '@/features/overview/management-ui';
import { pawOsAppRegistry } from '@/features/paw-os/model/app-registry';
import './paw-os-appearance.css';

const motionChoices: ReadonlyArray<{
  value: MotionPreference;
  label: string;
  detail: string;
  icon: typeof Monitor;
}> = [
  { value: 'system', label: '跟随系统', detail: '与系统的"减少动态效果"设置保持一致。', icon: Monitor },
  { value: 'full', label: '完整动效', detail: '系统允许时，窗口与面板使用完整的过渡动画。', icon: Sparkles },
  { value: 'reduce', label: '减少动效', detail: '减少晃动和过渡，界面更安静。', icon: Leaf },
];

const themeChoices: ReadonlyArray<{
  value: ThemePreference;
  label: string;
  detail: string;
}> = [
  { value: 'system', label: '跟随系统', detail: '根据系统当前的浅色或深色设置切换。' },
  { value: 'light', label: '浅色', detail: '清透的冷色桌面与明亮内容层级。' },
  { value: 'dark', label: '深色', detail: '深蓝星空桌面与低眩光内容层级。' },
];

/* The mini desktop preview borrows real App identity colors for its Dock
   dots via [data-app] custom properties instead of hard-coding a palette. */
const previewDockApps = ['project-workbench', 'agent', 'memory', 'files', 'browser'] as const;

export function PawOsAppearanceSettings() {
  const theme = useTheme();
  const motion = useMotionPreference();
  const effectiveMotion = motion.reduceMotion ? '减少动效' : '完整动效';
  const effectiveTheme = theme.resolvedTheme === 'dark' ? '深色' : '浅色';

  return (
    <>
      <ManagementSection
        description="桌面、窗口和所有 App 使用同一套主题外观，更改立即生效。"
        title="主题"
      >
        <div className="paw-os-appearance-theme">
          <figure aria-hidden="true" className="paw-os-appearance-preview">
            <span className="paw-os-appearance-preview__menu" />
            <span className="paw-os-appearance-preview__window">
              <i className="paw-os-appearance-preview__titlebar" />
              <i className="paw-os-appearance-preview__rail" />
              <i className="paw-os-appearance-preview__content" />
            </span>
            <span className="paw-os-appearance-preview__dock">
              {previewDockApps.map((appId) => <i data-app={appId} key={appId} />)}
            </span>
          </figure>
          <div aria-label="PAWOS 主题" className="paw-os-theme-settings" role="radiogroup">
            {themeChoices.map((choice) => {
              const selected = theme.preference === choice.value;
              return (
                <label className="paw-os-theme-option" data-selected={selected || undefined} key={choice.value}>
                  <input
                    checked={selected}
                    name="paw-os-theme"
                    onChange={() => theme.setPreference(choice.value)}
                    type="radio"
                    value={choice.value}
                  />
                  <span className="paw-os-theme-option__copy">
                    <strong>{choice.label}</strong>
                    <small>{choice.detail}</small>
                  </span>
                  <Check aria-hidden="true" className="paw-os-theme-option__check" size={17} />
                </label>
              );
            })}
          </div>
        </div>
        <p className="paw-os-theme-state" role="status">
          当前生效：{effectiveTheme}
          {theme.preference === 'system' ? '（跟随系统设置）' : ''}
        </p>
      </ManagementSection>

      <ManagementSection
        description="窗口开合、面板展开这类界面动画的幅度，更改立即生效。"
        title="动效"
      >
        <div aria-label="界面动效" className="paw-os-appearance-motion" role="radiogroup">
          {motionChoices.map((choice) => {
            const Icon = choice.icon;
            const selected = motion.preference === choice.value;
            return (
              <label
                className="paw-os-appearance-motion__option"
                data-selected={selected || undefined}
                key={choice.value}
              >
                <input
                  checked={selected}
                  name="paw-os-motion"
                  onChange={() => motion.setPreference(choice.value)}
                  type="radio"
                  value={choice.value}
                />
                <span aria-hidden="true" className="paw-os-appearance-motion__icon">
                  <Icon size={16} />
                </span>
                <span className="paw-os-appearance-motion__copy">
                  <strong>{choice.label}</strong>
                  <small>{choice.detail}</small>
                </span>
                <Check aria-hidden="true" className="paw-os-appearance-motion__check" size={16} />
              </label>
            );
          })}
        </div>
        <p className="paw-os-appearance-motion__state" role="status">
          当前生效：{effectiveMotion}
          {motion.systemReduceMotion
            ? '（系统设置优先）'
            : motion.preference === 'system'
              ? '（跟随系统设置）'
              : ''}
        </p>
      </ManagementSection>

      <ManagementSection
        description="每个 App 都有固定的身份色，出现在窗口标题栏和工具架上，帮助你快速辨认。"
        title="App 身份色"
      >
        <ul aria-label="App 身份色" className="paw-os-appearance-apps">
          {pawOsAppRegistry.map((app) => (
            <li data-app={app.id} key={app.id}>
              <i aria-hidden="true" />
              <span>{app.label}</span>
            </li>
          ))}
        </ul>
      </ManagementSection>
    </>
  );
}
