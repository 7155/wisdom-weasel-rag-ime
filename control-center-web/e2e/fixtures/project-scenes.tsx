import { createRoot } from 'react-dom/client';
import { ProjectSceneEmptyState } from '../../src/features/agent/timeline/ProjectSceneEmptyState';
import { KnowledgeEvidenceExplorer } from '../../src/features/memory/KnowledgeVisualization';
import '../../src/design/tokens.css';
import '../../src/design/typography.css';
import '../../src/components/primitives/primitives.css';
import '../../src/features/agent/agent.css';
import '../../src/features/memory/memory.css';

createRoot(document.getElementById('root')!).render(<>
  <section className="scene-fixture-band" aria-label="Room 空态槽位">
    <ProjectSceneEmptyState sceneId="room-duoagent-handoff" title="还没有公开 Post" description="发一条消息开始协作。" />
  </section>
  <section className="scene-fixture-band" aria-label="记忆空态槽位">
    <KnowledgeEvidenceExplorer items={[]} />
  </section>
  <section className="scene-fixture-demo" aria-label="记忆正常数据槽位">
    <KnowledgeEvidenceExplorer items={[{
      id: 'evidence:demo', title: 'Room 路由审计', excerpt: '完整循环路径、取消传播与深度预算。',
      sourceType: 'local', source: 'memory', score: 0.94, url: '',
    }]} />
  </section>
</>);
