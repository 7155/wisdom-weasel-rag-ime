import { createElement, type ComponentType } from 'react';
import { PawAppIcon, type PawAppIconProps } from '@/paw-os/shell/PawAppIcon';
import type { PawOsAppId } from './model/app-registry';

export type PawOsAppIconComponent = ComponentType<Omit<PawAppIconProps, 'appId'>>;

function iconFor(appId: PawOsAppId): PawOsAppIconComponent {
  const AppIcon = (props: Omit<PawAppIconProps, 'appId'>) => createElement(PawAppIcon, { ...props, appId });
  AppIcon.displayName = `PawOsAppIcon(${appId})`;
  return AppIcon;
}

/** Compatibility projection for consumers outside the new desktop shell. */
export const pawOsAppIcons: Record<PawOsAppId, PawOsAppIconComponent> = {
  'project-workbench': iconFor('project-workbench'),
  agent: iconFor('agent'),
  memory: iconFor('memory'),
  knowledge: iconFor('knowledge'),
  'input-studio': iconFor('input-studio'),
  'app-center': iconFor('app-center'),
  'system-monitor': iconFor('system-monitor'),
  'eval-lab': iconFor('eval-lab'),
  'system-settings': iconFor('system-settings'),
  files: iconFor('files'),
  browser: iconFor('browser'),
  terminal: iconFor('terminal'),
};
