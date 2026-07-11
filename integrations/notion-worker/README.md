# Notion Worker Template

This directory contains the RAG-IME webhook capability and the matching Custom Agent instructions.

Notion Workers are currently scaffolded and deployed by the official `ntn` CLI, so keep the CLI-generated package metadata instead of pinning an SDK version in this repository:

```bash
ntn workers new rag-ime-knowledge-worker
cp integrations/notion-worker/src/index.ts rag-ime-knowledge-worker/src/index.ts
cd rag-ime-knowledge-worker
ntn workers env set RAG_IME_QUERY_DATA_SOURCE_ID=<data-source-id>
ntn workers env set RAG_IME_WEBHOOK_SECRET=<random-secret>
ntn workers env set NOTION_API_TOKEN=<internal-integration-token>
ntn workers deploy
ntn workers webhooks list
```

The webhook only acknowledges with HTTP 202. It cannot serve query status. Configure either a separate status relay or a local read-only Notion API token for Sidecar polling; see `docs/notion-personal-knowledge.md`.
