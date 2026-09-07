import { useState } from 'react';
import { createRoot } from 'react-dom/client';
import { ModelPicker } from '@/features/agent/composer/ModelPicker';
import { AgentRecoveryActions } from '@/features/agent/AgentRecoveryActions';
import { publicAgentErrorText } from '@/features/agent/public-error';
import { parsePiModelCatalogOptions, type PiModelOption } from '@/features/agent/model-catalog-options';
import '@/components/primitives/primitives.css';
import './portable-agent.css';

type Selection = { provider: string; model: string; thinkingLevel: string };
type Failure = { state?: string; message?: string };
type Bridge = { models: () => Promise<{ catalog: unknown; selected: Selection }> };
type Options = { controls: HTMLElement; recovery: HTMLElement; onRetry: () => void; onCheck?: () => void };
declare global { interface Window { pawAgentUI: typeof portableAgentUI; pawApp: Bridge } }

/** Same ModelPicker, capability parser, recovery buttons and error text as Agent.
 * App-owned HTML keeps the vertical layout; its bridge retains execution. */
const portableAgentUI = {
  errorText: publicAgentErrorText,
  mount(options: Options) {
    let selected: Selection | undefined, models: PiModelOption[] = [], busy = false, error: Failure | undefined;
    let openModel: (() => void) | undefined;
    const controls = createRoot(options.controls), recovery = createRoot(options.recovery);
    function Controls() {
      const [requestOpen, setRequestOpen] = useState(0);
      openModel = () => setRequestOpen(value => value + 1);
      return <ModelPicker options={selected ? { models, modelReference: `${selected.provider}/${selected.model}`, thinking: selected.thinkingLevel } : undefined}
        disabled={busy} pending={false} requestOpen={requestOpen}
        onChange={(provider, model, thinkingLevel) => { selected = { provider, model, thinkingLevel }; render(); }} />;
    }
    function render() {
      controls.render(<Controls />);
      const uncertain = ['unconfirmed', 'interrupted', 'running', 'queued'].includes(error?.state || 'unconfirmed');
      recovery.render(error ? <div className="paw-app-recovery" role="alert">
        <p>{uncertain ? '原调用的完成状态尚未确认。请先核对记录，已收到的回答和资料会保留。' : publicAgentErrorText(error.message)}</p>
        <div><AgentRecoveryActions disabled={busy}
          onRetry={uncertain ? options.onCheck : options.onRetry}
          label={uncertain ? '核对原调用' : undefined}
          onSwitchModel={() => openModel?.()} /></div>
      </div> : null);
    }
    render();
    const ready = window.pawApp.models().then(value => {
      selected = value.selected; models = parsePiModelCatalogOptions(value.catalog).models;
      // A standalone API configuration exposes only its configured model.
      if (!models.length) models = [{ id: selected.model, name: selected.model, provider: selected.provider,
        reference: `${selected.provider}/${selected.model}`, thinkingLevels: [selected.thinkingLevel] }];
      render();
    }).catch(reason => { error = { state: 'failed', message: String(reason) }; render(); });
    return { ready, selection: () => selected && { ...selected },
      setBusy(value: boolean) { busy = value; render(); },
      failure(value?: Failure) { error = value; render(); },
      destroy() { controls.unmount(); recovery.unmount(); },
    };
  },
};
window.pawAgentUI = portableAgentUI;
