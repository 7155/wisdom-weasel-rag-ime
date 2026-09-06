import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/primitives';
import { useControlTransport } from '@/app/control-transport';
import { openPawOsRoute, usePawOsDesktop } from '@/features/paw-os/surface-context';
import { labConnectionKey, requestLabControl } from '../control-request';
import { object } from './types';

/** Read the owning Session only on request; never restart a model call. */
export function GoldenRunRecord({ sessionId }: { sessionId: string }) {
  const [open, setOpen] = useState(false);
  const transport = useControlTransport();
  const desktop = usePawOsDesktop();
  const query = useQuery({
    queryKey: ['golden-run-record', labConnectionKey(transport), sessionId],
    queryFn: ({ signal }) => requestLabControl(transport, { pathId: 'agent.session.snapshot', params: { sessionId }, signal }),
    enabled: open, retry: false, staleTime: 0,
  });
  const snapshot = object(query.data);
  const errors = (Array.isArray(snapshot.items) ? snapshot.items : []).flatMap((item) => {
    const message = object(item);
    return (Array.isArray(message.blocks) ? message.blocks : []).filter((block) => object(block).type === 'error')
      .map((block) => object(object(block).data).message).filter((text): text is string => typeof text === 'string');
  });
  const missingRuntime = errors.some((error) => /Cannot find module|ERR_MODULE_NOT_FOUND/.test(error));
  return <div className="golden-run-record">
    <Button size="small" variant="quiet" aria-expanded={open} onClick={() => setOpen((value) => !value)}>查看原运行记录</Button>
    {open ? <div className="golden-run-record__body">
      {query.isPending ? <p role="status">正在读取原对话…</p> : query.isError ? <><p role="alert">暂时无法读取原记录。已有请求没有重新发送。</p><Button size="small" onClick={() => void query.refetch()}>重新读取运行记录</Button></> : <>
        {missingRuntime ? <p className="golden-field-error">本机模型运行组件缺失。请先更新或修复 Pi Runtime，再返回起草步骤重新运行。</p> : null}
        {errors.length ? <details open={!missingRuntime}><summary>模型返回的错误</summary>{errors.map((error, index) => <p className="golden-preserve-text" key={index}>{error}</p>)}</details> : <p>原对话已保留，可以打开查看消息和执行状态。</p>}
        {desktop ? <Button size="small" onClick={() => openPawOsRoute(desktop, `/agent?session=${encodeURIComponent(sessionId)}`)}>打开原对话</Button> : null}
      </>}
    </div> : null}
  </div>;
}
