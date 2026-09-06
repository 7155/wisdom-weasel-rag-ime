#!/usr/bin/env python3
"""Project retained private measurements into a public-safe, importable Lab ledger.

No model calls and no production writes. Metrics come from retained receipts;
missing observations stay absent. Receipt hashes identify the observations, not
a retrospectively invented pre-run dataset freeze.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def build_ledger(root: Path) -> dict:
    receipts: dict[str, str] = {}

    def read(name: str) -> dict:
        raw = (root / name).read_bytes()
        receipts[name] = hashlib.sha256(raw).hexdigest()
        return json.loads(raw)

    def refs(*names: str) -> list[str]:
        return [f"retained-receipt:{name}#sha256={receipts[name]}" for name in names]

    def record(key, title, names, before, after, *, count, unit, result,
               action, boundary, effect="unverified", status="diagnostic",
               factor_before="无配对基线；单轮验证", factor_after="按原回执观察",
               kind="workflow", comparison=True, observation=False, outputs=()):
        evidence = refs(*names)
        receipt_digest = hashlib.sha256("\n".join(evidence).encode()).hexdigest()
        partial_cost = any("knownEstimatedApiCostUsd" in metrics for metrics in (before, after))
        return {
            "id": f"paw-selfboot.{key}.20260906.v1", "title": f"PAW 自举 · {title}",
            "vertical": "paw-selfboot", "evaluationKind": kind,
            "status": status, "claimStatus": "supporting" if status == "kept" or observation else "diagnostic",
            "projectionState": "current", "effectStatus": effect,
            "businessProblem": title, "whyAgent": "复用 PAW 的 Pi Session、Room 与 Lab owner，核验真实产物和接续结果。",
            "dataset": {"id": key, "split": "retained_observations", "caseCount": count,
                        "unit": unit + "；此 manifest 绑定保留回执，不冒充运行前的数据冻结。",
                        "manifestSha256": receipt_digest, "heldOutConsumed": False},
            "scoringContract": {"primaryMetric": "先验收完整任务与接续结果，再报告代价",
                "evaluatorAuthority": "原运行 Host 验收与父 Session 回执复核",
                "goldHiddenFromAgent": True,
                "hardGates": ["保留失败与未知项", "检查数不冒充独立任务数", "估算费用不冒充 Provider 账单"]},
            "factors": [{"name": "workflow", "before": factor_before, "after": factor_after, "reason": action}],
            "frozenControls": [
                {"name": "comparison_scope", "value": "paired" if comparison and before else "observation_only", "reason": "不将单轮或受阻观察解释成优化收益。"},
                {"name": "observation_scope", "value": unit, "reason": boundary},
                {"name": "cost_authority", "value": "Pi transcript catalog estimate；非 Provider 账单", "reason": "只汇总已记录的部分，未记录的在途用量未知。" if partial_cost else "完整 turn 汇总，不把最后一条消息当作总用量。"},
                *([{"name": "cost_completeness", "value": "partial_after_budget_stop", "reason": "预算中断；未记录的在途成本未知，已知估算不能作为总额或节省。"}] if partial_cost else []),
                *([{"name": "cost_scope", "value": "每臂完整任务执行；优化诊断投入另列", "reason": "仅在同口径已知费用间比较。"}] if comparison and before else []),
            ],
            "baseline": {"runId": key + (":baseline" if before else ":no-baseline"), "metrics": before, "evidenceRefs": evidence if before else []},
            "candidate": {"runId": key + ":observed", "metrics": after, "evidenceRefs": evidence},
            "comparison": {"decision": "observation" if observation else "keep" if status == "kept" else "diagnostic", "decisionReason": result,
                "metricDeltas": [{"metric": k, "before": before[k], "after": after[k], "delta": after[k] - before[k]}
                                 for k in sorted(before.keys() & after.keys())] if comparison else [],
                "outputComparisons": list(outputs)},
            "star": {"situation": title, "task": unit, "action": action, "result": result},
            "claim": {"resumeBullet": result, "allowed": result, "forbidden": boundary},
            "openGaps": [boundary],
        }

    def arm_metrics(arm):
        return {"taskCount": 1, "taskSuccessCount": int(arm["score"]["allPassed"]),
                "verifierPassCount": arm["score"]["passed"], "verifierCount": arm["score"]["total"],
                "providerCalls": arm["providerCalls"], "totalTokens": arm["tokens"],
                "estimatedApiCostUsd": arm.get("costUsd", arm.get("cost")),
                **({"latencyMs": arm["wallMs"]} if "wallMs" in arm else {})}

    rows = []
    name = "room-comparison-20260905/room-comparison-job.json"
    pair = read(name)["result"]["arms"]
    solo, room = arm_metrics(pair["solo"]), arm_metrics(pair["room"])
    room.update({k: pair["room"][k] for k in ("assignedCaseOverlap", "correctHandoffFacts", "omittedCorrectHandoffFacts", "duplicateFindingRows")})
    rows.append(record("room-small-pair", "小任务协作对照：未测出收益", [name], solo, room,
        count=1, unit="1 个合成任务，每臂 3 条契约检查，1 组配对",
        result="单 Session 与 Room 均为 2/3 检查通过、完整任务 0/1；Room 交接遗漏 0/2，但成本更高，未测出协作收益。",
        action="相同题目、模型与预算上限；比较单 Session 和串行 Room 分工交接。",
        factor_before="单 Session", factor_after="两个伙伴与一个模型整合者", effect="regressed",
        boundary="题目字段类型存在歧义；不得将此小样本推断为中等或复杂任务的协作成败率。"))

    name = "room-merge-confirm-20260905/verified-gain.json"
    gain = read(name)
    for path, expected in gain["receiptHashes"].items():
        if hashlib.sha256(Path(path).read_bytes()).hexdigest() != expected:
            raise ValueError("Room gain receipt changed")
    before, after = arm_metrics(gain["baseline"]), arm_metrics(gain["confirmation"])
    after.update({"optimizationProviderCalls": gain["experimentInvestment"]["providerCalls"],
                  "optimizationTokens": gain["experimentInvestment"]["tokens"],
                  "optimizationEstimatedCostUsd": gain["experimentInvestment"]["estimatedCostUsd"],
                  "diagnosisEstimatedCostUsd": gain["experimentInvestment"]["diagnosisEstimatedCostUsd"]})
    rows.append(record("room-merge", "Room 整合优化：质量保持，移除重复模型调用", [name], before, after,
        count=1, unit="1 组冻结契约任务，3 条检查；保留基线与一次新候选复验",
        result=f"3/3 检查均通过；模型调用 3→2，完整 turn tokens 下降 {gain['comparison']['tokenReductionPct']:.2f}%，估算成本下降 {gain['comparison']['estimatedCostReductionPct']:.2f}%。",
        action="Lab 诊断选择有 schema 校验的无损程序合并，替换重复模型整合；新 Room 复验并逐 turn 对账。",
        factor_before="两个伙伴 + 模型整合", factor_after="两个伙伴 + 无损程序合并", status="kept", effect="improved",
        boundary="窄工作流优化；不是 Room 优于单 Agent 的证明。初次六调用超出 20k 阈值 407 tokens，失败回执保留。总投入含 8 次调用，工程投入未知。"))

    name = "context-continuation-live-20260905/context-continuation-report.json"
    m = read(name)["metrics"]; u = m["modelUsageCompleteness"]
    after = {"taskCount": m["modelContinuationSuccess"]["total"], "taskSuccessCount": m["modelContinuationSuccess"]["passed"],
        "recallPassed": m["positiveKeyInformationRecall"]["passed"], "recallTotal": m["positiveKeyInformationRecall"]["total"],
        "exclusionPassed": m["negativeMemoryExclusion"]["passed"], "exclusionTotal": m["negativeMemoryExclusion"]["total"],
        "staleExposureCount": m["wrongOrStaleMemoryExposure"]["cases"], "exposureCaseCount": m["wrongOrStaleMemoryExposure"]["total"],
        "providerCalls": u["observedProviderCalls"], "totalTokens": u["observedTotalTokens"], "estimatedApiCostUsd": u["observedEstimatedCostUsd"],
        "memoryContextEstimatedTokens": m["contextTokens"]["memoryContext"]["total"]}
    rows.append(record("memory-continuation", "记忆接续：4 个真实模型任务通过", [name], {}, after,
        count=4, unit="4 个合成 Memory 条件，各一次真实 Pi 回答；8 次上下文投递",
        result="真实模型接续 4/4；正例召回 2/2、负例排除 2/2、错误或过期内容暴露 0/4；上下文估算 452 tokens 与模型用量分列。",
        action="经过 Memory Atom、真实 Context owner 和 Pi Session 消费恢复后的上下文，逐条核验答案。",
        kind="memory", comparison=False, observation=True,
        boundary="无配对收益基线；ACK 与 compaction summary 为夹具，不证明真实自动压缩或生产长期记忆质量。"))

    name = "reliability-metrics-20260905-r3/report.json"; r = read(name)
    after = {"observationPassed": r["passed"], "observationCount": r["observations"], "scenarioCount": r["scenarios"],
        "duplicateSideEffects": r["duplicateSideEffects"], "providerCalls": r["providerCalls"],
        "cancelP95Ms": r["cancelToTerminal"]["p95Ms"], "cancelSamples": r["cancelToTerminal"]["samples"],
        "restoreP95Ms": r["restoreToReadback"]["p95Ms"], "restoreSamples": r["restoreToReadback"]["samples"]}
    rows.append(record("execution-reliability", "执行可靠性：8 类故障、160 次观察", [name], {}, after,
        count=r["observations"], unit="8 类故障 × 20 次，共 160 次受控观察",
        result="160/160 通过，重复副作用 0；取消收口混合 60 样本 p95 31.446 ms，恢复读回混合 60 样本 p95 23.390 ms。",
        action="复用真实 Lab Trial owner 与 SQLite，注入并发准入、ACK 丢失、取消、迟到绑定和 owner 恢复。",
        kind="tool_runtime", comparison=False, observation=True,
        boundary="进程内 owner 重建，模拟业务和 Provider；混合 p95 不代替单故障指标，不代表进程 kill、真实网络或线上 SLA。"))

    name = "micro-selfboot-20260905/reconciled.v2.json"; runs = read(name)["runs"]
    jobs = [j for run in runs for j in run["jobs"] if j["taskId"] == "optimization"]
    job = next(j for run in runs if run["runName"] == "paw-micro-selfboot-r2" for j in run["jobs"] if j["taskId"] == "optimization")
    def policy_arm(index, key):
        call = job["calls"][index]; score = job["artifacts"]["comparison"][key]
        negative = [c for c in score["cases"] if c["expected"] != "approved"]
        return {"taskCount": 1, "taskSuccessCount": int(score["allPassed"]), "verifierPassCount": score["passed"], "verifierCount": score["total"],
            "providerCalls": call["providerCalls"], "totalTokens": call["usage"]["totalTokens"], "estimatedApiCostUsd": call["usage"]["estimatedCostUsd"],
            "forbiddenApprovals": sum(c["actual"] == "approved" for c in negative), "negativeCaseCount": len(negative)}
    before, after = policy_arm(0, "baseline"), policy_arm(2, "candidate")
    after.update({"optimizationProviderCalls": sum(j["providerCalls"] for j in jobs), "optimizationTokens": sum(j["totalTokens"] for j in jobs),
                  "optimizationEstimatedCostUsd": sum(j["estimatedCostUsd"] for j in jobs)})
    rows.append(record("expense-optimization", "费用规则优化：质量通过，成本未改善", [name], before, after,
        count=1, unit="1 个配置生成任务、4 条业务断言；r2 配对，首轮失败计入投入",
        result="基线与候选均 4/4，禁止直接批准事件均 0/3；估算成本 $0.000553→$0.0011352，未测出成本收益。两轮总投入 7 次模型调用、17,715 tokens。",
        action="Lab 诊断候选配置，Host 固定业务验收，并核算失败候选与诊断投入。",
        factor_before="原配置生成提示", factor_after="诊断后的候选提示", effect="regressed",
        boundary="候选知情的合成开发验证，未消费盲测；严重错误定义仅限三条禁止批准规则，不推广到其他企业场景。"))

    name = "policy-web-app-20260905/acceptance.json"; app = read(name)
    ui_name = "policy-web-app-20260905/browser-acceptance.json"; ui = read(ui_name)
    if app["archiveSha256"] != ui["archiveSha256"] or ui["apiMocked"]:
        raise ValueError("App acceptance archive or real API identity mismatch")
    after = {"startupPassed": app["startupPasses"], "startupCount": app["startupAttempts"],
        "observationPassed": app["businessPasses"], "observationCount": app["businessObservations"],
        "uniqueBusinessCases": app["uniqueBusinessCases"], "uiPassed": ui["passed"], "uiCount": ui["total"],
        "parityPassed": int(app["parity"]), "providerCalls": app["providerCalls"] + ui["providerCalls"]}
    rows.append(record("standalone-export", "独立费用 App：隔离启动与真实界面验收", [name, ui_name], {}, after,
        count=4, unit="1 个导出包，4 个唯一业务用例，3 次启动共 12 次业务观察；另有 4 次 UI 验收",
        result="隔离启动 3/3、业务观察 12/12、真实界面操作 4/4；导出前后结果一致，验证阶段未调用模型。",
        action="将同一 Lab 配置导出为 Python 标准库 Web App，空 HOME、新工作目录和隔离 Python 启动，再从真实界面提交四条输入。",
        kind="other", comparison=False, observation=True,
        boundary="无对照提升结论；依赖 Python 标准库，不是原生 macOS App，未在另一台实体机器验收；不代表所有 PAW App 均可独立使用。"))

    names = [f"medium-ledger-tools-20260905/{arm}/report.json" for arm in ("solo", "room")]
    def medium(arm):
        x = read(arm); u = x["observed"]
        return {"taskCount": 1, "taskSuccessCount": int(x["completeTaskPassed"]),
            "verifierPassCount": x["finalChecks"]["passed"], "verifierCount": x["finalChecks"]["total"],
            "deliveryPassed": x["delivery"]["passed"], "deliveryCount": x["delivery"]["total"],
            "continuationEntered": int(any(s["name"] == "continuation" for s in x["stages"])),
            "providerCalls": u["providerCalls"], "totalTokens": u["tokens"], "estimatedApiCostUsd": u["estimatedCostUsd"], "latencyMs": x["wallMs"]}
    before, after = map(medium, names)
    rows.append(record("medium-ledger-blocked", "中等任务：存储已完成，整题尚未完成", names, before, after,
        count=1, unit="1 个中等编码任务，每臂 3 阶段、20 条实现检查与 4 条实际交付检查",
        result="两臂存储检查均 6/6，最终实现检查 6/20、交付 0/4、完整任务 0/1；每臂触及 100k 观察 tokens，尚未进入报告与接续阶段。",
        action="单 Session 与 Room 从同一 seed 实现持久事件账本，记录真实工作区、Pi turn 和预算停止。",
        factor_before="同一 Session 分阶段工作", factor_after="Room 按存储、报告、整合责任接力",
        comparison=False,
        boundary="WorkspaceHarness 禁止 .sqlite 文件访问，导致阶段测试重试；此运行存在环境阻塞，不能归因为单 Agent 或多 Agent 能力差异。首次空工具目录的无效运行另行保留。"))
    continued=root/'medium-jsonl-continued-20260906'
    if (continued/'parent-reconciliation.json').exists():
        verification='medium-jsonl-continued-20260906/parent-reconciliation.json';v=read(verification)
        if not v['sameSeedAndTask']:raise ValueError('medium comparison task binding changed')
        names=[f'medium-jsonl-continued-20260906/{arm}/report.json' for arm in ('solo','room')]
        reports=[read(name) for name in names]
        def observed(x):
            u=x['observed']
            metrics={'taskSuccessCount':int(x['completeTaskPassed']),'taskCount':1,
                'verifierPassCount':x['finalChecks']['passed'],'verifierCount':x['finalChecks']['total'],
                'deliveryPassed':x['delivery']['passed'],'deliveryCount':x['delivery']['total'],
                'modelAttemptMessages':u['providerCalls'],'observedTokens':u['tokens'],
                'knownEstimatedApiCostUsd':u['estimatedCostUsd'],'latencyMs':x['wallMs'],
                'continuationEntered':int(any(s['name']=='continuation' for s in x['stages']))}
            if x['hostRestartedAndContinued']:
                metrics['restartPreserved'] = 1
            return metrics
        rows.append(record('medium-jsonl-pair','中等任务：已进入重启接续，整题未通过',names+[verification],observed(reports[0]),observed(reports[1]),
            count=1,unit='1 个中等文件账本任务，20 条实现检查、4 条交付检查；每臂累计 300k 观察 tokens / 30 条模型响应上限',
            result='两臂完整任务均 0/1、实现检查 16/20、交付 0/4；Room 重启后进入追加需求阶段，单 Session 在报告阶段停止。未证明多 Agent 提升任务成功率。',
            action='相同空实现、Luna low 与分阶段任务；先保留 100k 预算停止，再从原产物续跑至统一 300k 累计上限。Room 新伙伴接力，单 Session 保留私有历史。',
            factor_before='同一 Session 继续',factor_after='Room 分工和持久交接',comparison=False,
            boundary='一组配对不是总体成功率。两侧有在途请求越过观察阈值，费用只记已知估算。接续进入不等于接续任务成功。旧 Host 回放检查会改写检查库，原交付失败保留；验收器已改为副本检查，不升级旧结果。'))
    return {"schemaVersion": "paw.interview-agent-experiment-ledger.v1", "generatedAt": "2026-09-06", "experiments": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artifacts-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ledger = build_ledger(args.artifacts_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(ledger, stream, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    print(json.dumps({"experiments": len(ledger["experiments"]), "output": str(args.output)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
