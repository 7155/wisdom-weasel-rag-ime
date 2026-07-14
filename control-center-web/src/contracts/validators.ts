import Ajv2020, { type AnySchema, type ErrorObject, type ValidateFunction } from 'ajv/dist/2020.js';
import addFormats from 'ajv-formats';

import type { ContractTypeMap, GeneratedContractName } from './generated';
import { contractSchemas } from './schema-index';
import {
  normalizeAgentEvent,
  normalizeAgentMessage,
  normalizeRoomEvent,
  type UiAgentEvent,
  type UiAgentMessage,
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

const ajv = new Ajv2020({
  allErrors: true,
  allowUnionTypes: true,
  strict: false,
});
addFormats(ajv);

const validators = new Map<GeneratedContractName, ValidateFunction>();
for (const [name, schema] of Object.entries(contractSchemas) as [
  GeneratedContractName,
  (typeof contractSchemas)[GeneratedContractName],
][]) {
  validators.set(name, ajv.compile(schema as unknown as AnySchema));
}

const tolerantAgentEventValidator = ajv.compile(
  tolerantEventSchema('agent-event.v1') as AnySchema,
);
const tolerantRoomEventValidator = ajv.compile(
  tolerantEventSchema('agent-room-event.v1') as AnySchema,
);
const tolerantAgentMessageValidator = ajv.compile(tolerantAgentMessageSchema() as AnySchema);

export function validateContract<Name extends GeneratedContractName>(
  name: Name,
  value: unknown,
): ContractValidationResult<ContractTypeMap[Name]> {
  const validator = validators.get(name);
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

function tolerantEventSchema(name: 'agent-event.v1' | 'agent-room-event.v1'): object {
  const schema = cloneSchema(contractSchemas[name]);
  delete schema.$id;
  const properties = schema.properties as Record<string, unknown>;
  properties.eventType = { type: 'string', minLength: 1 };
  return schema;
}

function tolerantAgentMessageSchema(): object {
  const schema = cloneSchema(contractSchemas['agent-message.v1']);
  delete schema.$id;
  const definitions = schema.$defs as Record<string, Record<string, unknown>>;
  const block = definitions.block;
  const properties = block.properties as Record<string, unknown>;
  properties.type = { type: 'string', minLength: 1 };
  return schema;
}

function cloneSchema(schema: unknown): Record<string, unknown> {
  return JSON.parse(JSON.stringify(schema)) as Record<string, unknown>;
}

function normalizeErrors(errors: ErrorObject[] | null | undefined): ContractIssue[] {
  return (errors ?? []).map((error) => ({
    instancePath: error.instancePath,
    keyword: error.keyword,
    message: error.message ?? 'is invalid',
    params: error.params,
  }));
}
