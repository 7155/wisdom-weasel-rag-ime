export type ProjectPage = 'artifact' | 'materials' | 'runs' | 'brief' | 'apps' | 'knowledge';
export type ProjectView = { page: ProjectPage; guideOpen: boolean; artifactId?: string; bindingId?: string };
export const defaultProjectView: ProjectView = { page:'artifact', guideOpen:true };
const key = (connection: string) => `paw.lab.project-views.v1:${connection}`;
export function readProjectViews(connection: string): Record<string, ProjectView> {
  try {
    const raw: unknown = JSON.parse(sessionStorage.getItem(key(connection)) ?? '{}');
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
    return Object.fromEntries(Object.entries(raw).filter(([,value]) => value && typeof value === 'object'
      && ['artifact','materials','runs','brief','apps','knowledge'].includes(value.page) && typeof value.guideOpen === 'boolean'
      && (value.artifactId === undefined || typeof value.artifactId === 'string') && (value.bindingId === undefined || typeof value.bindingId === 'string')).slice(-100));
  } catch { return {}; }
}
export function writeProjectViews(connection: string, views: Record<string, ProjectView>): boolean {
  try { sessionStorage.setItem(key(connection), JSON.stringify(Object.fromEntries(Object.entries(views).slice(-100)))); return true; }
  catch { return false; }
}
