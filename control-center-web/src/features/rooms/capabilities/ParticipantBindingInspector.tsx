import { Bot, Boxes, Fingerprint, Link2, LockKeyhole, UserRound } from 'lucide-react';
import type { DefinitionReferenceProjection, ParticipantBindingProjection } from '@/contracts/capability-center-reducer';
import './capability-center.css';

export function ParticipantBindingInspector({ binding }: { binding: ParticipantBindingProjection }) {
  return <section className="participant-binding" aria-label="Participant Binding 检查器">
    <header><span><Link2 size={15} /><strong>Participant Binding</strong></span><small>generation {binding.generation}</small></header>
    <dl>
      <div><dt><UserRound size={13} />Participant</dt><dd>{binding.participantId}</dd></div>
      <div><dt><Bot size={13} />Session</dt><dd>{binding.sessionId}</dd></div>
      <div><dt><LockKeyhole size={13} />Capability</dt><dd>{binding.capabilityRevision} · epoch {binding.capabilityEpoch}</dd></div>
      <div><dt><Boxes size={13} />Compiled</dt><dd>{binding.compiledRuntimeProfileRef.profileId} · {binding.compiledRuntimeProfileRef.revision}</dd></div>
      {binding.roomBindingRef ? <div><dt><Link2 size={13} />Room Binding</dt><dd>{binding.roomBindingRef.bindingId}</dd></div> : null}
    </dl>
    <div className="participant-binding__refs">
      <DefinitionRef label="Persona" reference={binding.personaRef} />
      <DefinitionRef label="协作岗位" reference={binding.collaborationRoleRef} />
      <DefinitionRef label="Agent 模板" reference={binding.agentTemplateRef} />
      {binding.collaborationProfileRef ? <DefinitionRef label="角色书" reference={binding.collaborationProfileRef} /> : null}
      <span><small>Runtime Profile</small><strong>{binding.compiledRuntimeProfileRef.profileId}</strong><i>{binding.compiledRuntimeProfileRef.revision}</i><b title={binding.compiledRuntimeProfileRef.contentHash}><Fingerprint size={11} />{shortHash(binding.compiledRuntimeProfileRef.contentHash)}</b></span>
    </div>
  </section>;
}

function DefinitionRef({ label, reference }: { label: string; reference: DefinitionReferenceProjection }) {
  return <span><small>{label}</small><strong>{reference.id}</strong><i>v{reference.version}</i><b title={reference.contentHash}><Fingerprint size={11} />{shortHash(reference.contentHash)}</b></span>;
}

function shortHash(value: string): string { return `${value.slice(0, 13)}…${value.slice(-7)}`; }
