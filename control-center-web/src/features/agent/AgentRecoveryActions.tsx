import { BrainCircuit, Play, RefreshCcw } from 'lucide-react';
import { Button } from '@/components/primitives';

/** Rendering only. The owning Session/App decides retry admission and linkage. */
export function AgentRecoveryActions({ onRetry, onSwitchModel, disabled = false,
  modelDisabled = false, submitted = false, continueTurn = false, label,
}: { onRetry?: () => void; onSwitchModel?: () => void; disabled?: boolean;
  modelDisabled?: boolean; submitted?: boolean; continueTurn?: boolean; label?: string }) {
  return <>
    {onRetry ? <Button size="small" variant="primary"
      leadingIcon={continueTurn ? <Play size={14} /> : <RefreshCcw size={14} />}
      disabled={disabled || submitted} onClick={onRetry}>
      {submitted ? continueTurn ? '已提交继续' : '已提交重试' : label || (continueTurn ? '继续' : '重试本轮')}
    </Button> : null}
    {onSwitchModel ? <Button size="small" variant="quiet" leadingIcon={<BrainCircuit size={14} />}
      disabled={disabled || modelDisabled} onClick={onSwitchModel}>切换模型</Button> : null}
  </>;
}
