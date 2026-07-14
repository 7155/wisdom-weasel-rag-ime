import { Monitor, Moon, Move, Sun } from 'lucide-react';
import { useMotionPreference, type MotionPreference } from '@/design/motion';
import { useTheme, type ThemePreference } from '@/design/themes';
import {
  IconButton,
  Menu,
  MenuContent,
  MenuLabel,
  MenuRadioGroup,
  MenuRadioItem,
  MenuSeparator,
  MenuTrigger,
} from '@/components/primitives';

const themeOptions: Array<{ value: ThemePreference; label: string; icon: typeof Sun }> = [
  { value: 'system', label: '跟随系统', icon: Monitor },
  { value: 'light', label: '浅色', icon: Sun },
  { value: 'dark', label: '深色', icon: Moon },
];

const motionOptions: Array<{ value: MotionPreference; label: string }> = [
  { value: 'system', label: '跟随系统' },
  { value: 'reduce', label: '减少动效' },
  { value: 'full', label: '完整动效' },
];

export function ThemeMenu() {
  const { preference, resolvedTheme, setPreference } = useTheme();
  const motion = useMotionPreference();
  const ThemeIcon = resolvedTheme === 'dark' ? Moon : Sun;

  return (
    <Menu>
      <MenuTrigger asChild>
        <IconButton icon={<ThemeIcon size={17} />} label="外观与动效" />
      </MenuTrigger>
      <MenuContent align="end" aria-label="外观与动效">
        <MenuLabel>主题</MenuLabel>
        <MenuRadioGroup value={preference} onValueChange={(value) => setPreference(value as ThemePreference)}>
          {themeOptions.map((option) => {
            const Icon = option.icon;
            return (
              <MenuRadioItem key={option.value} value={option.value}>
                <Icon size={14} aria-hidden="true" />
                {option.label}
              </MenuRadioItem>
            );
          })}
        </MenuRadioGroup>
        <MenuSeparator />
        <MenuLabel>动效</MenuLabel>
        <MenuRadioGroup
          value={motion.preference}
          onValueChange={(value) => motion.setPreference(value as MotionPreference)}
        >
          {motionOptions.map((option) => (
            <MenuRadioItem key={option.value} value={option.value}>
              <Move size={14} aria-hidden="true" />
              {option.label}
            </MenuRadioItem>
          ))}
        </MenuRadioGroup>
      </MenuContent>
    </Menu>
  );
}
