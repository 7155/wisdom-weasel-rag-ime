import { appendFileSync } from "node:fs";

type TraceEnvironment = Record<string, string | undefined>;
type TraceRecord = {
  schemaVersion: "paw.ego-browser-step.v1";
  event: "started" | "completed" | "failed";
  action: string;
  target: string;
  atMs: number;
  error?: string;
};

const ACTION_NAMES: Record<string, string> = {
  goto: "navigate",
  reload: "reload",
  click: "click",
  dblclick: "click",
  hover: "hover",
  drag: "drag",
  fill: "type",
  type: "type",
  press: "press",
  selectOption: "select",
  check: "check",
  uncheck: "uncheck",
  setInputFiles: "upload",
  screenshot: "screenshot",
  snapshot: "snapshot",
  createTab: "new_tab",
  switchTab: "switch_tab",
  closeTab: "close_tab",
  useOrCreate: "task_space",
  new: "task_space",
  switch: "task_space",
  claim: "task_space",
  complete: "task_complete",
  handOff: "hand_off",
  takeOver: "take_over",
  waitForAgentControl: "wait_for_control",
};

const LOCATOR_BUILDERS = new Set([
  "locator",
  "getByRole",
  "getByText",
  "getByLabel",
  "getByPlaceholder",
  "getByAltText",
  "getByTitle",
  "getByTestId",
  "filter",
  "first",
  "last",
  "nth",
]);

export function instrumentPawTrace(
  context: Record<string, any>,
  env: TraceEnvironment,
): Record<string, any> {
  const tracePath = String(env.EGO_PAW_TRACE_PATH ?? "").trim();
  if (!tracePath) return context;
  for (const key of ["page", "browser", "taskSpaces"]) {
    if (context[key] && (typeof context[key] === "object" || typeof context[key] === "function")) {
      context[key] = traceValue(context[key], key, tracePath);
    }
  }
  return context;
}

function traceValue(value: any, path: string, tracePath: string): any {
  if (!value || (typeof value !== "object" && typeof value !== "function")) {
    return value;
  }
  return new Proxy(value, {
    get(target, property, receiver) {
      const child = Reflect.get(target, property, receiver);
      if (typeof property === "symbol") return child;
      const method = String(property);
      if (typeof child !== "function") {
        return traceValue(child, `${path}.${method}`, tracePath);
      }
      return (...args: unknown[]) => {
        const builderPath = LOCATOR_BUILDERS.has(method)
          ? `${path}.${method}(${selection(args)})`
          : path;
        const action = ACTION_NAMES[method];
        const targetLabel = action ? actionTarget(path, method, args) : "";
        if (action) writeTrace(tracePath, { event: "started", action, target: targetLabel });
        let result: any;
        try {
          result = Reflect.apply(child, target, args);
        } catch (error) {
          if (action) writeTrace(tracePath, {
            event: "failed",
            action,
            target: targetLabel,
            error: errorText(error),
          });
          throw error;
        }
        if (result && typeof result.then === "function") {
          return result.then(
            (resolved: any) => {
              if (action) writeTrace(tracePath, { event: "completed", action, target: targetLabel });
              return traceValue(resolved, builderPath, tracePath);
            },
            (error: unknown) => {
              if (action) writeTrace(tracePath, {
                event: "failed",
                action,
                target: targetLabel,
                error: errorText(error),
              });
              throw error;
            },
          );
        }
        if (action) writeTrace(tracePath, { event: "completed", action, target: targetLabel });
        return traceValue(result, builderPath, tracePath);
      };
    },
  });
}

function actionTarget(path: string, method: string, args: unknown[]): string {
  if (method === "goto" || method === "createTab") return safeUrl(args[0]);
  if (path === "taskSpaces") return compact(args[0], 120);
  if (path.endsWith(".mouse") && ["click", "dblclick", "hover", "drag"].includes(method)) {
    return compact(args[0], 160);
  }
  return compact(path.replace(/^page\./, ""), 180);
}

function selection(args: unknown[]): string {
  const head = compact(args[0], 90);
  if (!head) return "";
  const options = args[1];
  if (!options || typeof options !== "object" || Array.isArray(options)) return head;
  const name = compact((options as Record<string, unknown>).name, 70);
  return name ? `${head}: ${name}` : head;
}

function safeUrl(value: unknown): string {
  const raw = compact(value, 320);
  try {
    const url = new URL(raw);
    url.username = "";
    url.password = "";
    url.hash = "";
    for (const key of [...url.searchParams.keys()]) {
      if (/(token|secret|key|session|auth|password|code)/i.test(key)) {
        url.searchParams.set(key, "[redacted]");
      }
    }
    return url.toString();
  } catch {
    return raw;
  }
}

function compact(value: unknown, limit: number): string {
  if (typeof value === "string" || typeof value === "number") {
    return String(value).replace(/\s+/g, " ").trim().slice(0, limit);
  }
  if (Array.isArray(value)) {
    return value.slice(0, 4).map((item) => compact(item, 40)).join(", ").slice(0, limit);
  }
  if (value && typeof value === "object") {
    const record = value as Record<string, unknown>;
    if (typeof record.selector === "string") return compact(record.selector, limit);
    if (typeof record.x === "number" && typeof record.y === "number") {
      return `${record.x}, ${record.y}`;
    }
  }
  return "";
}

function writeTrace(
  tracePath: string,
  value: Omit<TraceRecord, "schemaVersion" | "atMs">,
): void {
  try {
    const record: TraceRecord = {
      schemaVersion: "paw.ego-browser-step.v1",
      ...value,
      atMs: Date.now(),
    };
    appendFileSync(tracePath, `${JSON.stringify(record)}\n`, {
      encoding: "utf8",
      mode: 0o600,
    });
  } catch {
    // Visibility must never interrupt the browser action it reports.
  }
}

function errorText(error: unknown): string {
  return (error instanceof Error ? error.message : String(error ?? ""))
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 240);
}
