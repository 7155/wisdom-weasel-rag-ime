import {
  Activity,
  BrainCircuit,
  Briefcase,
  FilePenLine,
  FileSearch2,
  FileText,
  Globe,
  ListChecks,
  MonitorCheck,
  Network,
  Orbit,
  PackageOpen,
  PackageSearch,
  Route,
  Search,
  SquareTerminal,
  Wrench,
  type LucideIcon,
} from 'lucide-react';
import { roomGravityToolLabel } from './room-gravity-projection';

/**
 * Room activity glyphs (Joshua5 mandate: 「工具 agents 这些都可以用 logo 替代
 * 这么多字，因为框本来就小」). The glyph replaces only the category word in the
 * tight chronology / satellite frames; the human summary text and the full
 * label (aria-label + title) always keep the explicit meaning (PF-CM-013).
 */

const toolGlyphs: Record<string, LucideIcon> = {
  room_partner: Orbit,
  agents: Network,
  agent_goal: ListChecks,
  workspace_job: Briefcase,
  skill_load: PackageOpen,
  skill_search: PackageSearch,
  tool_load: PackageOpen,
  tool_search: PackageSearch,
  bash: SquareTerminal,
  read: FileText,
  write: FilePenLine,
  edit: FilePenLine,
  ls: FileSearch2,
  find: FileSearch2,
  grep: Search,
  browser: Globe,
  desktop_semantic: MonitorCheck,
};

export interface RoomActivityGlyphParts {
  icon: LucideIcon;
  label: string;
}

/** Resolve icon + full readable label for one activity category. Tool rows
 * name the concrete tool (行星协调, 终端命令…), never a bare「工具」when the
 * Runtime reported an identity. */
export function roomActivityGlyphParts(eventType: string, toolName = ''): RoomActivityGlyphParts {
  const type = eventType.trim().toLowerCase();
  if (type === 'tool' || type.startsWith('tool_')) {
    const key = toolName.trim();
    const icon = toolGlyphs[key] ?? Wrench;
    const toolLabel = key ? roomGravityToolLabel(key) : '';
    return { icon, label: toolLabel && toolLabel !== '工具' ? `工具 · ${toolLabel}` : '工具' };
  }
  if (type.includes('reasoning') || type.includes('thinking')) return { icon: BrainCircuit, label: '思考摘要' };
  if (type.includes('route') || type.includes('dispatch')) return { icon: Route, label: '任务分派' };
  return { icon: Activity, label: '进展' };
}

export function RoomActivityGlyph({ eventType, size = 12, toolName }: {
  eventType: string;
  size?: number;
  toolName?: string;
}) {
  const { icon: Icon, label } = roomActivityGlyphParts(eventType, toolName);
  return (
    <i aria-label={label} className="paw-room-activity-glyph" role="img" title={label}>
      <Icon aria-hidden="true" size={size} />
    </i>
  );
}
