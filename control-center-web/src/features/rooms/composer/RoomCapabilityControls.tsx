import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useControlTransport } from '@/app/control-transport';
import { Button, Select } from '@/components/primitives';
import { ToolPicker } from '@/features/agent/composer/ToolPicker';
import { publicAgentErrorText } from '@/features/agent/public-error';
import { toolItems } from '@/features/agent/types';
import { requireSessionCapabilityCatalog, type CapabilityPreference } from '@/features/plugins/capability-policy';
import { roomParticipantPlanetName } from '../room-participant-identity';

type Participant = {
  id: string;
  sessionId: string;
  displayName: string;
  ordinal?: number;
  status: string;
};

/** Room partners are ordinary Sessions; these controls update that same policy owner. */
export function RoomCapabilityControls({ participants, aliases = {}, busy, disabled, onSelectTool }: {
  participants: Participant[];
  aliases?: Readonly<Record<string, string>>;
  busy: boolean;
  disabled: boolean;
  onSelectTool: (name: string) => void;
}) {
  const transport = useControlTransport();
  const client = useQueryClient();
  const [selectedId, setSelectedId] = useState('');
  const active = participants.filter((participant) => participant.status === 'active' && participant.sessionId);
  const selected = active.find((participant) => participant.id === selectedId) ?? active[0];
  const sessionId = selected?.sessionId ?? '';
  const queryKey = (id: string) => ['room-composer-capabilities', id];
  async function read(id: string, signal?: AbortSignal) {
    const response = await transport.request({ pathId: 'agent.tools.list', query: { sessionId: id }, signal });
    return { catalog: requireSessionCapabilityCatalog(response, id), tools: toolItems(response) };
  }
  const query = useQuery({
    queryKey: queryKey(sessionId),
    queryFn: ({ signal }) => read(sessionId, signal),
    enabled: Boolean(sessionId) && !disabled,
    retry: false,
  });
  const mutation = useMutation({
    mutationFn: async ({ owner, canonicalId, preference }: { owner: string; canonicalId: string; preference: CapabilityPreference }) => {
      const current = await read(owner);
      await transport.request({
        pathId: 'agent.session.capability-policy.update', params: { sessionId: owner },
        body: { capabilityDisclosurePreferences: {
          ...current.catalog.sessionPolicy!.disclosurePreferences.session,
          [canonicalId]: preference,
        } },
      });
      const confirmed = await read(owner);
      if (!confirmed.catalog.items.some((item) => item.canonicalId === canonicalId)
        || (confirmed.catalog.sessionPolicy!.disclosurePreferences.session[canonicalId] ?? 'inherit') !== preference) {
        throw new Error('设置已提交，但暂时无法确认该功能的状态，请重新读取。');
      }
      client.setQueryData(queryKey(owner), confirmed);
      return confirmed;
    },
  });
  const error = mutation.isError && mutation.variables.owner === sessionId ? mutation.error : query.error;
  if (!selected) return null;
  return <>
    <Select
      aria-label="选择要设置记忆和插件的伙伴"
      value={selected.id}
      options={active.map((participant) => ({ value: participant.id, label: aliases[participant.id] ?? roomParticipantPlanetName(participant) }))}
      onValueChange={setSelectedId}
    />
    <ToolPicker
      sessionId={sessionId}
      capabilityCatalog={query.data?.catalog}
      tools={query.data?.tools ?? []}
      status={query.data ? 'ready' : query.isError ? 'failed' : 'loading'}
      adjustmentDisabled={busy || disabled}
      capabilityPolicyPending={mutation.isPending}
      disabled={disabled}
      requestOpen={0}
      onSelect={(tool) => onSelectTool(tool.displayName)}
      onCapabilityPreferenceChange={(canonicalId, preference) => {
        if (!busy && !disabled && !mutation.isPending) mutation.mutate({ owner: sessionId, canonicalId, preference });
      }}
    />
    {error ? <span role="alert" className="room-composer__capability-error">
      {publicAgentErrorText(error)}
      <Button size="small" variant="quiet" onClick={() => { mutation.reset(); void query.refetch(); }}>重新读取</Button>
    </span> : null}
  </>;
}
