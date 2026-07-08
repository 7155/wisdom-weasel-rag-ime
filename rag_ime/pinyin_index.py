from __future__ import annotations

import os
import re

from .text_utils import compact_whitespace


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]*")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")
_FUZZY_PAIR_DEFAULTS: dict[str, bool] = {
    "z_zh": True,
    "c_ch": True,
    "s_sh": True,
    "en_eng": True,
    "in_ing": True,
    "n_l": False,
    "f_h": False,
}
_FUZZY_PAIR_ENV_NAMES: dict[str, tuple[str, ...]] = {
    "z_zh": ("RAG_IME_PINYIN_FUZZY_Z_ZH", "RAG_IME_PINYIN_FUZZY_PAIR_Z_ZH"),
    "c_ch": ("RAG_IME_PINYIN_FUZZY_C_CH", "RAG_IME_PINYIN_FUZZY_PAIR_C_CH"),
    "s_sh": ("RAG_IME_PINYIN_FUZZY_S_SH", "RAG_IME_PINYIN_FUZZY_PAIR_S_SH"),
    "en_eng": ("RAG_IME_PINYIN_FUZZY_EN_ENG", "RAG_IME_PINYIN_FUZZY_PAIR_EN_ENG"),
    "in_ing": ("RAG_IME_PINYIN_FUZZY_IN_ING", "RAG_IME_PINYIN_FUZZY_PAIR_IN_ING"),
    "n_l": ("RAG_IME_PINYIN_FUZZY_N_L", "RAG_IME_PINYIN_FUZZY_PAIR_N_L"),
    "f_h": ("RAG_IME_PINYIN_FUZZY_F_H", "RAG_IME_PINYIN_FUZZY_PAIR_F_H"),
}


_CJK_INITIALS: dict[str, str] = {
    "把": "b",
    "本": "b",
    "不": "b",
    "成": "c",
    "词": "c",
    "传": "c",
    "次": "c",
    "的": "d",
    "地": "d",
    "点": "d",
    "调": "d",
    "段": "d",
    "法": "f",
    "方": "f",
    "高": "g",
    "个": "g",
    "候": "h",
    "和": "h",
    "后": "h",
    "化": "h",
    "记": "j",
    "计": "j",
    "将": "j",
    "接": "j",
    "进": "j",
    "景": "j",
    "纠": "j",
    "据": "j",
    "快": "k",
    "库": "k",
    "历": "l",
    "流": "l",
    "路": "l",
    "模": "m",
    "面": "m",
    "片": "p",
    "频": "p",
    "拼": "p",
    "起": "q",
    "前": "q",
    "器": "q",
    "强": "q",
    "入": "r",
    "上": "s",
    "设": "s",
    "示": "s",
    "式": "s",
    "输": "s",
    "首": "s",
    "索": "s",
    "态": "t",
    "统": "t",
    "通": "t",
    "文": "w",
    "我": "w",
    "稳": "w",
    "想": "x",
    "显": "x",
    "项": "x",
    "选": "x",
    "型": "x",
    "用": "y",
    "一": "y",
    "优": "y",
    "语": "y",
    "约": "y",
    "元": "y",
    "预": "y",
    "源": "y",
    "展": "z",
    "找": "z",
    "这": "z",
    "置": "z",
    "中": "z",
    "状": "z",
    "注": "z",
    "转": "z",
}

_CJK_FULL_PINYIN: dict[str, str] = {
    "白": "bai",
    "楚": "chu",
    "继": "ji",
    "看": "kan",
    "来": "lai",
    "明": "ming",
    "起": "qi",
    "清": "qing",
    "下": "xia",
    "想": "xiang",
    "向": "xiang",
    "先": "xian",
    "续": "xu",
    "一": "yi",
}


_PHRASE_INITIALS: tuple[tuple[str, str], ...] = (
    ("RAG", "rag"),
    ("Agent", "agent"),
    ("Codex", "codex"),
    ("FTS5", "fts5"),
    ("LLM", "llm"),
    ("MLX", "mlx"),
    ("Qwen", "qwen"),
    ("Rime", "rime"),
    ("SQLite", "sqlite"),
    ("Squirrel", "squirrel"),
    ("VCP", "vcp"),
    ("输入法", "srf"),
    ("候选", "hx"),
    ("展示", "zs"),
    ("方式", "fs"),
    ("设计", "sj"),
    ("状态机", "ztj"),
    ("个人记忆", "grjy"),
    ("本地记忆", "bdjy"),
    ("本地", "bd"),
    ("记忆", "jy"),
    ("预测", "yc"),
    ("拼音", "py"),
    ("首词", "sc"),
    ("锚定", "md"),
    ("约束", "ys"),
    ("继续", "jx"),
    ("上下文", "sxw"),
    ("管理面板", "glmb"),
)

_PHRASE_PINYIN_KEYS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("输入法", ("shurufa",)),
    ("候选", ("houxuan",)),
    ("展示", ("zhanshi",)),
    ("方式", ("fangshi",)),
    ("设计", ("sheji",)),
    ("状态机", ("zhuangtaiji",)),
    ("个人记忆", ("gerenjiyi",)),
    ("本地记忆", ("bendijiyi",)),
    ("记忆", ("jiyi",)),
    ("预测", ("yuce",)),
    ("拼音", ("pinyin",)),
    ("上下文", ("shangxiawen",)),
    ("管理面板", ("guanlimianban",)),
    ("世界", ("shijie",)),
)


def build_pinyin_metadata(text: str) -> dict[str, object]:
    """Build best-effort pinyin keys for local phrase-memory filtering.

    The production route should eventually use Rime/wanxiang's own spelling
    data. This zero-dependency fallback keeps local-memory prefix filtering
    useful even before that adapter is available.
    """

    compact = compact_whitespace(text)
    if not compact:
        return {"initials": "", "pinyin_prefixes": []}
    initials = text_initials(compact)
    prefixes = pinyin_prefixes(compact, initials=initials)
    full_pinyin = text_full_pinyin(compact)
    return {
        "initials": initials,
        "pinyin_initials": initials,
        "pinyin_prefixes": prefixes,
        "full_pinyin": full_pinyin,
    }


def pinyin_search_document(*parts: str) -> str:
    terms: list[str] = []

    def add(value: str) -> None:
        key = _pinyin_key(value)
        if key and key not in terms:
            terms.append(key)

    for part in parts:
        compact = compact_whitespace(part)
        if not compact:
            continue
        add(text_initials(compact))
        for prefix in pinyin_prefixes(compact):
            add(prefix)
    return " ".join(terms)


def pinyin_search_terms(*parts: str) -> dict[str, str]:
    terms: dict[str, str] = {}

    def add(value: str, *, source: str) -> None:
        key = _pinyin_key(value)
        if key and key not in terms:
            terms[key] = source

    for part in parts:
        compact = compact_whitespace(part)
        if not compact:
            continue
        add(text_initials(compact), source="exact")
        for prefix in pinyin_prefixes(compact, include_fuzzy=False):
            add(prefix, source="exact")
    for term in list(terms):
        for variant in fuzzy_pinyin_variants(term):
            add(variant, source="fuzzy")
    return terms


def text_initials(text: str) -> str:
    parts: list[str] = []
    for char in compact_whitespace(text):
        if char.isspace():
            continue
        if char.isascii() and char.isalnum():
            parts.append(char.lower())
            continue
        initial = _CJK_INITIALS.get(char)
        if initial:
            parts.append(initial)
    return "".join(parts)


def pinyin_prefixes(text: str, *, initials: str | None = None, include_fuzzy: bool = True) -> list[str]:
    compact = compact_whitespace(text)
    keys: list[str] = []

    def add(value: str, *, fuzzy: bool = True) -> None:
        key = _pinyin_key(value)
        if key and key not in keys:
            keys.append(key)
        if fuzzy and include_fuzzy:
            for variant in fuzzy_pinyin_variants(key):
                if variant and variant not in keys:
                    keys.append(variant)

    if initials is None:
        initials = text_initials(compact)
    add(initials)

    for source, key in _PHRASE_INITIALS:
        if source in compact:
            add(key)

    for source, values in _PHRASE_PINYIN_KEYS:
        if source in compact:
            for key in values:
                add(key)

    for token in _ASCII_TOKEN_RE.findall(compact):
        add(token, fuzzy=False)

    # Add initials for short Chinese windows, so typing "hx" can match a
    # phrase like "设计一个候选展示方式", not only prefixes from the beginning.
    cjk_chars = [char for char in compact if _CJK_RE.fullmatch(char)]
    for size in (2, 3, 4):
        for index in range(0, max(0, len(cjk_chars) - size + 1)):
            add("".join(_CJK_INITIALS.get(char, "") for char in cjk_chars[index : index + size]))

    return keys[:32]


def text_full_pinyin(text: str) -> list[str]:
    parts: list[str] = []
    for char in compact_whitespace(text):
        if char.isspace():
            continue
        if char.isascii() and char.isalnum():
            parts.append(char.lower())
            continue
        pinyin = _CJK_FULL_PINYIN.get(char)
        if pinyin:
            parts.append(pinyin)
        elif parts:
            break
    return parts[:16]


def _pinyin_key(value: str) -> str:
    return "".join(char.lower() for char in compact_whitespace(value) if char.isascii() and char.isalnum())


def fuzzy_pinyin_variants(value: str, *, limit: int = 24) -> tuple[str, ...]:
    key = _pinyin_key(value)
    if not key or not _fuzzy_pinyin_enabled():
        return ()
    variants: list[str] = []
    seen = {key}
    queue = [key]
    while queue and len(variants) < limit:
        current = queue.pop(0)
        for candidate in _fuzzy_pinyin_one_step(current):
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            variants.append(candidate)
            if len(variants) >= limit:
                break
            queue.append(candidate)
    return tuple(variants)


def _fuzzy_pinyin_enabled() -> bool:
    disabled = {"0", "false", "no", "off", "none", "disabled"}
    enabled = os.environ.get("RAG_IME_PINYIN_FUZZY_ENABLED", "").strip().lower()
    if enabled in disabled:
        return False
    profile = os.environ.get("RAG_IME_PINYIN_FUZZY_PROFILE", "").strip().lower()
    if profile in disabled:
        return False
    return True


def _fuzzy_pinyin_one_step(value: str) -> tuple[str, ...]:
    variants: list[str] = []

    def add(candidate: str) -> None:
        if candidate and candidate != value and candidate not in variants:
            variants.append(candidate)

    for pair, source, target in (("z_zh", "zh", "z"), ("c_ch", "ch", "c"), ("s_sh", "sh", "s")):
        if not _fuzzy_pair_enabled(pair):
            continue
        start = 0
        while True:
            index = value.find(source, start)
            if index < 0:
                break
            add(value[:index] + target + value[index + len(source) :])
            start = index + 1

    for pair, source, target in (("z_zh", "z", "zh"), ("c_ch", "c", "ch"), ("s_sh", "s", "sh")):
        if not _fuzzy_pair_enabled(pair):
            continue
        for index, char in enumerate(value):
            if char != source:
                continue
            if index + 1 < len(value) and value[index + 1] == "h":
                continue
            add(value[:index] + target + value[index + 1 :])

    for pair, source, target in (
        ("en_eng", "eng", "en"),
        ("en_eng", "en", "eng"),
        ("in_ing", "ing", "in"),
        ("in_ing", "in", "ing"),
    ):
        if _fuzzy_pair_enabled(pair) and value.endswith(source):
            add(value[: -len(source)] + target)

    for pair, source, target in (("n_l", "n", "l"), ("n_l", "l", "n"), ("f_h", "h", "f"), ("f_h", "f", "h")):
        if not _fuzzy_pair_enabled(pair):
            continue
        for index, char in enumerate(value):
            if char == source:
                add(value[:index] + target + value[index + 1 :])

    return tuple(variants)


def _fuzzy_pair_enabled(pair: str) -> bool:
    default = _FUZZY_PAIR_DEFAULTS.get(pair, False)
    for env_name in _FUZZY_PAIR_ENV_NAMES.get(pair, ()):
        raw = os.environ.get(env_name, "").strip().lower()
        if raw:
            return raw in {"1", "true", "yes", "on", "enabled"}
    return default
