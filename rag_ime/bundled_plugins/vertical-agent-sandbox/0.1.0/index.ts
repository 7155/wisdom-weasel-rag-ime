const gatewayUrl = process.env.RAG_IME_AGENT_TOOL_URL ?? "";
const gatewayToken = process.env.RAG_IME_AGENT_TOOL_TOKEN ?? "";
const sessionId = process.env.RAG_IME_AGENT_SESSION_ID ?? "";

type SandboxParams = {
  op: "status" | "run";
  suiteId?: string;
  suiteRevision?: string;
};

type GatewayPayload = {
  ok?: boolean;
  error?: string;
  errorCode?: string;
  retryable?: boolean;
  result?: Record<string, unknown>;
};

async function callSandboxGateway(
  toolCallId: string,
  params: SandboxParams,
  signal?: AbortSignal,
): Promise<Record<string, unknown>> {
  if (!gatewayUrl || !gatewayToken || !sessionId) {
    throw new Error("RAG-IME vertical sandbox gateway is not configured for this Session");
  }

  const response = await fetch(gatewayUrl, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-RAG-IME-Agent-Token": gatewayToken,
    },
    body: JSON.stringify({
      schemaVersion: "rag-ime.agent-tool-call.v1",
      sessionId,
      tool: "sandbox",
      toolCallId,
      args: params,
    }),
    signal,
  });
  const payload = await response.json() as GatewayPayload;
  if (!response.ok || payload.ok !== true || !payload.result) {
    const errorCode = payload.errorCode || `http_${response.status}`;
    const retryable = payload.retryable === true;
    throw new Error(
      `${payload.error || `RAG-IME vertical sandbox gateway failed with HTTP ${response.status}`} `
        + `[errorCode=${errorCode}; retryable=${retryable}]`,
    );
  }
  return payload.result;
}

export default function registerVerticalAgentSandbox(pi: any) {
  pi.registerTool({
    name: "sandbox",
    label: "Vertical Agent Sandbox",
    description: "Run an allowlisted vertical Agent suite in a PAW-owned local sandbox and return SandboxRun, Trace, and EvalRun identities.",
    promptSnippet: "Use the PAW vertical Agent sandbox for a registered fixture suite; report the returned SandboxRun, Trace, and EvalRun links.",
    promptGuidelines: [
      "Only run a registered suite and describe the result as a local fixture evaluation.",
      "Do not treat sandbox output as permission to modify production Memory or Knowledge.",
    ],
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        op: {
          type: "string",
          enum: ["status", "run"],
          description: "检查 Connector 状态，或运行已注册的垂直 Agent suite。",
        },
        suiteId: {
          type: "string",
          minLength: 1,
          maxLength: 120,
          description: "运行时使用的已注册垂直 Agent suite id。Version 0.1.0 exposes the SGG showcase.",
        },
        suiteRevision: {
          type: "string",
          minLength: 1,
          maxLength: 120,
          description: "Optional exact suite revision; the PAW gateway validates it against the catalog.",
        },
      },
      required: ["op"],
    },
    executionMode: "sequential",
    async execute(
      toolCallId: string,
      params: SandboxParams,
      signal?: AbortSignal,
      onUpdate?: (value: unknown) => void,
    ) {
      onUpdate?.({
        content: [{ type: "text", text: params.op === "status" ? "正在检查垂直 Agent 沙盒…" : "正在启动垂直 Agent 沙盒…" }],
        details: { summary: params.op === "status" ? "正在检查垂直 Agent 沙盒…" : "正在启动垂直 Agent 沙盒…" },
      });
      const result = await callSandboxGateway(toolCallId, params, signal);
      return {
        content: [{ type: "text", text: JSON.stringify(result) }],
        details: result,
      };
    },
  });
}
