import { Archive, FileCheck2, FolderOpen, KeyRound, RefreshCw, RotateCcw, Settings2 } from 'lucide-react';
import { useEffect, useMemo, useState } from 'react';
import { Button, EmptyState, Field, Input, Switch } from '@/components/primitives';
import { useConfigurationQueries } from './api';
import {
  DataTable,
  InlineNotice,
  ManagementPage,
  ManagementSection,
  MetricStrip,
  QueryState,
  StatusBadge,
  WorkflowAction,
  arrayRecords,
  asRecord,
  configuredLabel,
  numberValue,
  stringValue,
  valueAt,
} from '@/features/overview/management-ui';

type DraftValue = string | number | boolean;

export function ConfigurationFeature() {
  const queries = useConfigurationQueries();
  const settingsEnvelope = asRecord(queries.settings.data);
  const settings = asRecord(settingsEnvelope.settings);
  const runtimeConfig = asRecord(settingsEnvelope.runtimeConfig);
  const settingsRevision = stringValue(
    settingsEnvelope.settingsRevision,
    stringValue(settingsEnvelope.settingsHash, stringValue(runtimeConfig.settingsRevision, 'unknown')),
  );
  const runtimeRevision = numberValue(
    settingsEnvelope.runtimeRevision,
    numberValue(runtimeConfig.runtimeRevision),
  );
  const schemaEnvelope = asRecord(queries.schema.data);
  const sections = arrayRecords(schemaEnvelope.sections);
  const [activeSection, setActiveSection] = useState('');
  const [expertMode, setExpertMode] = useState(false);
  const [changes, setChanges] = useState<Record<string, DraftValue>>({});
  const [configurationFile, setConfigurationFile] = useState('');
  const [restoreFile, setRestoreFile] = useState('');
  const [backupDestination, setBackupDestination] = useState('');

  useEffect(() => {
    if (!activeSection && sections.length) setActiveSection(stringValue(sections[0]?.id));
  }, [activeSection, sections]);

  const section = sections.find((item) => stringValue(item.id) === activeSection) ?? sections[0];
  const fields = arrayRecords(section?.fields).filter((field) => expertMode || field.expert !== true);
  const diffRows = useMemo(() => Object.entries(changes).map(([key, next]) => ({
    id: key,
    key,
    before: isSecretKey(key) ? configuredLabel(valueAt(settings, key)) : displayDraftValue(valueAt(settings, key)),
    after: isSecretKey(key) ? (String(next).trim() ? 'configured' : 'not configured') : displayDraftValue(next),
    applyMode: stringValue(findField(sections, key).applyMode, 'live'),
  })), [changes, sections, settings]);
  const error = (queries.settings.error ?? queries.schema.error ?? queries.capabilities.error) as Error | null;
  const pending = queries.settings.isPending || queries.schema.isPending || queries.capabilities.isPending;
  const refresh = () => void Promise.all([queries.settings.refetch(), queries.schema.refetch()]);

  const chooseFile = async (purpose: 'configuration-import' | 'restore' | 'export-destination') => {
    if (!queries.transport.pickFiles) return;
    const files = await queries.transport.pickFiles({
      accepts: purpose === 'configuration-import' ? ['.json', '.yaml', '.yml'] : purpose === 'restore' ? ['.ragime-backup', '.zip'] : undefined,
      multiple: false,
      purpose,
    });
    const selected = files[0];
    if (!selected) return;
    if (purpose === 'configuration-import') setConfigurationFile(selected.name);
    if (purpose === 'restore') setRestoreFile(selected.name);
    if (purpose === 'export-destination') setBackupDestination(selected.name);
  };

  return (
    <ManagementPage
      actions={
        <>
          <Switch checked={expertMode} label="高级设置" onCheckedChange={setExpertMode} />
          <Button leadingIcon={<RefreshCw size={15} />} loading={queries.settings.isFetching} onClick={refresh} size="small">刷新</Button>
        </>
      }
      description="按分组调整设置、查看差异、导入配置，并创建可回滚备份。"
      eyebrow="SETTINGS"
      routeId="configuration"
      title="配置与迁移"
    >
      <QueryState error={error} isPending={pending} onRetry={refresh}>
        <ManagementSection title="配置快照">
          <MetricStrip items={[
            { label: 'Schema', value: stringValue(schemaEnvelope.schemaVersion, 'unknown'), detail: `${sections.length} 个分组`, icon: Settings2 },
            { label: '设置版本', value: settingsRevision, detail: '当前版本', icon: FileCheck2 },
            { label: '运行版本', value: runtimeRevision, detail: '已生效设置', icon: RefreshCw },
            { label: '安全存储', value: queries.capabilities.data?.native.keychain ? 'available' : 'unavailable', detail: '秘密不会回显', icon: KeyRound, tone: queries.capabilities.data?.native.keychain ? 'success' : 'warning' },
          ]} />
          <InlineNotice title="秘密字段" tone="success">已保存的秘密只显示 configured / not configured。新值不会出现在差异明文、收据或日志中。</InlineNotice>
        </ManagementSection>

        <ManagementSection title="设置表单" description="按分组逐项调整设置；开启高级设置可显示更多选项。">
          {sections.length ? (
            <div className="mgmt-grid-2">
              <div className="mgmt-stack">
                <label className="ui-field">
                  <span className="ui-field__label">Section</span>
                  <select className="ui-input" onChange={(event) => setActiveSection(event.target.value)} value={stringValue(section?.id)}>
                    {sections.map((item) => <option key={stringValue(item.id)} value={stringValue(item.id)}>{stringValue(item.label, stringValue(item.id))}</option>)}
                  </select>
                </label>
                <div className="mgmt-list">
                  {fields.map((field) => (
                    <SettingField
                      field={field}
                      key={stringValue(field.key)}
                      onChange={(value) => setChanges((current) => ({ ...current, [stringValue(field.key)]: value }))}
                      value={changes[stringValue(field.key)] ?? valueAt(settings, stringValue(field.key))}
                    />
                  ))}
                </div>
              </div>
              <div className="mgmt-stack">
                <h3 style={{ fontSize: 12, margin: 0 }}>待应用差异</h3>
                {diffRows.length ? (
                  <DataTable caption="配置差异" columns={[
                    { key: 'key', label: 'Key', width: '32%' },
                    { key: 'before', label: '当前' },
                    { key: 'after', label: '目标' },
                    { key: 'applyMode', label: '应用', width: '18%' },
                  ]} rows={diffRows} />
                ) : <EmptyState description="修改字段后会在这里显示差异。" icon={Settings2} title="没有待应用变更" />}
                <WorkflowAction
                  actionId="configuration.settings.apply"
                  description="仅保存本次字段差异，并按应用方式刷新相关组件。"
                  mutationKey={['configuration', 'mutation', 'settings']}
                  preview={diffRows.length ? diffRows.map((row) => `${row.key}: ${row.before} -> ${row.after}`) : ['当前没有设置差异。']}
                  risk={diffRows.some((row) => row.applyMode !== 'live') ? 'R2' : 'R1'}
                  title="应用设置差异"
                />
              </div>
            </div>
          ) : <EmptyState description="当前没有可显示的设置分组。" icon={Settings2} title="设置为空" />}
        </ManagementSection>

        <ManagementSection title="配置导入" description="选择配置文件并预览差异；敏感字段不会显示。">
          <div className="mgmt-toolbar">
            <Button disabled={!queries.transport.pickFiles} leadingIcon={<FolderOpen size={15} />} onClick={() => void chooseFile('configuration-import')} size="small">选择配置</Button>
            <span className="mgmt-muted">{configurationFile || '未选择文件'}</span>
          </div>
          <WorkflowAction
            actionId="configuration.import"
            description="校验 JSON/YAML 并预览设置差异；敏感字段单独确认。"
            mutationKey={['configuration', 'mutation', 'import']}
            preview={[`文件：${configurationFile || '尚未选择'}`, '文件类型：JSON/YAML。', '远程模型配置与敏感字段需要额外确认。']}
            risk="R2"
            title="导入配置"
          />
        </ManagementSection>

        <ManagementSection title="备份与恢复" description="备份不含 API Key、模型权重、缓存与日志；恢复前自动生成回滚包。">
          <div className="mgmt-grid-2">
            <div className="mgmt-stack">
              <Button disabled={!queries.transport.pickFiles} leadingIcon={<Archive size={15} />} onClick={() => void chooseFile('export-destination')} size="small">选择备份位置</Button>
              <span className="mgmt-muted">{backupDestination || '未选择位置'}</span>
              <WorkflowAction
                actionId="configuration.backup-export"
                description="导出本地数据库、管理设置和 Rime 自定义 YAML。"
                mutationKey={['configuration', 'mutation', 'backup-export']}
                preview={[`目标：${backupDestination || '尚未选择'}`, '备份不包含秘密。', '完成后显示文件数、大小与校验值。']}
                risk="R1"
                title="导出可移植备份"
              />
            </div>
            <div className="mgmt-stack">
              <Button disabled={!queries.transport.pickFiles} leadingIcon={<RotateCcw size={15} />} onClick={() => void chooseFile('restore')} size="small">选择恢复包</Button>
              <span className="mgmt-muted">{restoreFile || '未选择恢复包'}</span>
              <WorkflowAction
                actionId="configuration.restore"
                applyLabel="批准恢复"
                description="校验恢复包与数据库版本，并先创建回滚包。"
                mutationKey={['configuration', 'mutation', 'restore']}
                preview={[`恢复包：${restoreFile || '尚未选择'}`, '恢复前需要再次确认。', '先创建回滚包；已保存的秘密不改变。']}
                risk="R3"
                title="恢复可移植备份"
              />
            </div>
          </div>
        </ManagementSection>
      </QueryState>
    </ManagementPage>
  );
}

function SettingField({ field, onChange, value }: { field: Record<string, unknown>; onChange: (value: DraftValue) => void; value: unknown }) {
  const key = stringValue(field.key);
  const label = stringValue(field.label, key);
  const description = stringValue(field.description);
  const type = stringValue(field.type, 'string');
  const secret = isSecretKey(key) || type === 'secret' || type === 'password';
  const id = `configuration-${key.replace(/[^A-Za-z0-9_-]/g, '-')}`;
  const [secretDraft, setSecretDraft] = useState('');

  if (type === 'boolean' && !secret) {
    return <div className="mgmt-list__row"><Switch checked={value === true} description={description} label={label} onCheckedChange={onChange} /></div>;
  }
  if (Array.isArray(field.options) && !secret) {
    return (
      <div className="mgmt-list__row">
        <Field description={description} htmlFor={id} label={label}>
          <select className="ui-input" id={id} onChange={(event) => onChange(event.target.value)} value={stringValue(value)}>
            {field.options.map((option) => <option key={String(option)} value={String(option)}>{String(option)}</option>)}
          </select>
        </Field>
      </div>
    );
  }
  if (['string', 'number', 'integer', 'secret', 'password'].includes(type) || secret) {
    return (
      <div className="mgmt-list__row">
        <Field
          description={secret ? `当前：${configuredLabel(valueAt({ value }, 'value'))}；留空表示不改变` : description}
          htmlFor={id}
          label={label}
        >
          <Input
            autoComplete={secret ? 'new-password' : undefined}
            id={id}
            max={typeof field.max === 'number' ? field.max : undefined}
            min={typeof field.min === 'number' ? field.min : undefined}
            onChange={(event) => {
              if (secret) setSecretDraft(event.target.value);
              onChange(type === 'number' || type === 'integer' ? Number(event.target.value) : event.target.value);
            }}
            placeholder={secret ? '输入新值' : undefined}
            step={typeof field.step === 'number' ? field.step : undefined}
            type={secret ? 'password' : type === 'number' || type === 'integer' ? 'number' : 'text'}
            value={secret ? secretDraft : stringValue(value)}
          />
        </Field>
      </div>
    );
  }
  return <div className="mgmt-list__row"><span>{label}</span><StatusBadge label="请在对应功能中调整" tone="info" /></div>;
}

function findField(sections: Record<string, unknown>[], key: string): Record<string, unknown> {
  return sections.flatMap((section) => arrayRecords(section.fields)).find((field) => stringValue(field.key) === key) ?? {};
}

function isSecretKey(key: string): boolean {
  return /token|secret|password|api.?key|authorization|cookie/i.test(key);
}

function displayDraftValue(value: unknown): string {
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return String(value);
  if (typeof value === 'string') return value || '(empty)';
  return value === undefined ? '(unset)' : '(structured)';
}
