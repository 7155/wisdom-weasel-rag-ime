import * as crypto from "node:crypto";
import { WebhookVerificationError, Worker } from "@notionhq/workers";

const worker = new Worker();
export default worker;

type KnowledgeQuery = {
  schemaVersion: "rag-ime.notion-query.v1";
  queryId: string;
  question: string;
  context: string;
  contextHash: string;
  generation: number;
  project: string;
  mode: "knowledge_answer" | "long_form" | "recall";
};

worker.webhook("enqueueKnowledgeQuery", {
  title: "Enqueue RAG-IME knowledge query",
  description: "Validates a signed Mac request and creates one idempotent RAG Queries row.",
  execute: async (events, { notion }) => {
    const dataSourceId = requiredEnv("RAG_IME_QUERY_DATA_SOURCE_ID");
    for (const event of events) {
      verifySignature(event.rawBody, event.headers);
      const query = parseQuery(event.body);
      const existing = await notion.dataSources.query({
        data_source_id: dataSourceId,
        filter: { property: "query_id", title: { equals: query.queryId } },
        page_size: 1,
      });
      if (existing.results.length > 0) {
        console.log(`duplicate query ignored: ${query.queryId}`);
        continue;
      }
      await notion.pages.create({
        parent: { type: "data_source_id", data_source_id: dataSourceId },
        properties: {
          query_id: { title: richText(query.queryId) },
          question: { rich_text: richText(query.question) },
          context: { rich_text: richText(query.context) },
          context_hash: { rich_text: richText(query.contextHash) },
          generation: { number: query.generation },
          project: { rich_text: richText(query.project) },
          mode: { rich_text: richText(query.mode) },
          status: { select: { name: "queued" } },
          answer: { rich_text: [] },
          sources: { rich_text: [] },
          error: { rich_text: [] },
          created_at: { date: { start: new Date().toISOString() } },
        },
      });
      console.log(`queued query: ${query.queryId}`);
    }
  },
});

function verifySignature(rawBody: string, headers: Record<string, string>): void {
  const secret = requiredEnv("RAG_IME_WEBHOOK_SECRET");
  const provided = headers["x-rag-ime-signature"];
  const expected = `sha256=${crypto.createHmac("sha256", secret).update(rawBody).digest("hex")}`;
  if (!provided || provided.length !== expected.length) {
    throw new WebhookVerificationError("Invalid RAG-IME signature");
  }
  if (!crypto.timingSafeEqual(Buffer.from(provided), Buffer.from(expected))) {
    throw new WebhookVerificationError("Invalid RAG-IME signature");
  }
}

function parseQuery(raw: Record<string, unknown>): KnowledgeQuery {
  const schemaVersion = text(raw.schemaVersion);
  const queryId = text(raw.queryId);
  const question = text(raw.question);
  const context = text(raw.context);
  const contextHash = text(raw.contextHash);
  const project = text(raw.project);
  const mode = text(raw.mode);
  const generation = Number(raw.generation);
  if (schemaVersion !== "rag-ime.notion-query.v1") throw new Error("Unsupported schemaVersion");
  if (!/^q-[a-f0-9]{16,64}$/i.test(queryId)) throw new Error("Invalid queryId");
  if (!question || question.length > 4000) throw new Error("Invalid question");
  if (context.length > 4000) throw new Error("Context is too long");
  if (!/^sha256:[a-f0-9]{16,64}$/i.test(contextHash)) throw new Error("Invalid contextHash");
  if (!Number.isSafeInteger(generation) || generation < 0) throw new Error("Invalid generation");
  if (!project || project.length > 160) throw new Error("Invalid project");
  if (!["knowledge_answer", "long_form", "recall"].includes(mode)) throw new Error("Invalid mode");
  return {
    schemaVersion: "rag-ime.notion-query.v1",
    queryId,
    question,
    context,
    contextHash,
    generation,
    project,
    mode: mode as KnowledgeQuery["mode"],
  };
}

function richText(value: string): Array<{ type: "text"; text: { content: string } }> {
  const chunks: Array<{ type: "text"; text: { content: string } }> = [];
  for (let index = 0; index < value.length; index += 1900) {
    chunks.push({ type: "text", text: { content: value.slice(index, index + 1900) } });
  }
  return chunks;
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function requiredEnv(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}
