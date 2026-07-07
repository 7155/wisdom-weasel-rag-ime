#!/usr/bin/env python3
"""Generate natural Chinese raw sentences for IME pretrain text."""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path


ASCII_RE = re.compile(r"[A-Za-z0-9]")
NOISE_RE = re.compile(r"(.)\1{4,}")
LONG_REPEAT_RE = re.compile(r"(.{2,5})\1{2,}")
PUNCT_STACK_RE = re.compile(r"[，。；？！……]{2,}")


SUBJECTS = [
    "我", "我们", "今天", "昨晚", "上午", "团队", "同事", "开发同学", "产品同学", "训练组", "算法组",
    "运维同学", "体验同学", "项目经理", "用户", "反馈同学", "数据同学", "输入法", "上下文", "这次发布",
    "日志", "训练日志", "内测组", "验收", "预发", "发布窗口", "回归测试", "实验组", "评测同学",
    "反馈样本", "新会话", "会话历史", "窗口状态", "中文语料", "短语词库", "用户习惯", "热词表", "个人词条",
    "候选窗口", "脚本", "模型", "推理链路", "训练代码", "语料切片", "配置项", "离线任务", "线上指标",
    "内存状态", "进程", "反馈队列", "验收清单", "版本记录", "本地模型", "候选算法", "语义边界", "窗口输入",
    "节奏控制", "空候选", "负样本", "正样本", "长句", "短句", "口语片段", "书面语", "工作台", "测试台",
]


TIME_ADVERBS = [
    "今天", "明天", "今晚", "下周", "本周", "这会儿", "下午", "半小时后", "早些时候", "刚才", "刚刚", "今晚", "最近", "近期",
    "最近几天", "下一轮", "每次", "偶尔",
]


NOUNS = [
    "候选质量", "补全速度", "输入节奏", "误补率", "复读率", "后缀长度", "候选可读性", "延迟分布", "上下文长度",
    "私有词触发", "本地偏好", "用户偏好", "新词上屏", "短语触发条件", "禁用词", "重试逻辑", "空目标样本",
    "噪声样本", "高频重复", "切片边界", "训练窗口", "采样比例", "回归结果", "反馈时序", "错误分布", "稳定性",
    "候选顺序", "候选一致性", "反馈日志", "词频统计", "语料稀疏", "上下文漂移", "隐私边界", "输入断点", "窗口抖动",
    "回车节奏", "停顿点", "输入法体验", "模型置信度", "离线指标", "在线指标", "回退策略", "降噪逻辑", "短语池",
    "记忆更新", "记忆回看", "行为序列", "候选复用", "实验报告", "上线进度", "预估误差", "版本差异", "异常告警",
    "观察点", "复盘提纲", "反馈闭环", "用户未删", "用户已删",
]


VERB_PHRASES = [
    "整理{obj}", "看一下{obj}", "复盘一下{obj}", "再做验证{obj}", "准备{obj}", "确认{obj}", "同步{obj}",
    "抽查{obj}", "再做对齐{obj}", "删掉重复{obj}", "补齐{obj}", "标注{obj}", "清理{obj}", "压缩{obj}",
    "回看{obj}", "收口{obj}", "对比{obj}", "对齐{obj}", "回样{obj}", "留空{obj}", "重放{obj}", "归档{obj}",
]


REASONS = [
    "误补太多了", "候选偏离上下文", "模型又多猜了一次", "用户连续删除", "重复展示太密", "窗口抖动明显",
    "上下文切换很快", "新词命中不稳定", "回退样本太少", "日志和体验不一致", "反馈量不足", "短语太长干扰选择",
    "低置信度样本太多",
]


CLAUSES = [
    "体验会更顺", "线上表现更稳", "误补会少很多", "用户更少被打断", "候选更容易命中", "输入节奏更连贯",
    "更新更可控", "数据更不乱飘", "回归更容易过", "异常更容易定位", "后面少踩坑", "指标更平滑", "体验更自然",
    "不容易复读", "响应更快一点", "重复候选会变少", "测试更容易写", "团队更容易对齐", "排障路径更短", "上线更快",
    "回改动更清晰", "对话更顺", "训练更有边界", "后续更容易做成组", "优先级更稳定", "反馈更容易复现", "结果更好对齐",
]


COMPLEMENTS = [
    "先跑一批样例看看", "留出一组对照再说", "再做一次采样验证", "观察一小时再定结论", "先别改参数先看趋势",
    "把边界值拉紧点", "把策略回退到上个版本", "先补齐异常样本清单", "先把新词记录下来", "把实验结论同步给大家",
    "再把反馈再看一次", "留一个降级方案", "再加一条日志", "先写成最小可复现",
]


CONNECTORS = ["并且", "然后", "而且", "同时", "不过", "所以", "因为", "此外", "另外", "接着", "尤其", "对应地", "同时也"]

BANNED = ["prompt", "assistant", "system", "user", "回答", "解释", "说明", "模板", "思考"]


def render_verb_phrase(rng: random.Random) -> str:
    phrase = rng.choice(VERB_PHRASES).format(obj=rng.choice(NOUNS))
    if "先" in phrase:
        phrase = phrase.replace("先", "", 1)
    return phrase


def sentence_pattern_a(rng: random.Random) -> str:
    s = rng.choice(SUBJECTS)
    v = render_verb_phrase(rng)
    c = rng.choice(CLAUSES)
    return f"{s}{v}，{c}。"


def sentence_pattern_b(rng: random.Random) -> str:
    t = rng.choice(TIME_ADVERBS)
    s = rng.choice(SUBJECTS)
    v = render_verb_phrase(rng)
    c = rng.choice(COMPLEMENTS)
    return f"{t}{s}{v}，{c}。"


def sentence_pattern_c(rng: random.Random) -> str:
    cause = rng.choice(REASONS)
    s = rng.choice(SUBJECTS)
    n = rng.choice(NOUNS)
    c = rng.choice(CLAUSES)
    return f"因为{cause}，{s}要优先处理{n}，{c}。"


def sentence_pattern_d(rng: random.Random) -> str:
    s = rng.choice(SUBJECTS)
    n1 = rng.choice(NOUNS)
    n2 = rng.choice(NOUNS)
    while n2 == n1:
        n2 = rng.choice(NOUNS)
    return f"{s}在{n1}和{n2}之间取舍时，{rng.choice(CLAUSES)}。"


def sentence_pattern_e(rng: random.Random) -> str:
    lead = rng.choice(["把", "先", "再"])
    noun = rng.choice(NOUNS)
    v = render_verb_phrase(rng)
    return f"{lead}{noun}{rng.choice(['先', '后', '再'])}{v}，{rng.choice(CLAUSES)}。"


def sentence_pattern_f(rng: random.Random) -> str:
    n = rng.choice(NOUNS)
    t = rng.choice(["很关键", "更明显", "更敏感", "更重要"])
    c = rng.choice(CLAUSES)
    return f"{n}{t}，{c}。"


def sentence_pattern_g(rng: random.Random) -> str:
    n = rng.choice(NOUNS)
    s = rng.choice(SUBJECTS)
    d = rng.choice(["一旦", "当", "如果"])
    c = rng.choice(CLAUSES)
    return f"{s}{d}{n}进入了变化阶段，{c}。"


PATTERNS = [
    sentence_pattern_a,
    sentence_pattern_b,
    sentence_pattern_c,
    sentence_pattern_d,
    sentence_pattern_e,
    sentence_pattern_f,
    sentence_pattern_g,
]


def is_valid(sentence: str, seen_signatures: set[str]) -> bool:
    sentence = sentence.strip()
    if len(sentence) < 10 or len(sentence) > 78:
        return False
    if ASCII_RE.search(sentence):
        return False
    if NOISE_RE.search(sentence) or LONG_REPEAT_RE.search(sentence):
        return False
    if PUNCT_STACK_RE.search(sentence):
        return False
    if sentence.count("，") > 3:
        return False
    for bad in BANNED:
        if bad in sentence:
            return False
    signature = sentence.replace("，", "").replace("。", "")
    if signature in seen_signatures:
        return False
    return True


def generate_sentence(rng: random.Random) -> str:
    pattern = rng.choice(PATTERNS)
    return pattern(rng).replace("  ", "")


def generate(count: int, seed: int) -> list[dict[str, str]]:
    rng = random.Random(seed)
    rows: list[dict[str, str]] = []
    seen_signatures: set[str] = set()
    attempts = 0
    max_attempts = count * 260

    while len(rows) < count and attempts < max_attempts:
        attempts += 1
        sentence = generate_sentence(rng)
        if not is_valid(sentence, seen_signatures):
            continue
        rows.append({"text": sentence})
        seen_signatures.add(sentence.replace("，", "").replace("。", ""))

    if len(rows) < count:
        raise RuntimeError(f"only generated {len(rows)} sentences after {attempts} attempts")
    return rows


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def write_report(path: Path, rows: list[dict[str, str]], seed: int) -> None:
    lengths = [len(row["text"]) for row in rows]
    report = {
        "seed": seed,
        "count": len(rows),
        "min_len": min(lengths),
        "max_len": max(lengths),
        "avg_len": sum(lengths) / len(lengths),
        "contains_ascii": sum(1 for row in rows if ASCII_RE.search(row["text"])),
        "repeated_pattern_like": sum(
            1 for row in rows if NOISE_RE.search(row["text"]) or LONG_REPEAT_RE.search(row["text"])
        ),
        "unique_count": len(set(row["text"] for row in rows)),
        "template_count": len(PATTERNS),
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=20260720)
    parser.add_argument(
        "--output", type=Path, default=Path("dataset/ime_raw_sentences_20k_v2.jsonl")
    )
    parser.add_argument(
        "--report", type=Path, default=Path("dataset/ime_raw_sentences_20k_v2.report.json")
    )
    args = parser.parse_args()

    rows = generate(args.count, args.seed)
    write_jsonl(args.output, rows)
    write_report(args.report, rows, args.seed)
    print(f"wrote {len(rows)} rows to {args.output}")
    print(f"wrote report to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
