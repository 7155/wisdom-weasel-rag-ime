import { BookOpen, MessagesSquare } from 'lucide-react';
import { createRoot } from 'react-dom/client';
import { EmptyState } from '../../src/components/primitives';
import '../../src/design/tokens.css';
import '../../src/design/typography.css';
import '../../src/components/primitives/primitives.css';
import '../../src/features/memory/memory.css';

createRoot(document.getElementById('root')!).render(<>
  <section className="functional-empty-fixture" aria-label="Room 空态槽位">
    <EmptyState icon={MessagesSquare} title="还没有公开 Post" description="发一条消息开始协作。" />
  </section>
  <section className="functional-empty-fixture" aria-label="记忆空态槽位">
    <EmptyState icon={BookOpen} title="还没有记忆" description="对话、整理和来源会写进这里。" />
  </section>
  <section className="functional-empty-demo" aria-label="记忆正常数据槽位">
    <article className="mgmt-list__row" data-selected>
      <div className="mgmt-list__copy">
        <strong>Room 路由审计</strong>
        <span>完整循环路径、取消传播与深度预算。</span>
      </div>
      <span className="mgmt-list__meta">来源 · 记忆库</span>
    </article>
  </section>
</>);
