import {
  BookOpenText,
  Bot,
  Brain,
  ClipboardCheck,
  Earth,
  FilePenLine,
  FileText,
  FolderSearch,
  Landmark,
  Library,
  ListTodo,
  MessageSquareText,
  Puzzle,
  Satellite,
  Search,
  ShieldAlert,
  SquareTerminal,
  Target,
  Users,
  Wrench,
  type LucideIcon,
} from 'lucide-react';

/**
 * One compact visual identity per Tool family (PF-CM-006 / PF-CM-007).
 *
 * Small frames (Session activity rows, Room satellite entries) crowd out
 * raw labels such as “工具 agents”. Both surfaces consume this registry so a
 * Tool keeps the same glyph everywhere while the accessible name stays the
 * readable Chinese label from `publicToolName`.
 */
const toolGlyphs: Record<string, LucideIcon> = {
  read: FileText,
  read_file: FileText,
  workspace_read: FileText,
  write: FilePenLine,
  write_file: FilePenLine,
  workspace_write: FilePenLine,
  workspace_write_file: FilePenLine,
  edit: FilePenLine,
  edit_file: FilePenLine,
  workspace_edit: FilePenLine,
  workspace_edit_file: FilePenLine,
  workspace_patch: FilePenLine,
  bash: SquareTerminal,
  shell: SquareTerminal,
  workspace_shell: SquareTerminal,
  workspace_job: SquareTerminal,
  grep: Search,
  workspace_search: Search,
  find: FolderSearch,
  ls: FolderSearch,
  workspace_list: FolderSearch,
  workspace_lsp: Puzzle,
  agents: Bot,
  subagent: Bot,
  room_partner: Satellite,
  room_state: Users,
  room_post: MessageSquareText,
  room_commit: ClipboardCheck,
  room_collaborate: Users,
  agent_goal: Target,
  work_documents: Landmark,
  todo: ListTodo,
  planning: ListTodo,
  memory: BookOpenText,
  agent_role_book: BookOpenText,
  knowledge: Library,
  browser: Earth,
  skill_load: Puzzle,
  tool_load: Puzzle,
};

const activityKindGlyphs: Record<string, LucideIcon> = {
  reasoning_summary: Brain,
  user_input_required: MessageSquareText,
  approval_required: ShieldAlert,
  approval_resolved: ShieldAlert,
};

/** Resolve the compact glyph for one Runtime activity row. */
export function agentToolGlyph(toolId: string, activityKind = ''): LucideIcon {
  const normalized = toolId.trim().toLowerCase();
  if (normalized && toolGlyphs[normalized]) return toolGlyphs[normalized];
  if (normalized.includes('memory')) return BookOpenText;
  if (normalized.includes('knowledge') || normalized.includes('rag')) return Library;
  if (normalized.includes('subagent')) return Bot;
  if (normalized.includes('room')) return Satellite;
  if (normalized.includes('workspace')) return SquareTerminal;
  const byKind = activityKindGlyphs[activityKind];
  if (byKind) return byKind;
  if (activityKind.includes('approval')) return ShieldAlert;
  return Wrench;
}
