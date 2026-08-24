import { ArchiveRestore, CheckCircle2, Download, FileInput } from 'lucide-react';
import { useMemo, useState } from 'react';
import {
  Button,
  Disclosure,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/primitives';
import {
  DataTable,
  InlineNotice,
  asRecord,
  publicErrorText,
  stringValue,
} from '@/features/overview/management-ui';
import type { ControlPathId } from '@/platform/routes';
import type { ControlTransport, FrontendCapabilities, JsonValue, PickedFile } from '@/platform/transport';

type PortabilityProps = {
  capabilities: FrontendCapabilities | undefined;
  currentSettings: Record<string, unknown>;
  onConfigurationChanged: () => void;
  transport: ControlTransport;
};

type ImportPreview = {
  valid: boolean;
  errors: string[];
  warnings: string[];
  settings: Record<string, unknown>;
  providers: Record<string, unknown>;
  settingCount: number;
  requiresRemoteModelConfirmation: boolean;
  configurationHash: string;
  requiresConfirmation: string;
  runtimeRevision: number;
};

type RestorePreview = {
  valid: boolean;
  restoreToken: string;
  runtimeRevision: number;
  databaseCounts: Record<string, number>;
  databaseMigrationVersion: number;
  rimeFileCount: number;
  exclusions: string[];
  requiresConfirmation: string;
  requiresRestart: boolean;
};

const importRouteIds: readonly ControlPathId[] = [
  'configuration.import.preview',
  'configuration.import.apply',
];
const backupRouteIds: readonly ControlPathId[] = ['configuration.backup.export'];
const restoreRouteIds: readonly ControlPathId[] = [
  'configuration.restore.preview',
  'configuration.restore.apply',
];

export function PortabilityWorkflows(props: PortabilityProps) {
  return (
    <div className="configuration-portability">
      <ConfigurationImportWorkflow {...props} />
      <div className="mgmt-grid-2">
        <BackupExportWorkflow {...props} />
        <BackupRestoreWorkflow {...props} />
      </div>
    </div>
  );
}

function ConfigurationImportWorkflow({
  capabilities,
  currentSettings,
  onConfigurationChanged,
  transport,
}: PortabilityProps) {
  const [selected, setSelected] = useState<PickedFile | null>(null);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const routeReady = hasRoutes(capabilities, importRouteIds);
  const pickerReady = capabilities?.native.pickFiles === true && Boolean(transport.pickFiles);
  const diffRows = useMemo(
    () => configurationDiff(currentSettings, preview?.settings ?? {}),
    [currentSettings, preview?.settings],
  );
  const requiresConfirmation = Boolean(
    preview && (preview.requiresRemoteModelConfirmation || Object.keys(preview.providers).length),
  );

  async function chooseAndPreview() {
    if (!transport.pickFiles || !pickerReady || !routeReady) return;
    setWorking(true);
    setError('');
    setReceipt(null);
    try {
      const files = await transport.pickFiles({
        purpose: 'configuration-import',
        accepts: ['.json', '.yaml', '.yml'],
        maxFiles: 1,
      });
      const file = files[0];
      if (!file) return;
      if (!file.path) throw new Error('本机文件选择器没有返回受信任路径。');
      const payload = asRecord(await transport.request({
        pathId: 'configuration.import.preview',
        body: { path: file.path },
      }));
      setSelected(file);
      setPreview(parseImportPreview(payload));
    } catch (cause) {
      setSelected(null);
      setPreview(null);
      setError(publicErrorText(cause, '无法校验配置文件，请检查文件后重试。'));
    } finally {
      setWorking(false);
    }
  }

  async function applyImport() {
    if (!selected?.path || !preview?.valid || (requiresConfirmation && !confirmed)) return;
    setWorking(true);
    setError('');
    try {
      const result = asRecord(await transport.request({
        pathId: 'configuration.import.apply',
        body: {
          path: selected.path,
          expectedRuntimeRevision: preview.runtimeRevision,
          previewToken: preview.configurationHash,
          confirmText: preview.requiresConfirmation,
          ...(preview.requiresRemoteModelConfirmation
            ? { confirmRemoteModel: 'ALLOW REMOTE MODEL' }
            : {}),
        },
      }));
      if (result.ok !== true) throw new Error(stringValue(result.error, '配置导入失败。'));
      setReceipt(result);
      setConfirmOpen(false);
      setConfirmed(false);
      onConfigurationChanged();
    } catch (cause) {
      setError(publicErrorText(cause, '配置导入失败；文件或本机设置可能已变化，请重新预览。'));
    } finally {
      setWorking(false);
    }
  }

  const blockedReason = !pickerReady
    ? '请在本机控制中心中使用配置文件选择器。网页不会接受手工路径。'
    : !routeReady
      ? '当前后台未开放配置导入的预览与应用端点。'
      : '';

  return (
    <div className="mgmt-workflow" data-availability={blockedReason ? 'unsupported' : 'available'}>
      <div className="mgmt-workflow__heading">
        <div>
          <strong>导入配置</strong>
          <p>从本机选择 JSON 或 YAML，先核对差异再导入；只有远程模型或账号信息变更需要额外确认。</p>
        </div>
        <Button
          disabled={Boolean(blockedReason)}
          leadingIcon={<FileInput size={15} />}
          loading={working && !confirmOpen}
          onClick={() => void chooseAndPreview()}
          size="small"
        >
          选择并校验
        </Button>
      </div>
      {blockedReason ? <InlineNotice title="当前不可用" tone="warning">{blockedReason}</InlineNotice> : null}
      {selected && preview ? (
        <div className="mgmt-workflow__panel">
          <strong>{selected.name}</strong>
          <span className="mgmt-muted">
            {preview.valid ? `校验通过 · ${preview.settingCount} 项设置` : `发现 ${preview.errors.length} 个问题`}
          </span>
          {preview.errors.length ? <NoticeList title="不能导入" tone="danger" items={preview.errors} /> : null}
          {preview.warnings.length ? <NoticeList title="导入提醒" tone="warning" items={preview.warnings} /> : null}
          {preview.requiresRemoteModelConfirmation ? (
            <InlineNotice title="包含远程模型开关" tone="warning">
              应用后部分内容可能发送到远程模型；确认窗口会再次明确提示。
            </InlineNotice>
          ) : null}
          {diffRows.length ? (
            <Disclosure
              className="configuration-details"
              defaultOpen={diffRows.length <= 8}
              key={preview.configurationHash}
              summary={`查看 ${diffRows.length} 项配置差异`}
            >
              <DataTable
                caption="配置导入差异"
                columns={[
                  { key: 'key', label: '设置项', width: '38%' },
                  { key: 'before', label: '当前' },
                  { key: 'after', label: '导入后' },
                ]}
                rows={diffRows}
              />
            </Disclosure>
          ) : preview.valid ? (
            <InlineNotice title="没有设置差异" tone="info">
              文件可能只包含模型账号元数据，或与当前设置一致。
            </InlineNotice>
          ) : null}
          {Object.keys(preview.providers).length ? (
            <InlineNotice title="模型配置" tone="warning">
              将处理 {Object.keys(preview.providers).map(providerLabel).join('、')}；密钥不会在页面中回显。
            </InlineNotice>
          ) : null}
          <div className="mgmt-workflow__buttons">
            <Button
              disabled={!preview.valid || working}
              onClick={() => {
                if (requiresConfirmation) setConfirmOpen(true);
                else void applyImport();
              }}
              size="small"
              variant="primary"
            >
              {requiresConfirmation ? '查看影响并继续' : '导入配置'}
            </Button>
          </div>
        </div>
      ) : null}
      {receipt ? (
        <Receipt
          detail={`${arrayStrings(receipt.changedKeys).length} 项设置已更新${receipt.requiresRestart === true ? '，相关组件需要重启' : ''}`}
          title="配置已导入"
        />
      ) : null}
      {error ? <InlineNotice title="操作失败" tone="danger">{error}</InlineNotice> : null}

      <Dialog open={confirmOpen} onOpenChange={(open) => { if (!working) { setConfirmOpen(open); setConfirmed(false); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认导入“{selected?.name ?? ''}”？</DialogTitle>
            <DialogDescription>
              文件哈希和本机设置版本已绑定；若文件或设置变化，后台会拒绝本次应用。
            </DialogDescription>
          </DialogHeader>
          {preview?.requiresRemoteModelConfirmation ? (
            <InlineNotice title="远程数据风险" tone="warning">
              此配置会开启远程模型能力，相关输入可能离开本机。
            </InlineNotice>
          ) : null}
          <label className="mgmt-workflow__confirm">
            <input checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} type="checkbox" />
            我已核对上述差异，并确认导入这份配置。
          </label>
          {error ? <InlineNotice title="导入失败" tone="danger">{error}</InlineNotice> : null}
          <DialogFooter>
            <Button disabled={working} onClick={() => setConfirmOpen(false)} variant="quiet">取消</Button>
            <Button disabled={!confirmed} loading={working} onClick={() => void applyImport()} variant="primary">确认并导入</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function BackupExportWorkflow({ capabilities, transport }: PortabilityProps) {
  const [working, setWorking] = useState(false);
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');
  const routeReady = hasRoutes(capabilities, backupRouteIds);
  const pickerReady = capabilities?.native.pickFiles === true && Boolean(transport.pickFiles);

  async function exportBackup() {
    if (!transport.pickFiles || !routeReady || !pickerReady) return;
    setWorking(true);
    setError('');
    try {
      const selections = await transport.pickFiles({
        purpose: 'export-destination',
        maxFiles: 1,
      });
      const destination = selections[0];
      if (!destination) return;
      if (!destination.path) throw new Error('本机文件选择器没有返回受信任目录。');
      const result = asRecord(await transport.request({
        pathId: 'configuration.backup.export',
        body: { destination: destination.path },
      }));
      if (result.ok !== true) throw new Error(stringValue(result.error, '备份导出失败。'));
      setReceipt(result);
    } catch (cause) {
      setError(publicErrorText(cause, '无法导出备份，请重新选择保存目录。'));
    } finally {
      setWorking(false);
    }
  }

  const blocked = !pickerReady || !routeReady;
  return (
    <div className="mgmt-workflow" data-availability={blocked ? 'unsupported' : 'available'}>
      <div className="mgmt-workflow__heading">
        <div><strong>导出可移植备份</strong><p>包含本地数据库、非敏感设置和安全的输入法自定义文件。</p></div>
        <Button disabled={blocked} leadingIcon={<Download size={15} />} loading={working} onClick={() => void exportBackup()} size="small">选择目录并导出</Button>
      </div>
      <InlineNotice title="备份不会包含" tone="info">不包含账号密钥、访问令牌、模型文件、缓存和日志。</InlineNotice>
      {receipt ? (
        <Receipt
          detail={`${formatBytes(numberValue(receipt.sizeBytes))} · ${numberValue(receipt.rimeFileCount)} 个 Rime 文件 · 不含密钥`}
          title={stringValue(receipt.path, '备份已导出')}
        />
      ) : null}
      {error ? <InlineNotice title="导出失败" tone="danger">{error}</InlineNotice> : null}
    </div>
  );
}

function BackupRestoreWorkflow({ capabilities, onConfigurationChanged, transport }: PortabilityProps) {
  const [selected, setSelected] = useState<PickedFile | null>(null);
  const [preview, setPreview] = useState<RestorePreview | null>(null);
  const [receipt, setReceipt] = useState<Record<string, unknown> | null>(null);
  const [error, setError] = useState('');
  const [working, setWorking] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const routeReady = hasRoutes(capabilities, restoreRouteIds);
  const pickerReady = capabilities?.native.pickFiles === true && Boolean(transport.pickFiles);

  async function chooseAndPreview() {
    if (!transport.pickFiles || !routeReady || !pickerReady) return;
    setWorking(true);
    setError('');
    setReceipt(null);
    try {
      const files = await transport.pickFiles({
        purpose: 'restore',
        accepts: ['.ragime-backup', '.zip'],
        maxFiles: 1,
      });
      const file = files[0];
      if (!file) return;
      if (!file.path) throw new Error('本机文件选择器没有返回受信任路径。');
      const payload = asRecord(await transport.request({
        pathId: 'configuration.restore.preview',
        body: { path: file.path },
      }));
      setSelected(file);
      setPreview(parseRestorePreview(payload));
    } catch (cause) {
      setSelected(null);
      setPreview(null);
      setError(publicErrorText(cause, '无法校验备份包，请检查文件后重试。'));
    } finally {
      setWorking(false);
    }
  }

  async function applyRestore() {
    if (!selected?.path || !preview?.valid || !confirmed) return;
    setWorking(true);
    setError('');
    try {
      const result = asRecord(await transport.request({
        pathId: 'configuration.restore.apply',
        body: {
          path: selected.path,
          restoreToken: preview.restoreToken,
          confirmText: preview.requiresConfirmation,
          expectedRuntimeRevision: preview.runtimeRevision,
        },
      }));
      if (result.ok !== true) throw new Error(stringValue(result.error, '备份恢复失败。'));
      setReceipt(result);
      setPreview(null);
      setSelected(null);
      setConfirmOpen(false);
      setConfirmed(false);
      onConfigurationChanged();
    } catch (cause) {
      setError(publicErrorText(cause, '恢复失败；备份包或本机数据可能已变化，请重新预览。'));
    } finally {
      setWorking(false);
    }
  }

  const blocked = !pickerReady || !routeReady;
  return (
    <div className="mgmt-workflow" data-availability={blocked ? 'unsupported' : 'available'}>
      <div className="mgmt-workflow__heading">
        <div><strong>恢复可移植备份</strong><p>确认备份范围和文件完整性后，再由你明确确认恢复。</p></div>
        <Button disabled={blocked} leadingIcon={<ArchiveRestore size={15} />} loading={working && !confirmOpen} onClick={() => void chooseAndPreview()} size="small">选择并校验</Button>
      </div>
      {preview && selected ? (
        <div className="mgmt-workflow__panel">
          <strong>{selected.name}</strong>
          <dl className="mgmt-kv">
            <dt>输入记录</dt><dd>{preview.databaseCounts.input_events ?? 0}</dd>
            <dt>记忆项</dt><dd>{preview.databaseCounts.memory_items ?? 0}</dd>
            <dt>规划任务</dt><dd>{preview.databaseCounts.planning_tasks ?? 0}</dd>
            <dt>Rime 文件</dt><dd>{preview.rimeFileCount}</dd>
            <dt>数据库版本</dt><dd>{preview.databaseMigrationVersion}</dd>
          </dl>
          <NoticeList title="备份排除项" tone="info" items={preview.exclusions} />
          <InlineNotice title="回滚与生效" tone="warning">
            恢复前会自动生成当前数据的回滚包；恢复会替换数据库、设置和 Rime 配置，并需要重启相关组件。
          </InlineNotice>
          <div className="mgmt-workflow__buttons">
            <Button onClick={() => setConfirmOpen(true)} size="small" variant="danger">查看并确认恢复</Button>
          </div>
        </div>
      ) : null}
      {receipt ? (
        <Receipt detail="数据已恢复；请保留该回滚包，直到确认输入法和记忆均正常。" title={stringValue(receipt.rollbackPath, '恢复完成')} />
      ) : null}
      {error ? <InlineNotice title="恢复失败" tone="danger">{error}</InlineNotice> : null}

      <Dialog open={confirmOpen} onOpenChange={(open) => { if (!working) { setConfirmOpen(open); setConfirmed(false); } }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>确认恢复“{selected?.name ?? ''}”？</DialogTitle>
            <DialogDescription>恢复令牌绑定了备份内容，本机数据版本也必须与预览时一致。</DialogDescription>
          </DialogHeader>
          <InlineNotice title="危险操作" tone="danger">当前数据库、设置和输入法自定义文件会被备份包内容替换；执行前会生成回滚包。</InlineNotice>
          <label className="mgmt-workflow__confirm">
            <input checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} type="checkbox" />
            我已核对恢复范围，并确认替换当前本机数据。
          </label>
          {error ? <InlineNotice title="恢复失败" tone="danger">{error}</InlineNotice> : null}
          <DialogFooter>
            <Button disabled={working} onClick={() => setConfirmOpen(false)} variant="quiet">取消</Button>
            <Button disabled={!confirmed} loading={working} onClick={() => void applyRestore()} variant="danger">确认并恢复</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function parseImportPreview(payload: Record<string, unknown>): ImportPreview {
  const runtimeRevision = integerValue(payload.runtimeRevision, -1);
  const configurationHash = stringValue(payload.configurationHash);
  const requiresConfirmation = stringValue(payload.requiresConfirmation);
  if (!configurationHash.startsWith('sha256:') || runtimeRevision < 0 || !requiresConfirmation) {
    throw new Error('配置预览缺少文件哈希或本机版本绑定。');
  }
  return {
    valid: payload.valid === true,
    errors: arrayStrings(payload.errors),
    warnings: arrayStrings(payload.warnings),
    settings: asRecord(payload.settings),
    providers: asRecord(payload.providers),
    settingCount: integerValue(payload.settingCount),
    requiresRemoteModelConfirmation: payload.requiresRemoteModelConfirmation === true,
    configurationHash,
    requiresConfirmation,
    runtimeRevision,
  };
}

function parseRestorePreview(payload: Record<string, unknown>): RestorePreview {
  const runtimeRevision = integerValue(payload.runtimeRevision, -1);
  const restoreToken = stringValue(payload.restoreToken);
  const requiresConfirmation = stringValue(payload.requiresConfirmation);
  if (!/^[a-f0-9]{64}$/.test(restoreToken) || runtimeRevision < 0 || !requiresConfirmation) {
    throw new Error('恢复预览缺少备份校验或本机版本绑定。');
  }
  const counts = asRecord(payload.databaseCounts);
  return {
    valid: payload.valid === true,
    restoreToken,
    runtimeRevision,
    databaseCounts: Object.fromEntries(
      Object.entries(counts).map(([key, value]) => [key, integerValue(value)]),
    ),
    databaseMigrationVersion: integerValue(payload.databaseMigrationVersion),
    rimeFileCount: integerValue(payload.rimeFileCount),
    exclusions: arrayStrings(payload.exclusions),
    requiresConfirmation,
    requiresRestart: payload.requiresRestart === true,
  };
}

function configurationDiff(current: Record<string, unknown>, incoming: Record<string, unknown>) {
  const currentFlat = flattenObject(current);
  return Object.entries(flattenObject(incoming))
    .filter(([key, value]) => !Object.is(currentFlat[key], value))
    .map(([key, value]) => ({
      id: key,
      key: configurationKeyLabel(key),
      before: displayValue(currentFlat[key]),
      after: displayValue(value),
    }));
}

function flattenObject(value: Record<string, unknown>, prefix = ''): Record<string, JsonValue> {
  const result: Record<string, JsonValue> = {};
  for (const [key, child] of Object.entries(value)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (isPlainRecord(child)) Object.assign(result, flattenObject(child, path));
    else if (isJsonValue(child)) result[path] = child;
  }
  return result;
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function isJsonValue(value: unknown): value is JsonValue {
  if (value === null || ['string', 'number', 'boolean'].includes(typeof value)) return true;
  if (Array.isArray(value)) return value.every(isJsonValue);
  return isPlainRecord(value) && Object.values(value).every(isJsonValue);
}

function hasRoutes(capabilities: FrontendCapabilities | undefined, required: readonly ControlPathId[]) {
  const routeIds = new Set(capabilities?.routeIds ?? []);
  return required.every((pathId) => routeIds.has(pathId));
}

function NoticeList({ items, title, tone }: { items: string[]; title: string; tone: 'danger' | 'info' | 'warning' }) {
  if (!items.length) return null;
  return <InlineNotice title={title} tone={tone}><ul>{items.map((item) => <li key={item}>{item}</li>)}</ul></InlineNotice>;
}

function Receipt({ detail, title }: { detail: string; title: string }) {
  return (
    <div className="mgmt-workflow__receipt">
      <CheckCircle2 aria-hidden="true" size={18} />
      <div><strong>{title}</strong><span>{detail}</span></div>
    </div>
  );
}

function arrayStrings(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string') : [];
}

function integerValue(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isSafeInteger(value) ? value : fallback;
}

function numberValue(value: unknown): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : 0;
}

function displayValue(value: JsonValue | undefined): string {
  if (value === undefined) return '未设置';
  if (typeof value === 'boolean') return value ? '开启' : '关闭';
  if (typeof value === 'string' || typeof value === 'number') return String(value) || '空';
  if (value === null) return '空';
  return '结构化内容';
}

function configurationKeyLabel(key: string): string {
  const labels: Record<string, string> = {
    'context.tokenBudget': '上下文容量',
    'activeRag.allowRemoteModel': '允许远程深度生成',
    'privacy.allowRemoteModelForActiveRag': '允许向远程模型发送内容',
  };
  if (labels[key]) return labels[key];
  return '其他设置';
}

function providerLabel(id: string): string {
  return ({ instant: '即时预测模型', knowledge: '知识模型', voice: '语音模型' } as Record<string, string>)[id] ?? id;
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}
