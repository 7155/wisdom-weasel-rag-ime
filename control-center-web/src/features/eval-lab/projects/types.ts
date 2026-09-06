export type JsonValue = null | boolean | number | string | JsonValue[] | { [key: string]: JsonValue };
export type ArtifactView = 'markdown' | 'table' | 'form' | 'code' | 'html' | 'json';
export type ArtifactAction = { actionId: string; label: string; prompt: string };
export type ArtifactField = {
  key: string; label: string; type: 'text' | 'long_text' | 'number' | 'boolean' | 'select' | 'multiselect';
  description?: string; placeholder?: string; required?: boolean; options?: string[];
};
export type ArtifactForm = { fields: ArtifactField[]; values: Record<string, JsonValue>; description?: string };
export type ArtifactTable = { columns: { key: string; label: string }[]; rows: Record<string, JsonValue>[]; caption?: string };
export type ArtifactCode = { language: string; source: string; filename?: string };
export type ArtifactSummary = {
  artifactId: string; revision: number; title: string; kind: string; view: ArtifactView; summary: string;
  templateRef: { skillId: string; templateId: string; version: string } | null;
  actions: ArtifactAction[]; createdAtMs: number; updatedAtMs: number;
};
export type LabArtifact = ArtifactSummary & { content: JsonValue };
export type LabMaterial = {
  sourceId: string; title: string; kind: 'document' | 'code' | 'skill' | 'history' | 'failure';
  text: string; uri: string; origin: 'text' | 'path'; byteSize: number; contentHash: string; importedAtMs: number;
};
export type MaterialSet = { materialSetId: string; version: number; materials: LabMaterial[]; createdAtMs: number | null };
export type LabBinding = {
  bindingId: string; adapterId: string; materialSetId: string; briefVersion: number;
  artifactId: string; artifactRevision: number; ownerRef: { kind: string; id: string };
  summary: string; createdAtMs: number; input: Record<string, JsonValue>;
};
export type LabProjectSummary = {
  projectId: string; revision: number; title: string; materialCount: number; artifactCount: number;
  guideSessionId: string; createdAtMs: number; updatedAtMs: number;
};
export type LabProject = LabProjectSummary & {
  schemaVersion: 'rag-ime.agent-lab-project.v1'; description: string; briefVersion: number;
  materialSetId: string; materialSet: MaterialSet;
  materialVersions: { materialSetId: string; version: number; createdAtMs: number }[];
  intake: { state: 'needs_materials' | 'read' | 'unavailable'; requestedPath: string; resolvedPath: string;
    readCount: number; readBytes: number; skippedCount: number; partial: boolean;
    issues: { code: string; title: string; message: string }[]; checkedAtMs: number | null };
  artifacts: ArtifactSummary[]; bindings: LabBinding[];
  workspace: { artifactOrder: string[]; primaryArtifactId: string; layout: 'split' | 'focus' };
  workspaceBinding: { kind: string; path: string; pathKind: string; checkedAtMs: number } | null;
};
export type ProjectRead = {
  ok: true; items: LabProjectSummary[]; project: LabProject | null; artifact?: LabArtifact; materialSet?: MaterialSet;
  supportedViews: ArtifactView[]; availableAdapters?: { adapterId: string; title: string; description: string }[];
};
export const projectActions = ['create', 'update_brief', 'import_materials', 'remove_materials', 'publish_artifact', 'set_workspace', 'bind_execution', 'ensure_guide', 'prepare_app'] as const;
export type ProjectAction = typeof projectActions[number];
export type ProjectCommand = { action: ProjectAction; projectId?: string; expectedRevision: number; clientRequestId: string; input: Record<string, JsonValue> };
export type ProjectReceipt = { ok: true; project: LabProject; artifact?: LabArtifact; binding?: LabBinding; clientRequestId: string; replayed: boolean };
export const object = (value: unknown): Record<string, unknown> => value !== null && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
const text = (value: unknown): value is string => typeof value === 'string';
const natural = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const texts = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const views: ArtifactView[] = ['markdown', 'table', 'form', 'code', 'html', 'json'];
const fields = ['text', 'long_text', 'number', 'boolean', 'select', 'multiselect'];

export function isArtifactSummary(value: unknown): value is ArtifactSummary {
  const item = object(value);
  return text(item.artifactId) && !!item.artifactId && natural(item.revision) && item.revision > 0 && text(item.title)
    && text(item.kind) && text(item.summary) && views.includes(item.view as ArtifactView)
    && natural(item.createdAtMs) && natural(item.updatedAtMs) && Array.isArray(item.actions)
    && item.actions.every((raw) => { const action = object(raw); return text(action.actionId) && text(action.label) && text(action.prompt); })
    && (item.templateRef === null || ['skillId', 'templateId', 'version'].every((key) => text(object(item.templateRef)[key])));
}
export function isArtifact(value: unknown): value is LabArtifact {
  if (!isArtifactSummary(value)) return false;
  const content = object(value).content; const structured = object(content);
  if (value.view === 'markdown' || value.view === 'html') return text(content);
  if (value.view === 'code') return text(structured.source) && (structured.language === undefined || text(structured.language));
  if (value.view === 'table') return Array.isArray(structured.columns) && structured.columns.length > 0
    && structured.columns.every((raw) => text(object(raw).key) && text(object(raw).label))
    && Array.isArray(structured.rows) && structured.rows.every((row) => row !== null && typeof row === 'object' && !Array.isArray(row));
  if (value.view === 'form') return Array.isArray(structured.fields) && structured.fields.length > 0
    && structured.fields.every((raw) => { const field = object(raw); return text(field.key) && text(field.label) && fields.includes(String(field.type))
      && (!['select', 'multiselect'].includes(String(field.type)) || texts(field.options)); })
    && structured.values !== null && typeof structured.values === 'object' && !Array.isArray(structured.values);
  return content !== undefined;
}
export function isProjectSummary(value: unknown): value is LabProjectSummary {
  const item = object(value);
  return text(item.projectId) && !!item.projectId && natural(item.revision) && item.revision > 0 && text(item.title)
    && natural(item.materialCount) && natural(item.artifactCount) && text(item.guideSessionId) && natural(item.createdAtMs) && natural(item.updatedAtMs);
}
export function isProject(value: unknown): value is LabProject {
  const item = object(value); const materialSet = object(item.materialSet); const intake = object(item.intake); const workspace = object(item.workspace);
  return isProjectSummary(value) && item.schemaVersion === 'rag-ime.agent-lab-project.v1' && text(item.description)
    && natural(item.briefVersion) && text(item.materialSetId) && text(materialSet.materialSetId) && natural(materialSet.version)
    && Array.isArray(materialSet.materials) && materialSet.materials.every((raw) => { const source = object(raw); return ['sourceId', 'title', 'text', 'uri', 'kind'].every((key) => text(source[key])) && natural(source.byteSize); })
    && Array.isArray(item.materialVersions) && Array.isArray(item.artifacts) && item.artifacts.every(isArtifactSummary)
    && Array.isArray(item.bindings) && item.bindings.every((raw) => { const binding = object(raw); return text(binding.bindingId) && text(binding.adapterId) && text(object(binding.ownerRef).kind) && text(object(binding.ownerRef).id); })
    && ['needs_materials', 'read', 'unavailable'].includes(String(intake.state)) && Array.isArray(intake.issues)
    && intake.issues.every((raw) => ['code', 'title', 'message'].every((key) => text(object(raw)[key])))
    && texts(workspace.artifactOrder) && text(workspace.primaryArtifactId) && ['split', 'focus'].includes(String(workspace.layout));
}
export function parseProjectRead(raw: unknown, projectId = '', artifactId = ''): ProjectRead {
  const value = object(raw);
  if (value.ok !== true || !Array.isArray(value.items) || !value.items.every(isProjectSummary)
      || !(value.project === null || isProject(value.project)) || !texts(value.supportedViews)
      || (projectId && (!isProject(value.project) || value.project.projectId !== projectId))
      || (artifactId && (!isArtifact(value.artifact) || value.artifact.artifactId !== artifactId))) throw new Error('项目数据未完整返回，请重新读取。');
  return value as ProjectRead;
}
