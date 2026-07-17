import type { ErrorObject, ValidateFunction } from 'ajv';

import type { ContractTypeMap, GeneratedContractName } from './generated';
import {
  contractValidators,
  tolerantAgentEventValidator,
  tolerantAgentMessageValidator,
  tolerantRoomEventValidator,
} from './generated-validators';
import {
  normalizeAgentEvent,
  normalizeAgentMessage,
  normalizeObservationEvent,
  normalizeRoomEvent,
  type UiAgentEvent,
  type UiAgentMessage,
  type UiObservationEvent,
  type UiRoomEvent,
} from './ui-events';

export interface ContractIssue {
  instancePath: string;
  keyword: string;
  message: string;
  params: Record<string, unknown>;
}

export type ContractValidationResult<T> =
  | { ok: true; value: T }
  | { ok: false; issues: ContractIssue[] };

export class ContractValidationError extends Error {
  readonly contractName: string;
  readonly issues: ContractIssue[];

  constructor(contractName: string, issues: ContractIssue[]) {
    const detail = issues
      .slice(0, 3)
      .map((issue) => `${issue.instancePath || '/'} ${issue.message}`)
      .join('; ');
    super(`Invalid ${contractName} payload${detail ? `: ${detail}` : ''}`);
    this.name = 'ContractValidationError';
    this.contractName = contractName;
    this.issues = issues;
  }
}

const validators = contractValidators as unknown as Record<
  GeneratedContractName,
  ValidateFunction
>;

export function validateContract<Name extends GeneratedContractName>(
  name: Name,
  value: unknown,
): ContractValidationResult<ContractTypeMap[Name]> {
  const validator = validators[name];
  if (!validator) {
    throw new Error(`Contract validator is not registered: ${name}`);
  }
  if (validator(value)) {
    return { ok: true, value: value as ContractTypeMap[Name] };
  }
  return { ok: false, issues: normalizeErrors(validator.errors) };
}

export function parseContract<Name extends GeneratedContractName>(
  name: Name,
  value: unknown,
): ContractTypeMap[Name] {
  const result = validateContract(name, value);
  if (result.ok) return result.value;
  throw new ContractValidationError(name, result.issues);
}

export function parseAgentEvent(value: unknown): UiAgentEvent {
  const strict = validateContract('agent-event.v1', value);
  if (strict.ok) return normalizeAgentEvent(strict.value as Record<string, unknown>);
  if (tolerantAgentEventValidator(value)) {
    return normalizeAgentEvent(value as Record<string, unknown>);
  }
  throw new ContractValidationError('agent-event.v1', strict.issues);
}

export function parseRoomEvent(value: unknown): UiRoomEvent {
  const strict = validateContract('agent-room-event.v1', value);
  if (strict.ok) return normalizeRoomEvent(strict.value as unknown as Record<string, unknown>);
  if (tolerantRoomEventValidator(value)) {
    return normalizeRoomEvent(value as Record<string, unknown>);
  }
  throw new ContractValidationError('agent-room-event.v1', strict.issues);
}

export function parseObservationEvent(value: unknown): UiObservationEvent {
  return normalizeObservationEvent(parseContract('observation-event.v1', value));
}

export function parseAgentMessage(value: unknown): UiAgentMessage {
  const strict = validateContract('agent-message.v1', value);
  if (strict.ok) return normalizeAgentMessage(strict.value as Record<string, unknown>);
  if (tolerantAgentMessageValidator(value)) {
    return normalizeAgentMessage(value as Record<string, unknown>);
  }
  throw new ContractValidationError('agent-message.v1', strict.issues);
}

export function tryParseAgentMessage(value: unknown): ContractValidationResult<UiAgentMessage> {
  try {
    return { ok: true, value: parseAgentMessage(value) };
  } catch (error) {
    if (error instanceof ContractValidationError) {
      return { ok: false, issues: error.issues };
    }
    throw error;
  }
}

function normalizeErrors(errors: ErrorObject[] | null | undefined): ContractIssue[] {
  return (errors ?? []).map((error) => ({
    instancePath: error.instancePath,
    keyword: error.keyword,
    message: error.message ?? 'is invalid',
    params: error.params,
  }));
}
