import generatedProjection from './generated/personal-agent-workbench.v1.json';
import { parseProjectFieldProjection } from './project-field-projection';
import type { ProjectFieldProject } from './prototype-data';

export const personalAgentProjectFieldProjection = parseProjectFieldProjection(generatedProjection);

const projectionProject = personalAgentProjectFieldProjection.project;

export const reconstructedPersonalAgentProject: ProjectFieldProject = {
  ...projectionProject,
  reconstruction: projectionProject.reconstruction ? {
    ...projectionProject.reconstruction,
    projection: {
      state: 'verified-local-evidence',
      schemaVersion: personalAgentProjectFieldProjection.schemaVersion,
      generatedAt: personalAgentProjectFieldProjection.generatedAt,
      gitHead: personalAgentProjectFieldProjection.sourceRevision.gitHead,
      sourceWorktreeDirtyAtCuration: personalAgentProjectFieldProjection.sourceRevision.sourceWorktreeDirtyAtCuration,
    },
  } : undefined,
};
