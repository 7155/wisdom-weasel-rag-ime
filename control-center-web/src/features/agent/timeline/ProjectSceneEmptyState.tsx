import type { ReactNode } from 'react';
import { resolveProjectScene, type ProjectSceneId } from './project-art';
import './project-art.css';

export function ProjectSceneEmptyState({
  action,
  description,
  sceneId,
  title,
}: {
  action?: ReactNode;
  description: string;
  sceneId: ProjectSceneId;
  title: string;
}) {
  const scene = resolveProjectScene(sceneId);
  return (
    <div className="project-scene-empty">
      <img
        alt={scene.alt}
        height={scene.height}
        loading="lazy"
        src={scene.source}
        width={scene.width}
      />
      <span><h2>{title}</h2><small>{description}</small></span>
      {action ? <div className="project-scene-empty__action">{action}</div> : null}
    </div>
  );
}
