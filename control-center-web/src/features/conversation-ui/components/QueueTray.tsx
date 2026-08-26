import { useMemo, useState } from 'react';
import type { ConversationQueueController } from '../use-conversation-queue';

/**
 * The held follow-ups, shown next to the composer that holds them. Nothing in
 * this tray has reached Runtime yet, which is exactly why every row can still
 * be reordered, edited, sent ahead of its turn, or dropped.
 */
export function QueueTray({ busy, controller }: {
  controller: ConversationQueueController;
  busy: boolean;
}) {
  const { capReached, queue } = controller;
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingText, setEditingText] = useState('');
  const previews = useMemo(() => queue.map((item) => item.text.trim().replace(/\s+/gu, ' ')), [queue]);

  if (queue.length === 0) {
    return capReached ? <p className="ccui-queue-cap-notice" role="status">排队已满，最多同时保留 8 条。</p> : null;
  }

  if (!expanded) {
    return (
      <div className="ccui-queue-tray">
        {capReached ? <p className="ccui-queue-cap-notice" role="status">排队已满，最多同时保留 8 条；这条留在输入框里。</p> : null}
        {queue.length === 1 ? (
          <div aria-label="等待当前执行完成后发送的消息" className="ccui-queue-single" role="status">
            <span aria-hidden="true" className="ccui-queue-user-mark">↳</span>
            <button className="ccui-queue-preview" onClick={() => setExpanded(true)} type="button">{previews[0]}</button>
            {busy ? (
              <button
                aria-label="改为立即干预当前执行"
                className="ccui-queue-direction"
                onClick={() => controller.sendNow(queue[0]!.id)}
                type="button"
              >调整方向</button>
            ) : null}
            <button
              aria-label="删除这条接续消息"
              className="ccui-icon-action"
              onClick={() => controller.remove(queue[0]!.id)}
              type="button"
            >⌫</button>
          </div>
        ) : (
          <button aria-expanded="false" className="ccui-queue-collapsed" onClick={() => setExpanded(true)} type="button">
            <strong>{queue.length} 条排队中</strong>
            <span>下一条：{previews[0]}</span>
            <span aria-hidden="true">展开</span>
          </button>
        )}
      </div>
    );
  }

  const beginEdit = (id: string, text: string) => {
    setEditingId(id);
    setEditingText(text);
  };
  const commitEdit = () => {
    if (!editingId) return;
    controller.edit(editingId, editingText);
    setEditingId(null);
    setEditingText('');
  };

  return (
    <section aria-label="排队中的消息" className="ccui-queue-panel">
      {capReached ? <p className="ccui-queue-cap-notice" role="status">排队已满，最多同时保留 8 条。</p> : null}
      <header className="ccui-queue-header">
        <strong>{queue.length} 条排队中</strong>
        <button aria-label="收起排队消息" className="ccui-icon-action" onClick={() => setExpanded(false)} type="button">收起</button>
      </header>
      <div className="ccui-queue-list" role="list">
        {queue.map((item, index) => {
          const editing = editingId === item.id;
          return (
            <div
              className={`ccui-queue-row${dragging === item.id ? ' is-dragging' : ''}${editing ? ' is-editing' : ''}`}
              draggable={!editing}
              key={item.id}
              onDragEnd={() => setDragging(null)}
              onDragOver={(event) => {
                if (editing) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = 'move';
              }}
              onDragStart={(event) => {
                setDragging(item.id);
                event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', item.id);
              }}
              onDrop={(event) => {
                event.preventDefault();
                const activeId = event.dataTransfer.getData('text/plain');
                if (activeId && activeId !== item.id) controller.reorder(activeId, item.id);
                setDragging(null);
              }}
              role="listitem"
            >
              <span aria-hidden="true" className="ccui-drag-handle">⠿</span>
              <div className="ccui-queue-row-main">
                <span className="ccui-queue-row-index">{index + 1}</span>
                {editing ? (
                  <textarea
                    aria-label="编辑排队消息"
                    autoFocus
                    className="ccui-queue-inline-editor"
                    onChange={(event) => setEditingText(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Escape') {
                        event.preventDefault();
                        setEditingId(null);
                      } else if (event.key === 'Enter' && !event.shiftKey && !event.nativeEvent.isComposing) {
                        event.preventDefault();
                        commitEdit();
                      }
                    }}
                    rows={2}
                    value={editingText}
                  />
                ) : (
                  <>
                    <span className="ccui-queue-row-text">{previews[index]}</span>
                    {item.queuedWhileBusy ? <span className="ccui-queue-tag">当前回合之后</span> : null}
                  </>
                )}
              </div>
              <div className="ccui-queue-actions">
                {editing ? (
                  <>
                    <button onClick={commitEdit} type="button">保存</button>
                    <button onClick={() => setEditingId(null)} type="button">取消</button>
                  </>
                ) : (
                  <>
                    <button onClick={() => controller.sendNow(item.id)} type="button">{busy ? '改为干预' : '立即发送'}</button>
                    <button onClick={() => beginEdit(item.id, item.text)} type="button">编辑</button>
                    <button onClick={() => controller.remove(item.id)} type="button">移除</button>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <footer className="ccui-queue-footer">
        <span>拖动可以调整顺序</span>
        <button className="danger" onClick={controller.clear} type="button">全部清空</button>
      </footer>
    </section>
  );
}
