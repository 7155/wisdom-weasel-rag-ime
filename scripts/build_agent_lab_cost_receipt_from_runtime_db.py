#!/usr/bin/env python3
"""Build an Agent Lab cost estimate from retained Runtime usage events.

The Runtime DB is opened immutable and the output is a separate estimate
receipt.  This does not alter the original run receipt or pretend an estimate
is a provider bill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_lab_cost import build_agent_lab_cost_receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-db", type=Path, required=True)
    parser.add_argument("--pricing-config", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--published-date", required=True)
    parser.add_argument("--source-url", default="https://platform.openai.com/docs/pricing")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    runtime_db = args.runtime_db.expanduser().resolve(strict=True)
    pricing_config = args.pricing_config.expanduser().resolve(strict=True)
    pricing = _pricing(pricing_config, str(args.model))
    usage = _runtime_usage(runtime_db)
    if not any(usage.values()):
        raise SystemExit("runtime DB has no provider usage events")
    receipt = build_agent_lab_cost_receipt({
        "schemaVersion": "rag-ime.agent-lab-cost-request.v1",
        "pricingIdentity": {
            "pricingId": f"{pricing['provider']}-api-{args.model}-{args.published_date}",
            "provider": pricing["provider"],
            "model": args.model,
            "currency": "USD",
            "unit": "per_million_tokens",
            "rates": pricing["rates"],
            "publishedDate": str(args.published_date),
            "sourceUrl": str(args.source_url),
            "sourceSha256": _sha256_file(pricing_config),
        },
        "usage": {
            "available": True,
            "uncachedInputTokens": usage["input"],
            "cachedInputTokens": usage["cacheRead"],
            "outputTokens": usage["output"],
            "sourceRef": f"runtime-db:{args.run_id}",
            "sourceSha256": _sha256_file(runtime_db),
        },
    })
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.tmp")
    temporary.write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(output)
    print(json.dumps({
        "status": "completed",
        "output": str(output),
        "model": args.model,
        "usage": receipt["usage"],
        "estimate": receipt["estimate"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


def _pricing(path: Path, model_id: str) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    models = payload.get("gpt", {}).get("models", []) if isinstance(payload, dict) else []
    for model in models if isinstance(models, list) else []:
        if not isinstance(model, dict) or model.get("id") != model_id:
            continue
        cost = model.get("cost")
        if not isinstance(cost, dict):
            break
        return {
            "provider": str(model.get("provider") or "openai"),
            "rates": {
                "uncachedInputUsd": _decimal(cost.get("input")),
                "cachedInputUsd": _decimal(cost.get("cacheRead")),
                "outputUsd": _decimal(cost.get("output")),
            },
        }
    raise SystemExit(f"pricing config has no complete model: {model_id}")


def _decimal(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SystemExit("pricing rate is missing")
    return str(value)


def _runtime_usage(path: Path) -> dict[str, int]:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    totals = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
    with sqlite3.connect(uri, uri=True) as conn:
        for (raw,) in conn.execute(
            "SELECT metrics_json FROM agent_runtime_events WHERE event_type = 'provider_request_completed'"
        ):
            try:
                payload = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            usage = payload.get("usage") if isinstance(payload, dict) else None
            if not isinstance(usage, dict):
                continue
            aliases = {
                "input": ("input", "inputTokens"),
                "output": ("output", "outputTokens"),
                "cacheRead": ("cacheRead", "cacheReadTokens"),
                "cacheWrite": ("cacheWrite", "cacheWriteTokens"),
            }
            for key, names in aliases.items():
                value = next((usage.get(name) for name in names if usage.get(name) is not None), None)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    totals[key] += value
    return totals


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
