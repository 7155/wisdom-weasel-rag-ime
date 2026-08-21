import {
  Activity,
  AudioLines,
  BookOpen,
  Bot,
  Brain,
  BriefcaseBusiness,
  Files,
  Globe2,
  MessagesSquare,
  PackageOpen,
  Settings2,
  SquareTerminal,
  type LucideIcon,
} from 'lucide-react';
import type { PawOsAppId } from './model/app-registry';

export const pawOsAppIcons: Record<PawOsAppId, LucideIcon> = {
  'project-workbench': BriefcaseBusiness,
  agent: Bot,
  rooms: MessagesSquare,
  memory: Brain,
  knowledge: BookOpen,
  'input-studio': AudioLines,
  'app-center': PackageOpen,
  'system-monitor': Activity,
  'system-settings': Settings2,
  files: Files,
  browser: Globe2,
  terminal: SquareTerminal,
};
