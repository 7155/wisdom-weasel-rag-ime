#!/usr/bin/env python3
"""Build an Agent Lab cost receipt from retained Runtime request receipts.

The Runtime DB is opened immutable. Retained per-request cost receipts are the
cost authority; an optional trial aggregate is preserved as a separate usage
classification. This does not alter the original run or claim a provider bill.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rag_ime.agent_lab_cost import (
    build_agent_lab_cost_receipt,
    content_addressed_pricing_id,
)


_COST_TOLERANCE = Decimal("0.000000000001")
_TOKENS_PER_MILLION = Decimal(1_000_000)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime-db", type=Path, required=True)
    parser.add_argument("--pricing-config", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--published-date", required=True)
    parser.add_argument("--trial-artifact", type=Path)
    parser.add_argument("--source-url", default="https://platform.openai.com/docs/pricing")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)

    runtime_db = args.runtime_db.expanduser().resolve(strict=True)
    pricing_config = args.pricing_config.expanduser().resolve(strict=True)
    pricing = _pricing(pricing_config, str(args.model))
    runtime = _runtime_cost_receipt(runtime_db, pricing=pricing)
    if runtime["model"] != str(args.model):
        raise SystemExit(
            f"runtime model {runtime['model']} does not match requested model {args.model}"
        )
    if runtime["provider"] != pricing["provider"]:
        raise SystemExit(
            "runtime provider "
            f"{runtime['provider']} does not match pricing source provider "
            f"{pricing['provider']}"
        )
    if args.trial_artifact is not None:
        trial_artifact = args.trial_artifact.expanduser().resolve(strict=True)
        runtime_cost_receipt = dict(runtime["runtimeCostReceipt"])
        runtime_cost_receipt["trialAggregate"] = _trial_aggregate(
            trial_artifact,
            run_id=str(args.run_id),
        )
        runtime["runtimeCostReceipt"] = _seal_runtime_cost_receipt(
            runtime_cost_receipt
        )
    usage = runtime["usage"]
    if not any(usage.values()):
        raise SystemExit("runtime DB has no provider usage events")
    source_sha256 = _sha256_file(pricing_config)
    pricing_identity: dict[str, object] = {
        "provider": pricing["provider"],
        "model": args.model,
        "currency": "USD",
        "unit": "per_million_tokens",
        "rates": runtime["rates"],
        "publishedDate": str(args.published_date),
        "sourceUrl": str(args.source_url),
        "sourceSha256": source_sha256,
    }
    pricing_identity["pricingId"] = content_addressed_pricing_id(pricing_identity)
    receipt = build_agent_lab_cost_receipt({
        "schemaVersion": "rag-ime.agent-lab-cost-request.v1",
        "pricingIdentity": pricing_identity,
        "usage": {
            "available": True,
            "uncachedInputTokens": usage["input"],
            "cachedInputTokens": usage["cacheRead"],
            "outputTokens": usage["output"],
            "sourceRef": f"runtime-cost:{args.run_id}",
            "sourceSha256": runtime["runtimeCostReceipt"]["sourceSha256"],
        },
        "runtimeCostReceipt": runtime["runtimeCostReceipt"],
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
    candidates: list[dict[str, object]] = []
    if isinstance(payload, dict):
        configured = payload.get("gpt")
        configured_models = (
            configured.get("models", []) if isinstance(configured, dict) else []
        )
        if isinstance(configured_models, list):
            candidates.extend(
                model for model in configured_models if isinstance(model, dict)
            )
        for api_models in payload.values():
            if not isinstance(api_models, dict):
                continue
            model = api_models.get(model_id)
            if isinstance(model, dict):
                candidates.append(model)
    matches = [model for model in candidates if model.get("id") == model_id]
    if len(matches) != 1:
        raise SystemExit(f"pricing config must contain exactly one model: {model_id}")
    model = matches[0]
    cost = model.get("cost")
    if isinstance(cost, dict):
        tiers: list[dict[str, object]] = []
        raw_tiers = cost.get("tiers", [])
        if not isinstance(raw_tiers, list):
            raise SystemExit("pricing tiers must be an array")
        for raw_tier in raw_tiers:
            if not isinstance(raw_tier, dict):
                raise SystemExit("pricing tier must be an object")
            threshold = raw_tier.get("inputTokensAbove")
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, int)
                or threshold < 0
            ):
                raise SystemExit("pricing tier inputTokensAbove must be non-negative")
            tiers.append({
                "inputTokensAbove": threshold,
                "rates": _rates(raw_tier),
                "cacheWriteUsd": _decimal(raw_tier.get("cacheWrite")),
            })
        return {
            "provider": str(model.get("provider") or "openai"),
            "rates": _rates(cost),
            "cacheWriteUsd": _decimal(cost.get("cacheWrite")),
            "tiers": tiers,
        }
    raise SystemExit(f"pricing config has no complete model: {model_id}")


def _rates(cost: dict[str, object]) -> dict[str, str]:
    return {
        "uncachedInputUsd": _decimal(cost.get("input")),
        "cachedInputUsd": _decimal(cost.get("cacheRead")),
        "outputUsd": _decimal(cost.get("output")),
    }


def _decimal(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise SystemExit("pricing rate is missing")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise SystemExit("pricing rate is not a decimal") from exc
    if not amount.is_finite() or amount < 0:
        raise SystemExit("pricing rate must be finite and non-negative")
    return _decimal_text(amount)


def _runtime_usage(path: Path) -> dict[str, int]:
    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    totals = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
    conn = sqlite3.connect(uri, uri=True)
    try:
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
    finally:
        conn.close()
    return totals


def _runtime_cost_receipt(
    path: Path,
    *,
    pricing: dict[str, object],
) -> dict[str, object]:
    """Validate DB usage against the Runtime's retained per-request cost receipts."""

    uri = f"file:{quote(str(path), safe='/')}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True)
    try:
        session_rows = list(
            conn.execute(
                "SELECT model_profile, session_file FROM agent_sessions "
                "WHERE model_profile != '' AND session_file != ''"
            )
        )
    except sqlite3.Error as exc:
        raise SystemExit("runtime DB has no Session pricing provenance") from exc
    finally:
        conn.close()
    profiles = {str(row[0]) for row in session_rows}
    if len(profiles) != 1:
        raise SystemExit("runtime DB must contain exactly one model profile")
    profile = next(iter(profiles))
    if "/" not in profile:
        raise SystemExit("runtime model profile must include provider/model")
    provider, model = profile.split("/", 1)
    if provider != pricing.get("provider"):
        return {
            "provider": provider,
            "model": model,
            "usage": _runtime_usage(path),
            "rates": pricing["rates"],
        }

    totals = {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}
    cost_totals = {
        "input": Decimal(0),
        "cacheRead": Decimal(0),
        "cacheWrite": Decimal(0),
        "output": Decimal(0),
        "total": Decimal(0),
    }
    used_rates: dict[str, dict[str, str]] = {}
    transcript_sha256s: list[str] = []
    observed = 0
    for raw_path in sorted(set(str(row[1]) for row in session_rows)):
        transcript = Path(raw_path).expanduser().resolve(strict=True)
        transcript_sha256s.append(_sha256_file(transcript))
        try:
            lines = transcript.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise SystemExit(f"Runtime cost receipt is unreadable: {transcript.name}") from exc
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise SystemExit(
                    f"Runtime cost receipt contains invalid JSON: {transcript.name}"
                ) from exc
            message = event.get("message") if isinstance(event, dict) else None
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(message, dict) or message.get("role") != "assistant":
                continue
            if not isinstance(usage, dict):
                continue
            if message.get("provider") != provider or message.get("model") != model:
                raise SystemExit("Runtime cost receipt mixes provider/model identities")
            counts = {
                key: _token_count(usage.get(key), label=f"Runtime usage {key}")
                for key in totals
            }
            rates, cache_write_rate = _rates_for_request(pricing, counts)
            rate_key = json.dumps(
                {**rates, "cacheWriteUsd": cache_write_rate},
                sort_keys=True,
                separators=(",", ":"),
            )
            used_rates[rate_key] = rates
            expected = {
                "input": _cost(counts["input"], rates["uncachedInputUsd"]),
                "cacheRead": _cost(counts["cacheRead"], rates["cachedInputUsd"]),
                "cacheWrite": _cost(counts["cacheWrite"], cache_write_rate),
                "output": _cost(counts["output"], rates["outputUsd"]),
            }
            expected["total"] = sum(expected.values(), Decimal(0))
            reported = usage.get("cost")
            if not isinstance(reported, dict) or any(
                not _cost_matches(reported.get(key), expected[key])
                for key in ("input", "cacheRead", "cacheWrite", "output", "total")
            ):
                raise SystemExit(
                    "Runtime cost receipt does not match the hashed pricing source"
                )
            for key, value in counts.items():
                totals[key] += value
            for key, value in expected.items():
                cost_totals[key] += value
            observed += 1
    if not observed:
        raise SystemExit("runtime Session transcripts contain no cost receipts")
    database_totals = _runtime_usage(path)
    if totals["cacheWrite"]:
        raise SystemExit("v1 Agent Lab cost receipts cannot represent cache-write cost")
    if len(used_rates) != 1:
        raise SystemExit(
            "Runtime cost receipt spans multiple pricing tiers; "
            "v1 Agent Lab cost receipts cannot represent it exactly"
        )
    runtime_cost_receipt: dict[str, object] = {
        "requestCount": observed,
        "runtimeDbSha256": _sha256_file(path),
        "transcriptSha256s": transcript_sha256s,
        "databaseUsage": {
            "uncachedInputTokens": database_totals["input"],
            "cachedInputTokens": database_totals["cacheRead"],
            "outputTokens": database_totals["output"],
        },
        "reportedCostUsd": {
            "input": _decimal_text(cost_totals["input"]),
            "cacheRead": _decimal_text(cost_totals["cacheRead"]),
            "output": _decimal_text(cost_totals["output"]),
            "total": _decimal_text(cost_totals["total"]),
        },
    }
    runtime_cost_receipt = _seal_runtime_cost_receipt(runtime_cost_receipt)
    return {
        "provider": provider,
        "model": model,
        "usage": totals,
        "rates": next(iter(used_rates.values())),
        "runtimeCostReceipt": runtime_cost_receipt,
    }


def _trial_aggregate(path: Path, *, run_id: str) -> dict[str, object]:
    matches: list[dict[str, object]] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise SystemExit(f"trial aggregate is unreadable: {path.name}") from exc
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise SystemExit(f"trial aggregate contains invalid JSON: {path.name}") from exc
        if not isinstance(event, dict) or event.get("eventType") != "trial_completed":
            continue
        payload = event.get("payload")
        if not isinstance(payload, dict) or payload.get("trialId") != run_id:
            continue
        usage = payload.get("usage")
        if not isinstance(usage, dict) or usage.get("available") is not True:
            raise SystemExit("trial_completed has no available aggregate usage")
        counts = {
            "uncachedInputTokens": _token_count(
                usage.get("input"), label="trial aggregate input"
            ),
            "cachedInputTokens": _token_count(
                usage.get("cacheRead"), label="trial aggregate cacheRead"
            ),
            "outputTokens": _token_count(
                usage.get("output"), label="trial aggregate output"
            ),
        }
        cache_write = _token_count(
            usage.get("cacheWrite"), label="trial aggregate cacheWrite"
        )
        if cache_write:
            raise SystemExit(
                "v1 Agent Lab cost receipts cannot represent trial cache-write usage"
            )
        total_tokens = usage.get("totalTokens")
        if total_tokens is not None and _token_count(
            total_tokens, label="trial aggregate totalTokens"
        ) != sum(counts.values()):
            raise SystemExit("trial_completed aggregate token total is inconsistent")
        matches.append(counts)
    if len(matches) != 1:
        raise SystemExit(
            "trial artifact must contain exactly one matching trial_completed record"
        )
    return {
        "sourceRef": f"agent-artifact:{run_id}:trial_completed",
        "sourceSha256": _sha256_file(path),
        **matches[0],
    }


def _seal_runtime_cost_receipt(
    runtime_cost_receipt: dict[str, object],
) -> dict[str, object]:
    sealed = dict(runtime_cost_receipt)
    sealed.pop("sourceSha256", None)
    sealed["sourceSha256"] = hashlib.sha256(
        json.dumps(
            sealed,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    return sealed


def _rates_for_request(
    pricing: dict[str, object],
    usage: dict[str, int],
) -> tuple[dict[str, str], str]:
    rates = dict(pricing["rates"])
    cache_write_rate = str(pricing["cacheWriteUsd"])
    input_tokens = usage["input"] + usage["cacheRead"] + usage["cacheWrite"]
    matched_threshold = -1
    for raw_tier in pricing["tiers"]:
        tier = dict(raw_tier)
        threshold = int(tier["inputTokensAbove"])
        if input_tokens > threshold and threshold > matched_threshold:
            rates = dict(tier["rates"])
            cache_write_rate = str(tier["cacheWriteUsd"])
            matched_threshold = threshold
    return rates, cache_write_rate


def _token_count(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SystemExit(f"{label} must be a non-negative integer")
    return value


def _cost(tokens: int, rate: str) -> Decimal:
    return Decimal(tokens) * Decimal(rate) / _TOKENS_PER_MILLION


def _cost_matches(reported: object, expected: Decimal) -> bool:
    if isinstance(reported, bool) or not isinstance(reported, (int, float, str)):
        return False
    try:
        value = Decimal(str(reported))
    except InvalidOperation:
        return False
    return value.is_finite() and abs(value - expected) <= _COST_TOLERANCE


def _decimal_text(value: Decimal) -> str:
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(4 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
