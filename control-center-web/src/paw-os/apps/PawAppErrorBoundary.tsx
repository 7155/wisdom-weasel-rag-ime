import { Component, createRef, type ErrorInfo, type ReactNode } from 'react';
import { usePawOsAppActive, usePawOsAppIdentity, usePawOsDesktop } from '@/features/paw-os/surface-context';
import { pawApp, type PawAppId } from '../runtime/app-registry';
import { PawAppIcon } from '../shell/PawAppIcon';

type BoundaryProps = {
  active: boolean;
  appId: PawAppId;
  children: ReactNode;
  onClose?: () => void;
  resetKey: string;
};

type BoundaryState = { failed: boolean; resetKey: string };

/** Keep a failed App below its window chrome and outside every other App. */
export function PawAppErrorBoundary({ appId, children, resetKey }: {
  appId: PawAppId;
  children: ReactNode;
  resetKey: string;
}) {
  const identity = usePawOsAppIdentity();
  const active = usePawOsAppActive() ?? true;
  const desktop = usePawOsDesktop();
  const windowId = identity?.windowId;
  return <WindowErrorBoundary
    active={active}
    appId={appId}
    onClose={windowId && desktop?.closeWindow ? () => desktop.closeWindow?.(windowId) : undefined}
    resetKey={resetKey}
  >{children}</WindowErrorBoundary>;
}

class WindowErrorBoundary extends Component<BoundaryProps, BoundaryState> {
  state: BoundaryState = { failed: false, resetKey: this.props.resetKey };
  private readonly recoveryRef = createRef<HTMLButtonElement>();

  static getDerivedStateFromProps(props: BoundaryProps, state: BoundaryState): Partial<BoundaryState> | null {
    return props.resetKey === state.resetKey ? null : { failed: false, resetKey: props.resetKey };
  }

  static getDerivedStateFromError(): Partial<BoundaryState> {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error(`PAW App render failed: ${this.props.appId}`, error, info);
  }

  componentDidMount(): void {
    if (this.state.failed && this.props.active) this.recoveryRef.current?.focus({ preventScroll: true });
  }

  componentDidUpdate(previous: BoundaryProps, state: BoundaryState): void {
    if (this.state.failed && this.props.active && (!state.failed || !previous.active)) {
      this.recoveryRef.current?.focus({ preventScroll: true });
    }
  }

  render() {
    if (!this.state.failed) return this.props.children;
    const label = pawApp(this.props.appId).label;
    return <section className="paw-app-failure" role="alert" aria-label={`${label} 显示错误`}>
      <PawAppIcon appId={this.props.appId} size={32} />
      <h2>{label} 未能显示</h2>
      <p>这个窗口没有完整显示，其他 App 仍可继续使用。</p>
      <p>可以关闭此窗口，或重新载入工作台后再试。</p>
      <div className="paw-app-failure__actions">
        {this.props.onClose ? <button className="ui-button" onClick={this.props.onClose} ref={this.recoveryRef} type="button">关闭此窗口</button> : null}
        {/* A rejected lazy import can remain cached for this document. Do not
            present a boundary remount as a guaranteed module-download retry. */}
        <button className="ui-button" data-variant="primary" onClick={() => window.location.reload()} ref={this.props.onClose ? undefined : this.recoveryRef} type="button">重新载入工作台</button>
      </div>
    </section>;
  }
}
