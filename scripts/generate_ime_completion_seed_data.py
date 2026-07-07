#!/usr/bin/env python3
"""Generate seed data for a prompt-free Chinese IME completion model."""

from __future__ import annotations

import argparse
import json
import random
import re
from collections import Counter
from pathlib import Path


ASCII_WORD_RE = re.compile(r"[A-Za-z]")


TOPICS = [
    "输入法模型",
    "中文补全",
    "本地候选",
    "候选窗口",
    "用户输入历史",
    "本地记忆",
    "短句续写",
    "前台体验",
    "个人语料",
    "语料清洗",
    "训练数据",
    "后缀目标",
    "空候选策略",
    "复读过滤",
    "上下文窗口",
    "候选排序",
    "低延迟推理",
    "轻量模型",
    "本地推理",
    "字词预测",
    "短语记忆",
    "写作习惯",
    "项目笔记",
    "学习计划",
    "论文草稿",
    "工作记录",
    "调试日志",
    "会议记录",
    "知识整理",
    "日常安排",
    "读书笔记",
    "代码说明",
    "文档修改",
    "面试表达",
    "需求整理",
    "问题排查",
    "流程复盘",
    "数据标注",
    "模型评测",
    "反馈记录",
    "版本计划",
    "结构梳理",
    "思路延展",
    "语言习惯",
    "句子收尾",
    "候选质量",
    "私有数据",
    "语义线索",
    "上下文判断",
    "用户偏好",
    "输入节奏",
    "连续文本",
    "自然表达",
    "中文语感",
    "短语补全",
    "候选治理",
    "隐私边界",
    "本地索引",
    "记忆更新",
    "离线整理",
    "候选反馈",
    "文本片段",
    "语料切片",
    "写作辅助",
    "知识卡片",
    "学习复盘",
    "技术路线",
    "产品边界",
    "实验记录",
    "验证结果",
    "运行状态",
    "错误线索",
    "体验问题",
    "候选稳定性",
    "输入上下文",
]

GOALS = [
    "整理清楚",
    "做成最小可用版本",
    "先跑通闭环",
    "收敛到真实场景",
    "保持稳定可控",
    "变得更自然",
    "减少无效输出",
    "控制在短候选里",
    "贴近用户习惯",
    "避免打断输入",
    "先验证效果",
    "逐步扩大规模",
    "形成稳定流程",
    "变成可复用资产",
    "放到本地处理",
    "留给后续优化",
    "优先保证准确",
    "再考虑速度",
    "先看失败样本",
    "再做批量生成",
    "转成训练样本",
    "拆成短后缀",
    "只保留有效部分",
    "避免重复内容",
    "压到几个字",
    "保持中文表达",
    "去掉多余文字",
    "保留自然语气",
    "用于后续训练",
    "用于本地推理",
    "用于候选排序",
    "用于质量评测",
    "变成可检查数据",
    "先做小批量验证",
    "再扩展到全量",
]

OBJECT_GOALS = [
    "整理清楚",
    "做成最小可用版本",
    "跑通闭环",
    "收敛到真实场景",
    "保持稳定可控",
    "变得更自然",
    "减少无效输出",
    "控制在短候选里",
    "贴近用户习惯",
    "避免打断输入",
    "完成效果验证",
    "逐步扩大规模",
    "形成稳定流程",
    "变成可复用资产",
    "放到本地处理",
    "留给后续优化",
    "转成训练样本",
    "拆成短后缀",
    "只保留有效部分",
    "避免重复内容",
    "压到几个字",
    "保持中文表达",
    "去掉多余文字",
    "保留自然语气",
    "用于后续训练",
    "用于本地推理",
    "用于候选排序",
    "用于质量评测",
    "变成可检查数据",
]

PRINCIPLES = [
    "只补新增内容",
    "不要复读前文",
    "不要补无关内容",
    "不要偏离前文",
    "保持候选很短",
    "优先符合语境",
    "优先贴近习惯",
    "低置信度就留空",
    "重复内容直接丢掉",
    "旧内容不能刷屏",
    "上下文变化要失效",
    "候选来源要清楚",
    "接受反馈要升权",
    "删除反馈要降权",
    "隐私数据不外传",
    "本地优先处理",
    "先保证能用",
    "速度放在稳定之后",
    "短句比长句可靠",
    "自然表达比固定话术重要",
    "语感比说明重要",
    "稳定比花哨重要",
    "可插入比完整段落重要",
    "清洗比数量重要",
    "真实输入最有价值",
    "负样本也很关键",
    "空候选也是结果",
    "候选要能直接上屏",
    "生成数据必须过滤",
    "训练文件只留真实文本",
]

CONDITIONS = [
    "上下文很短",
    "用户刚刚删除候选",
    "候选已经出现过",
    "前文反复重复",
    "语义不够明确",
    "输入还在变化",
    "上下文刚切换",
    "候选太长",
    "候选像说明",
    "候选像长段落",
    "候选复读前文",
    "记忆不够相关",
    "前台状态不稳定",
    "用户继续输入",
    "模型没有把握",
    "短语不够自然",
    "后缀接不上",
    "上下文已经过期",
    "文本只有噪声",
    "片段缺少主语",
    "语料来源不清楚",
    "候选被多次拒绝",
    "同一候选刷屏",
    "当前句子已完整",
    "标点已经收尾",
]

ACTIONS = [
    "不出候选",
    "直接留空",
    "降低权重",
    "重新取上下文",
    "等待下一次输入",
    "只给短后缀",
    "先过滤重复",
    "保留更自然的候选",
    "换成更短表达",
    "记录为负样本",
    "加入冷却列表",
    "重新评估相关性",
    "优先显示本地候选",
    "把旧候选清掉",
    "保留最新结果",
    "只训练后半段",
    "切成更短样本",
    "丢掉多余文字",
    "只保留中文片段",
    "重新生成样本",
    "增加空目标",
    "减少长句",
    "检查是否复读",
    "再进入训练集",
]

OBJECTS = [
    "候选",
    "后缀",
    "短语",
    "上下文",
    "训练样本",
    "记忆片段",
    "用户习惯",
    "输入历史",
    "项目术语",
    "中文语料",
    "空目标",
    "负样本",
    "真实反馈",
    "候选排序",
    "质量检查",
    "生成结果",
    "本地数据",
    "文本片段",
    "续写目标",
    "切分位置",
]

BAD_BEHAVIORS = [
    "补无关内容",
    "说明背景",
    "复述前文",
    "生成长段落",
    "输出固定话术",
    "抢走原输入",
    "旧内容刷屏",
    "反复出现",
    "混入英文",
    "暴露隐私",
    "补得太满",
    "变成对话",
    "覆盖原候选",
    "忽略上下文",
    "强行补全",
    "重复当前词",
    "带出无关内容",
]

GOOD_BEHAVIORS = [
    "只给新增后缀",
    "保持短小自然",
    "贴着前文续写",
    "低置信度留空",
    "优先尊重原输入",
    "根据反馈调整",
    "只在合适时出现",
    "接得上就出现",
    "接不上就沉默",
    "按上下文失效",
    "只输出可插入文本",
    "保留中文语感",
    "减少重复候选",
    "优先短语级补全",
    "把长记忆压短",
    "让用户自己选择",
    "把噪声挡在外面",
    "用真实反馈校准",
]

DAILY_CONTEXTS = [
    "今天先把资料整理完",
    "明天上午继续看这部分",
    "这段笔记还需要补充",
    "刚才那个问题可以先放一放",
    "等会儿再把结论写进去",
    "这个地方需要换一种说法",
    "我先把重点标出来",
    "会议之后再统一整理",
    "今晚主要处理这几个问题",
    "这件事先记到待办里",
    "把前面的内容顺一下",
    "下一步先看实际效果",
    "这个例子可以再具体一点",
    "这段话最好改得更自然",
    "先别急着扩大范围",
    "等验证通过再继续",
    "这次先做一个小版本",
    "把错误样本单独挑出来",
    "后面再补更多场景",
    "先从真实输入开始",
]

CONNECTORS = [
    "然后",
    "再",
    "接着",
    "顺便",
    "同时",
    "之后",
    "最后",
    "先",
    "暂时",
    "重点",
    "主要",
    "另外",
    "下一步",
    "这一版",
    "后续",
    "当前",
]

ENDINGS = [
    "就够了",
    "更稳一点",
    "再继续",
    "不要展开",
    "先这样",
    "后面补",
    "慢慢调",
    "更自然",
    "更可控",
    "更贴近输入习惯",
    "更容易验证",
    "不会打断用户",
    "方便后续排查",
    "直接进入训练",
    "形成闭环",
    "看实际效果",
    "保留必要信息",
    "避免噪声",
    "减少误触",
    "方便复盘",
]

NEGATIVE_UNITS = [
    "哈哈",
    "嗯嗯",
    "这个",
    "然后",
    "就是",
    "输入法",
    "模型",
    "候选",
    "测试",
    "重复",
    "一样",
    "看看",
    "再说",
    "随便",
    "等等",
    "啊啊",
    "好好",
    "不是",
]

NOISY_PREFIXES = [
    "。。。。。。",
    "，，，，，，",
    "我我我我我",
    "的的的的的",
    "了了了了了",
    "这这这这这",
    "然后然后然后",
    "就是就是就是",
    "输入输入输入",
    "候选候选候选",
    "模型模型模型",
    "测试测试测试",
    "一样一样一样",
    "随便随便随便",
    "等等等等等等",
    "不是不是不是",
    "看看看看看看",
    "再说再说再说",
]

BAD_JOINS = [
    "先先",
    "再再",
    "要要",
    "就就",
    "把把",
    "应该应该",
    "直接直接",
    "只只",
    "不要不要",
    "继续继续",
]


def sentence_templates(rng: random.Random) -> list[str]:
    topic = rng.choice(TOPICS)
    topic2 = rng.choice(TOPICS)
    goal = rng.choice(GOALS)
    object_goal = rng.choice(OBJECT_GOALS)
    principle = rng.choice(PRINCIPLES)
    condition = rng.choice(CONDITIONS)
    action = action_for_condition(condition, rng)
    obj = rng.choice(OBJECTS)
    bad = rng.choice(BAD_BEHAVIORS)
    good = rng.choice(GOOD_BEHAVIORS)
    daily = rng.choice(DAILY_CONTEXTS)
    connector = rng.choice(CONNECTORS)
    ending = rng.choice(ENDINGS)
    return [
        f"今天先把{topic}{object_goal}",
        f"{topic}最重要的是{principle}",
        f"如果{condition}，就{action}",
        f"遇到{condition}时，先{action}",
        f"这个{topic}不要{bad}，要{good}",
        f"我现在想把{topic}{object_goal}",
        f"后续再把{topic}{object_goal}",
        f"这一版先保证{topic}{ending}",
        f"{daily}，{connector}{goal}",
        f"{topic}和{topic2}要分开处理",
        f"{topic}可以先从{obj}开始",
        f"把{obj}清洗干净以后再训练",
        f"这批{obj}先检查是否复读",
        f"真正有价值的是{principle}",
        f"用户继续输入时应该{action}",
        f"候选接不上前文就{action}",
        f"短候选比长句更容易上屏",
        f"真实输入历史比合成数据更关键",
        f"生成数据必须经过过滤再使用",
        f"训练文件里只保留前缀和后缀",
        f"模型看到前文以后只需要续后面",
        f"候选太像长段落时应该直接丢掉",
        f"最后一轮训练要贴近真实输入",
        f"先用小批量样本验证方向",
        f"不要让模型学会补无关内容",
        f"让补全结果保持几个字到十几个字",
        f"这段内容可以继续写成{goal}",
        f"{topic}的失败样本要单独保留",
        f"{topic}的正样本来自用户接受",
        f"{topic}的负样本来自用户删除",
        f"前台上下文变化以后旧候选要失效",
        f"输入法模型越轻越容易本地运行",
        f"补全结果只要能接上前文就好",
        f"后缀目标太长会影响候选体验",
        f"语料越接近真实输入越有用",
        f"写到这里可以自然接上{ending}",
    ]


def direct_templates(rng: random.Random) -> tuple[str, str]:
    topic = rng.choice(TOPICS)
    topic2 = rng.choice(TOPICS)
    goal = rng.choice(GOALS)
    object_goal = rng.choice(OBJECT_GOALS)
    principle = rng.choice(PRINCIPLES)
    condition = rng.choice(CONDITIONS)
    action = action_for_condition(condition, rng)
    obj = rng.choice(OBJECTS)
    bad = rng.choice(BAD_BEHAVIORS)
    good = rng.choice(GOOD_BEHAVIORS)
    daily = rng.choice(DAILY_CONTEXTS)
    connector = rng.choice(CONNECTORS)
    ending = rng.choice(ENDINGS)
    templates = [
        (f"{topic}不能{bad}，应该", good),
        (f"如果{condition}，就先", action),
        (f"遇到{condition}时，应该", action),
        (f"这批{obj}要先", goal),
        (f"我今天想把{topic}", object_goal),
        (f"后面再把{topic}", object_goal),
        (f"这一版先保证{topic}", ending),
        (f"{daily}，{connector}", goal),
        (f"{topic}和{topic2}应该", "分开处理"),
        (f"真正影响体验的是", principle),
        (f"用户接受候选以后，可以", "提高相关权重"),
        (f"用户删除候选以后，应该", "降低出现频率"),
        (f"候选已经复读前文，就", "直接过滤掉"),
        (f"上下文刚刚变化，旧候选要", "立刻失效"),
        (f"模型没有把握的时候，最好", "不要出候选"),
        (f"输入法补全的训练目标是", "预测新增后缀"),
        (f"训练时前缀部分不算损失，只训练", "后面的补全文本"),
        (f"最后落盘的数据只应该包含", "前缀和后缀"),
        (f"候选窗口里不要塞长说明，只显示", "短补全"),
        (f"生成样本进入训练前必须", "去重和过滤"),
        (f"真实输入历史切片以后可以得到", "高质量样本"),
        (f"普通中文语料适合用来保持", "自然语感"),
        (f"词库材料更适合补充", "常用短语"),
        (f"低价值重复文本应该变成", "空目标样本"),
    ]
    return rng.choice(templates)


def action_for_condition(condition: str, rng: random.Random) -> str:
    if condition in {
        "当前句子已完整",
        "标点已经收尾",
        "模型没有把握",
        "文本只有噪声",
        "前文反复重复",
        "候选复读前文",
        "候选被多次拒绝",
        "同一候选刷屏",
    }:
        return rng.choice(["不出候选", "直接留空", "等待下一次输入", "记录为负样本", "降低权重"])
    return rng.choice(ACTIONS)


def pair_from_sentence(sentence: str, rng: random.Random) -> tuple[str, str]:
    sentence = sentence.strip()
    max_completion = min(14, max(2, len(sentence) // 2))
    min_completion = 2
    completion_len = rng.randint(min_completion, max_completion)
    prefix = sentence[:-completion_len]
    completion = sentence[-completion_len:]
    return prefix, completion


def negative_pair(rng: random.Random) -> tuple[str, str]:
    if rng.random() < 0.35:
        prefix = rng.choice(NOISY_PREFIXES)
        if rng.random() < 0.5:
            prefix += rng.choice(["，", "。", "，然后", "，就是", "，这个", "，先"])
        if rng.random() < 0.35:
            prefix += rng.choice(TOPICS)
        return prefix, ""
    unit = rng.choice(NEGATIVE_UNITS)
    count = rng.randint(3, 7)
    prefix = unit * count
    if rng.random() < 0.4:
        prefix += rng.choice(["，", "。", "，然后", "，就是", "，这个"])
    return prefix, ""


def clean_text(text: str) -> str:
    return text.strip().replace(" ", "").replace("\t", "")


def is_valid(prefix: str, completion: str) -> bool:
    prefix = clean_text(prefix)
    completion = clean_text(completion)
    if len(prefix) < 3 or len(prefix) > 80:
        return False
    if ASCII_WORD_RE.search(prefix) or ASCII_WORD_RE.search(completion):
        return False
    if completion:
        if len(completion) > 16:
            return False
        joined = prefix + completion
        if any(bad in joined for bad in BAD_JOINS):
            return False
        if completion in prefix[-48:]:
            return False
        if prefix.endswith(completion[: min(4, len(completion))]):
            return False
        if any(bad in joined for bad in ("可以通过", "以下是", "作为", "我是", "回答", "解释", "助手", "思考", "模板")):
            return False
    return True


def generate_pair(rng: random.Random) -> tuple[str, str, str]:
    roll = rng.random()
    if roll < 0.09:
        prefix, completion = negative_pair(rng)
        return clean_text(prefix), completion, "empty"
    if roll < 0.48:
        prefix, completion = direct_templates(rng)
        return clean_text(prefix), clean_text(completion), "direct"
    sentence = rng.choice(sentence_templates(rng))
    prefix, completion = pair_from_sentence(sentence, rng)
    return clean_text(prefix), clean_text(completion), "sentence"


def generate(count: int, seed: int) -> tuple[list[dict[str, str]], Counter[str]]:
    rng = random.Random(seed)
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    categories: Counter[str] = Counter()
    attempts = 0
    max_attempts = count * 200
    while len(rows) < count and attempts < max_attempts:
        attempts += 1
        prefix, completion, category = generate_pair(rng)
        key = (prefix, completion)
        if key in seen or not is_valid(prefix, completion):
            continue
        seen.add(key)
        rows.append({"prefix": prefix, "completion": completion})
        categories[category] += 1
    if len(rows) != count:
        raise RuntimeError(f"only generated {len(rows)} rows after {attempts} attempts")
    return rows, categories


def write_jsonl(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def write_report(path: Path, rows: list[dict[str, str]], categories: Counter[str], seed: int) -> None:
    report = {
        "seed": seed,
        "count": len(rows),
        "non_empty": sum(1 for row in rows if row["completion"]),
        "empty": sum(1 for row in rows if not row["completion"]),
        "categories": dict(categories),
        "max_prefix_chars": max(len(row["prefix"]) for row in rows),
        "max_completion_chars": max(len(row["completion"]) for row in rows),
        "ascii_content_rows": sum(1 for row in rows if ASCII_WORD_RE.search(row["prefix"] + row["completion"])),
        "duplicate_rows": len(rows) - len({(row["prefix"], row["completion"]) for row in rows}),
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=20_000)
    parser.add_argument("--seed", type=int, default=20260707)
    parser.add_argument("--output", type=Path, default=Path("dataset/ime_completion_seed_20k.jsonl"))
    parser.add_argument("--report", type=Path, default=Path("dataset/ime_completion_seed_20k.report.json"))
    args = parser.parse_args()

    rows, categories = generate(args.count, args.seed)
    write_jsonl(args.output, rows)
    write_report(args.report, rows, categories, args.seed)
    print(f"wrote {len(rows)} rows to {args.output}")
    print(f"wrote report to {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
