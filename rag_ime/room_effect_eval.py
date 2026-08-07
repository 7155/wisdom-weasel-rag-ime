from __future__ import annotations

import argparse
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

from .agent_room_capabilities import _tool_routing_score, room_runtime_registry
from .agent_room_skills import RoomSkillPolicy
from .agent_prompt_plans import PROMPT_LAYER_SPECS, _model_visible_projection_content
from .agent_roles import agent_role, agent_role_catalog
from .agent_templates import agent_template, agent_template_catalog


_REQUIRED_SKILL_HEADINGS = (
    "## Workflow",
    "## Output Contract",
    "## Boundaries",
)
_PLACEHOLDER_TERMS = ("tbd", "待补充", "placeholder")
_PLACEHOLDER_LINES = ("todo", "todo:", "todo：")


def evaluate_room_task_effects(
    fixture_path: str | Path,
    *,
    policy_path: str | Path,
    skills_root: str | Path,
) -> dict[str, object]:
    fixture = json.loads(Path(fixture_path).read_text(encoding="utf-8"))
    if fixture.get("schemaVersion") != "wisdom-weasel.room-task-effect-fixtures.v1":
        raise ValueError("unsupported Room task effect fixture schema")
    cases = fixture.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("Room task effect fixtures require cases")
    policy = RoomSkillPolicy(policy_path, skills_root)
    catalog = policy.catalog()
    catalog_bytes = len(json.dumps(catalog, ensure_ascii=False, separators=(",", ":")).encode())
    body_bytes = sum(len(policy.skill_body(skill_id).encode()) for skill_id in policy.skill_ids)
    registry = room_runtime_registry()
    tool_catalog_bytes = len(
        json.dumps(
            [
                {"name": name, "description": value["description"], "risk": value["risk"]}
                for name, value in registry.items()
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    )
    tool_schema_bytes = len(
        json.dumps(registry, ensure_ascii=False, separators=(",", ":")).encode()
    )

    results: list[dict[str, object]] = []
    skill_true_positive = skill_false_positive = skill_false_negative = 0
    tool_true_positive = tool_false_positive = tool_false_negative = 0
    chain_breaks = prompt_errors = 0
    for value in cases:
        if not isinstance(value, Mapping):
            raise ValueError("Room task effect case must be an object")
        stage = str(value.get("stage") or "")
        selection = policy.select_stage(stage)
        actual_skills = (
            [str(selection["skillId"])]
            if selection["selection"] == "required"
            else [str(item) for item in selection["candidateSkillIds"]]
        )
        expected_skills = _strings(value.get("expectedSkills"))
        forbidden_skills = _strings(value.get("forbiddenSkills"))
        skill_true_positive += len(set(actual_skills) & set(expected_skills))
        skill_false_positive += len(set(actual_skills) - set(expected_skills))
        skill_false_negative += len(set(expected_skills) - set(actual_skills))

        query = str(value.get("toolQuery") or "").casefold()
        ranked_tools = sorted(
            (
                (
                    _tool_routing_score(query, {"name": name, **spec}),
                    name,
                )
                for name, spec in registry.items()
            ),
            key=lambda item: (-item[0], item[1]),
        )
        best_score = ranked_tools[0][0] if query and ranked_tools else 0
        actual_tools = [
            name
            for score, name in ranked_tools
            if best_score > 0 and score == best_score
        ]
        expected_tools = _strings(value.get("expectedTools"))
        tool_true_positive += len(set(actual_tools) & set(expected_tools))
        tool_false_positive += len(set(actual_tools) - set(expected_tools))
        tool_false_negative += len(set(expected_tools) - set(actual_tools))

        expected_prompt_terms = _strings(value.get("expectedPromptTerms"))
        loaded_text = " ".join(
            " ".join(policy.skill_body(item).split()) for item in actual_skills
        )
        missing_prompt_terms = [
            term for term in expected_prompt_terms if term.casefold() not in loaded_text.casefold()
        ]
        prompt_errors += len(missing_prompt_terms)
        broken = []
        for skill_id in actual_skills:
            broken.extend(
                candidate
                for candidate in policy.next_candidates(skill_id)
                if candidate not in policy.skill_ids
            )
        chain_breaks += len(broken)
        results.append(
            {
                "id": str(value.get("id") or ""),
                "stage": stage,
                "actualSkills": actual_skills,
                "expectedSkills": expected_skills,
                "forbiddenSkillHits": sorted(set(actual_skills) & set(forbidden_skills)),
                "actualTools": actual_tools,
                "expectedTools": expected_tools,
                "missingPromptTerms": missing_prompt_terms,
                "chainBreaks": broken,
                "passed": (
                    set(actual_skills) == set(expected_skills)
                    and not set(actual_skills) & set(forbidden_skills)
                    and set(actual_tools) == set(expected_tools)
                    and not missing_prompt_terms
                    and not broken
                ),
            }
        )

    skill_errors = _skill_contract_errors(policy)
    prompt_contract_errors = _prompt_contract_errors()
    prompt_errors += len(skill_errors) + len(prompt_contract_errors)
    context_results, context_noise_count = _evaluate_context_cases(fixture.get("contextCases"))
    passed = (
        all(bool(item["passed"]) for item in results)
        and not skill_errors
        and not prompt_contract_errors
        and context_noise_count == 0
    )
    return {
        "schemaVersion": "wisdom-weasel.room-task-effect-eval.v1",
        "passed": passed,
        "caseCount": len(results),
        "metrics": {
            "skillPrecision": _ratio(skill_true_positive, skill_true_positive + skill_false_positive),
            "skillRecall": _ratio(skill_true_positive, skill_true_positive + skill_false_negative),
            "toolPrecision": _ratio(tool_true_positive, tool_true_positive + tool_false_positive),
            "toolRecall": _ratio(tool_true_positive, tool_true_positive + tool_false_negative),
            "catalogBytes": catalog_bytes,
            "loadBodyBytes": body_bytes,
            "skillCatalogBytes": catalog_bytes,
            "skillBodyBytes": body_bytes,
            "progressiveDisclosureRatio": round(catalog_bytes / max(1, body_bytes), 4),
            "toolCatalogBytes": tool_catalog_bytes,
            "toolSchemaBytes": tool_schema_bytes,
            "toolProgressiveDisclosureRatio": round(
                tool_catalog_bytes / max(1, tool_schema_bytes), 4
            ),
            "promptErrorCount": prompt_errors,
            "chainBreakCount": chain_breaks,
            "contextNoiseCount": context_noise_count,
        },
        "skillContractErrors": skill_errors,
        "promptContractErrors": prompt_contract_errors,
        "cases": results,
        "contextCases": context_results,
        "limitations": [
            "Deterministic contract evaluation does not claim semantic selection quality from a live LLM.",
            "Provider-side tokenization and cache-hit billing require a real configured Provider canary.",
        ],
    }


def render_room_task_effect_report(result: Mapping[str, object]) -> str:
    metrics = result["metrics"]
    assert isinstance(metrics, Mapping)
    lines = [
        "# Room V2 Task Effect Evaluation",
        "",
        f"- Result: {'PASS' if result.get('passed') else 'FAIL'}",
        f"- Cases: {result.get('caseCount')}",
        f"- Skill precision / recall: {metrics['skillPrecision']} / {metrics['skillRecall']}",
        f"- Tool precision / recall: {metrics['toolPrecision']} / {metrics['toolRecall']}",
        f"- Catalog / full Skill bytes: {metrics['catalogBytes']} / {metrics['loadBodyBytes']}",
        f"- Progressive disclosure ratio: {metrics['progressiveDisclosureRatio']}",
        f"- Tool catalog / schema bytes: {metrics['toolCatalogBytes']} / {metrics['toolSchemaBytes']}",
        f"- Tool disclosure ratio: {metrics['toolProgressiveDisclosureRatio']}",
        f"- Prompt errors: {metrics['promptErrorCount']}",
        f"- Chain breaks: {metrics['chainBreakCount']}",
        f"- Context noise: {metrics['contextNoiseCount']}",
        "",
        "## Cases",
        "",
        "| Case | Skills | Tools | Result |",
        "|---|---|---|---|",
    ]
    for case in result["cases"]:  # type: ignore[index]
        assert isinstance(case, Mapping)
        lines.append(
            f"| {case['id']} | {', '.join(_strings(case['actualSkills'])) or '-'} | "
            f"{', '.join(_strings(case['actualTools'])) or '-'} | "
            f"{'PASS' if case['passed'] else 'FAIL'} |"
        )
    lines.extend(("", "## Boundaries", ""))
    lines.extend(f"- {item}" for item in _strings(result.get("limitations")))
    return "\n".join(lines) + "\n"


def _skill_contract_errors(policy: RoomSkillPolicy) -> list[str]:
    errors: list[str] = []
    for entry in policy.catalog():
        skill_id = str(entry["name"])
        body = policy.skill_body(skill_id)
        text = json.dumps(entry, ensure_ascii=False) + "\n" + body
        for heading in _REQUIRED_SKILL_HEADINGS:
            if heading not in body:
                errors.append(f"{skill_id}:missing:{heading}")
        for placeholder in _PLACEHOLDER_TERMS:
            if placeholder in text.casefold():
                errors.append(f"{skill_id}:placeholder:{placeholder}")
        if any(line.strip().casefold() in _PLACEHOLDER_LINES for line in text.splitlines()):
            errors.append(f"{skill_id}:placeholder:todo")
        if any(line.strip() in {"未定", "未定。"} for line in text.splitlines()):
            errors.append(f"{skill_id}:placeholder:未定")
    return errors


def _prompt_contract_errors() -> list[str]:
    errors: list[str] = []
    layers = [name for _order, name, _producer, _optional in PROMPT_LAYER_SPECS]
    producers = [producer for _order, _name, producer, _optional in PROMPT_LAYER_SPECS]
    if len(layers) != 6 or len(layers) != len(set(layers)):
        errors.append("prompt-plan:fixed-layer-set")
    if len(producers) != len(set(producers)):
        errors.append("prompt-plan:duplicate-producer")
    prompt_sources: list[tuple[str, str]] = []
    for item in agent_role_catalog():
        role = agent_role(item["roleId"], item["version"])
        prompt_sources.append((f"persona:{role.role_id}", role.system_prompt))
    for item in agent_template_catalog():
        template = agent_template(item["templateId"], item["version"])
        prompt_sources.append((f"template:{template.template_id}", template.prompt))
    for name, prompt in prompt_sources:
        normalized = " ".join(prompt.split()).casefold()
        if not normalized:
            errors.append(f"{name}:empty")
        for placeholder in _PLACEHOLDER_TERMS:
            if placeholder in normalized:
                errors.append(f"{name}:placeholder:{placeholder}")
    return errors


def _evaluate_context_cases(value: object) -> tuple[list[dict[str, object]], int]:
    if value is None:
        return [], 0
    if not isinstance(value, list):
        raise ValueError("contextCases must be an array")
    results: list[dict[str, object]] = []
    noise_count = 0
    for case in value:
        if not isinstance(case, Mapping) or not isinstance(case.get("content"), Mapping):
            raise ValueError("context case requires object content")
        visible = _model_visible_projection_content(
            {
                "entryKind": str(case.get("entryKind") or "room_fact"),
                "content": json.dumps(case["content"], ensure_ascii=False),
            }
        )
        missing = [term for term in _strings(case.get("expectedIncludes")) if term not in visible]
        leaked = [
            term
            for term in _strings(case.get("forbiddenTerms"))
            if term.casefold() in visible.casefold()
        ]
        noise_count += len(missing) + len(leaked)
        results.append(
            {
                "id": str(case.get("id") or ""),
                "visibleBytes": len(visible.encode()),
                "auditBytes": len(json.dumps(case["content"], ensure_ascii=False).encode()),
                "missingExpected": missing,
                "leakedInternals": leaked,
                "passed": not missing and not leaked,
            }
        )
    return results, noise_count


def _strings(value: object) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(item) for item in value]


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def main() -> int:
    parser = argparse.ArgumentParser(description="Run deterministic Room task-effect evaluation")
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--policy", required=True)
    parser.add_argument("--skills-root", required=True)
    parser.add_argument("--json-output", required=True)
    parser.add_argument("--report-output", required=True)
    args = parser.parse_args()
    result = evaluate_room_task_effects(
        args.fixtures, policy_path=args.policy, skills_root=args.skills_root
    )
    Path(args.json_output).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    Path(args.report_output).write_text(
        render_room_task_effect_report(result), encoding="utf-8"
    )
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
