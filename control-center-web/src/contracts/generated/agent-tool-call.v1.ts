/* eslint-disable */
/**
 * This file is generated. Do not edit it by hand.
 * Source: rag_ime/contracts/json/agent-tool-call.v1.json
 */

export interface AgentToolCallV1 {
  schemaVersion: 'rag-ime.agent-tool-call.v1';
  sessionId: string;
  tool:
    | 'ime_overview'
    | 'ime_input'
    | 'ime_voice'
    | 'ime_planning'
    | 'agent_schedule'
    | 'ime_memory'
    | 'ime_knowledge'
    | 'ime_models'
    | 'ime_runtime'
    | 'ime_configuration'
    | 'ime_agents'
    | 'agent_plan'
    | 'ime_plugins'
    | 'workspace_list'
    | 'workspace_read'
    | 'workspace_search'
    | 'workspace_patch'
    | 'workspace_shell';
  toolCallId: string;
  args: {
    [k: string]: unknown;
  };
  runtimeContext?: {
    schemaVersion: 'rag-ime.agent-runtime-context.v1';
    /**
     * @minItems 1
     * @maxItems 2
     */
    forkSessions:
      | [
          {
            sessionId: string;
            sessionFile: string;
            parentSessionFile: string;
            parentLeafId: string;
            thinkingOverride?: 'off';
          },
        ]
      | [
          {
            sessionId: string;
            sessionFile: string;
            parentSessionFile: string;
            parentLeafId: string;
            thinkingOverride?: 'off';
          },
          {
            sessionId: string;
            sessionFile: string;
            parentSessionFile: string;
            parentLeafId: string;
            thinkingOverride?: 'off';
          },
        ];
  };
}
