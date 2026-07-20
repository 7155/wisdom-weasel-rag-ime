import { resolveProjectScene, type ProjectSceneId } from './project-art';
import './project-art.css';

export function ProjectSceneEmptyState({
  description,
  sceneId,
  title,
}: {
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
      <span><strong>{title}</strong><small>{description}</small></span>
    </div>
  );
}
