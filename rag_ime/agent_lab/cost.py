"""Deterministic, evidence-bound API cost receipts for Agent Lab.

Pricing is caller data, not a model catalog.  The helper performs no Provider
call, persistence, comparison, or savings calculation.  A retained Runtime
cost receipt may be reconciled to the pricing inputs, while a provider bill,
when available, remains a separate receipt from the computed estimate.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import date
from decimal import Decimal, InvalidOperation, localcontext
from urllib.parse import urlsplit

from ..contracts.json_schema import ContractValidationError, validate_contract


_REQUEST_CONTRACT = "agent-lab-cost-request.v1.json"
_RECEIPT_CONTRACT = "agent-lab-cost-receipt.v1.json"
_TOKENS_PER_MILLION = Decimal(1_000_000)


class AgentLabCostError(ValueError):
    """The caller did not provide a complete, valid cost evidence request."""


def content_addressed_pricing_id(pricing: Mapping[str, object]) -> str:
    """Bind one pricing id to the exact provider, rates, date, and source hash."""

    value = _mapping(pricing, label="pricingIdentity")
    rates = _mapping(value.get("rates"), label="pricingIdentity.rates")
    published_date = str(value.get("publishedDate") or "")
    source_url = str(value.get("sourceUrl") or "")
    source_sha256 = str(value.get("sourceSha256") or "")
    _validate_published_date(published_date)
    _validate_source_url(source_url)
    if len(source_sha256) != 64 or any(
        character not in "0123456789abcdef" for character in source_sha256
    ):
        raise AgentLabCostError("pricing sourceSha256 must be a lowercase SHA-256")
    provider = str(value.get("provider") or "")
    model = str(value.get("model") or "")
    if not provider or not model:
        raise AgentLabCostError("pricing provider and model are required")
    if value.get("currency") != "USD" or value.get("unit") != "per_million_tokens":
        raise AgentLabCostError(
            "pricing currency/unit must be USD per_million_tokens"
        )
    identity = {
        "provider": provider,
        "model": model,
        "currency": "USD",
        "unit": "per_million_tokens",
        "rates": {
            "uncachedInputUsd": _decimal_text(
                _decimal(rates.get("uncachedInputUsd"), label="uncached input rate")
            ),
            "cachedInputUsd": _decimal_text(
                _decimal(rates.get("cachedInputUsd"), label="cached input rate")
            ),
            "outputUsd": _decimal_text(
                _decimal(rates.get("outputUsd"), label="output rate")
            ),
        },
        "publishedDate": published_date,
        "sourceUrl": source_url,
        "sourceSha256": source_sha256,
    }
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()
    return f"pricing:sha256:{digest}"


def build_agent_lab_cost_receipt(request: Mapping[str, object]) -> dict[str, object]:
    """Return a deterministic USD cost receipt without treating it as a bill."""

    payload = dict(request)
    try:
        validate_contract(payload, _REQUEST_CONTRACT)
    except (ContractValidationError, ValueError) as exc:
        raise AgentLabCostError(f"invalid Agent Lab cost request: {exc}") from exc

    pricing = _mapping(payload["pricingIdentity"], label="pricingIdentity")
    usage = _mapping(payload["usage"], label="usage")
    rates = _mapping(pricing["rates"], label="pricingIdentity.rates")
    _validate_published_date(str(pricing["publishedDate"]))
    _validate_source_url(str(pricing["sourceUrl"]))

    counts = {
        "uncachedInput": _token_count(
            usage["uncachedInputTokens"], label="usage.uncachedInputTokens"
        ),
        "cachedInput": _token_count(
            usage["cachedInputTokens"], label="usage.cachedInputTokens"
        ),
        "output": _token_count(usage["outputTokens"], label="usage.outputTokens"),
    }
    if not sum(counts.values()):
        raise AgentLabCostError("usage must contain at least one reported token")

    with localcontext() as context:
        context.prec = 96
        uncached_cost = _cost(
            counts["uncachedInput"],
            _decimal(rates["uncachedInputUsd"], label="uncached input rate"),
        )
        cached_cost = _cost(
            counts["cachedInput"],
            _decimal(rates["cachedInputUsd"], label="cached input rate"),
        )
        output_cost = _cost(
            counts["output"],
            _decimal(rates["outputUsd"], label="output rate"),
        )
        total_cost = uncached_cost + cached_cost + output_cost

    billed = payload.get("billedReceipt")
    if billed is None:
        billing: dict[str, object] = {"status": "not_provided"}
        billing_boundary = (
            "No billed receipt was supplied; billing status remains not_provided."
        )
    else:
        billed_receipt = _mapping(billed, label="billedReceipt")
        billing = {
            "status": "provided",
            "currency": "USD",
            "totalUsd": _decimal_text(
                _decimal(billed_receipt["totalUsd"], label="billed total")
            ),
            "receiptRef": str(billed_receipt["receiptRef"]),
            "receiptSha256": str(billed_receipt["receiptSha256"]),
        }
        billing_boundary = (
            "The billed receipt is preserved separately and is not reconciled or "
            "replaced by the estimate."
        )

    runtime_cost = payload.get("runtimeCostReceipt")
    pricing_lower_bound = payload.get("pricingLowerBound")
    if runtime_cost is not None and pricing_lower_bound is not None:
        raise AgentLabCostError(
            "runtimeCostReceipt and pricingLowerBound are mutually exclusive"
        )
    runtime_cost_receipt: dict[str, object] | None = None
    pricing_lower_bound_receipt: dict[str, object] | None = None
    authority = "pricing_estimate"
    cost_boundary = (
        "This is a deterministic estimate from caller-supplied pricing and "
        "reported usage, not a provider bill."
    )
    if pricing_lower_bound is not None:
        pricing_lower_bound_receipt = _mapping(
            pricing_lower_bound,
            label="pricingLowerBound",
        )
        if str(pricing["pricingId"]) != content_addressed_pricing_id(pricing):
            raise AgentLabCostError(
                "lower-bound pricingId must be content-addressed"
            )
        if pricing_lower_bound_receipt["sourceSha256"] != pricing["sourceSha256"]:
            raise AgentLabCostError(
                "pricing lower-bound proof must bind the pricing source hash"
            )
        tiers = pricing_lower_bound_receipt.get("tiers")
        if not isinstance(tiers, list) or not tiers:
            raise AgentLabCostError("pricing lower-bound proof requires tiers")
        previous_threshold = -1
        previous_rates = {
            key: _decimal(rates[key], label=f"base {key}")
            for key in ("uncachedInputUsd", "cachedInputUsd", "outputUsd")
        }
        for index, raw_tier in enumerate(tiers):
            tier = _mapping(raw_tier, label=f"pricingLowerBound.tiers[{index}]")
            threshold = tier["inputTokensAbove"]
            if (
                isinstance(threshold, bool)
                or not isinstance(threshold, int)
                or threshold <= previous_threshold
            ):
                raise AgentLabCostError(
                    "pricing lower-bound tier thresholds must strictly increase"
                )
            tier_rates = _mapping(
                tier["rates"],
                label=f"pricingLowerBound.tiers[{index}].rates",
            )
            current_rates = {
                key: _decimal(tier_rates[key], label=f"tier {index} {key}")
                for key in previous_rates
            }
            if any(
                current_rates[key] < previous_rates[key]
                for key in previous_rates
            ):
                raise AgentLabCostError(
                    "pricing lower-bound tier rates must not decrease"
                )
            previous_threshold = threshold
            previous_rates = current_rates
        authority = "pricing_lower_bound"
        cost_boundary = (
            "This is a conservative lower bound from aggregate usage and the "
            "hashed pricing schedule; every retained tier rate is non-decreasing. "
            "It is not an exact Runtime cost or a provider bill."
        )
    if runtime_cost is not None:
        runtime_cost_receipt = _mapping(runtime_cost, label="runtimeCostReceipt")
        if str(pricing["pricingId"]) != content_addressed_pricing_id(pricing):
            raise AgentLabCostError(
                "runtime-reconciled pricingId must be content-addressed"
            )
        reported = _mapping(
            runtime_cost_receipt["reportedCostUsd"],
            label="runtimeCostReceipt.reportedCostUsd",
        )
        expected_reported = {
            "input": uncached_cost,
            "cacheRead": cached_cost,
            "output": output_cost,
            "total": total_cost,
        }
        if any(
            _decimal(reported[key], label=f"runtime reported {key}") != value
            for key, value in expected_reported.items()
        ):
            raise AgentLabCostError(
                "runtime reported cost must exactly match the pricing recomputation"
            )
        runtime_body = dict(runtime_cost_receipt)
        runtime_sha256 = str(runtime_body.pop("sourceSha256"))
        transcript_sha256s = runtime_body.get("transcriptSha256s")
        if (
            not isinstance(transcript_sha256s, list)
            or len(transcript_sha256s) != len(set(transcript_sha256s))
        ):
            raise AgentLabCostError(
                "runtime cost receipt transcript hashes must be unique"
            )
        if runtime_sha256 != hashlib.sha256(
            _canonical_json(runtime_body).encode("utf-8")
        ).hexdigest():
            raise AgentLabCostError("runtime cost receipt sourceSha256 is invalid")
        if (
            not str(usage["sourceRef"]).startswith("runtime-cost:")
            or str(usage["sourceSha256"]) != runtime_sha256
        ):
            raise AgentLabCostError(
                "usage must bind the exact runtime cost receipt"
            )
        authority = "runtime_cost_reconciled"
        cost_boundary = (
            "The estimate was recomputed from the hashed pricing source and "
            "reconciled to retained per-request Runtime cost receipts; it is "
            "not a provider bill."
        )

    receipt: dict[str, object] = {
        "schemaVersion": "rag-ime.agent-lab-cost-receipt.v1",
        "authority": authority,
        "pricingIdentity": {
            "pricingId": str(pricing["pricingId"]),
            "provider": str(pricing["provider"]),
            "model": str(pricing["model"]),
            "currency": "USD",
            "unit": "per_million_tokens",
            "rates": {
                "uncachedInputUsd": str(rates["uncachedInputUsd"]),
                "cachedInputUsd": str(rates["cachedInputUsd"]),
                "outputUsd": str(rates["outputUsd"]),
            },
            "publishedDate": str(pricing["publishedDate"]),
            "sourceUrl": str(pricing["sourceUrl"]),
            "sourceSha256": str(pricing["sourceSha256"]),
        },
        "usage": {
            "available": True,
            "uncachedInputTokens": counts["uncachedInput"],
            "cachedInputTokens": counts["cachedInput"],
            "outputTokens": counts["output"],
            "sourceRef": str(usage["sourceRef"]),
            "sourceSha256": str(usage["sourceSha256"]),
        },
        "estimate": {
            "uncachedInputCostUsd": _decimal_text(uncached_cost),
            "cachedInputCostUsd": _decimal_text(cached_cost),
            "outputCostUsd": _decimal_text(output_cost),
            "totalCostUsd": _decimal_text(total_cost),
        },
        "billing": billing,
        "boundaries": [
            cost_boundary,
            billing_boundary,
            "No savings amount is inferred by this receipt.",
        ],
    }
    if runtime_cost_receipt is not None:
        receipt["runtimeCostReceipt"] = runtime_cost_receipt
    if pricing_lower_bound_receipt is not None:
        receipt["pricingLowerBound"] = pricing_lower_bound_receipt
    receipt["receiptSha256"] = hashlib.sha256(
        _canonical_json(receipt).encode("utf-8")
    ).hexdigest()
    try:
        validate_contract(receipt, _RECEIPT_CONTRACT)
    except ContractValidationError as exc:  # pragma: no cover - internal invariant
        raise RuntimeError(f"Agent Lab cost receipt violated its contract: {exc}") from exc
    return receipt


def _mapping(value: object, *, label: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise AgentLabCostError(f"{label} must be an object")
    return dict(value)


def _token_count(value: object, *, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise AgentLabCostError(f"{label} must be a non-negative integer")
    return value


def _decimal(value: object, *, label: str) -> Decimal:
    if not isinstance(value, str):
        raise AgentLabCostError(f"{label} must be an exact decimal string")
    try:
        amount = Decimal(value)
    except InvalidOperation as exc:
        raise AgentLabCostError(f"{label} is not a decimal amount") from exc
    if not amount.is_finite() or amount < 0:
        raise AgentLabCostError(f"{label} must be finite and non-negative")
    return amount


def _cost(tokens: int, rate_per_million: Decimal) -> Decimal:
    return Decimal(tokens) * rate_per_million / _TOKENS_PER_MILLION


def _decimal_text(value: Decimal) -> str:
    if value == 0:
        return "0"
    # ``Decimal.normalize()`` uses the ambient context and can silently round a
    # value computed under the wider calculation context.  Fixed-point
    # formatting preserves every coefficient digit; trimming only removes
    # insignificant trailing zeroes.
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


def _validate_published_date(value: str) -> None:
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise AgentLabCostError("pricing publishedDate is not a real ISO date") from exc
    if parsed.isoformat() != value:
        raise AgentLabCostError("pricing publishedDate must be canonical YYYY-MM-DD")


def _validate_source_url(value: str) -> None:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.netloc
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise AgentLabCostError("pricing sourceUrl must be a credential-free HTTPS URL")


def _canonical_json(payload: Mapping[str, object]) -> str:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )
