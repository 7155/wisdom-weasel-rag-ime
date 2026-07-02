from __future__ import annotations

import re

from .text_utils import compact_whitespace


_ASCII_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9_+#.\-]*")
_CJK_RE = re.compile(r"[\u3400-\u9fff]")


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
    return {
        "initials": initials,
        "pinyin_initials": initials,
        "pinyin_prefixes": prefixes,
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


def pinyin_prefixes(text: str, *, initials: str | None = None) -> list[str]:
    compact = compact_whitespace(text)
    keys: list[str] = []

    def add(value: str) -> None:
        key = _pinyin_key(value)
        if key and key not in keys:
            keys.append(key)

    if initials is None:
        initials = text_initials(compact)
    add(initials)

    for source, key in _PHRASE_INITIALS:
        if source in compact:
            add(key)

    for token in _ASCII_TOKEN_RE.findall(compact):
        add(token)

    # Add initials for short Chinese windows, so typing "hx" can match a
    # phrase like "设计一个候选展示方式", not only prefixes from the beginning.
    cjk_chars = [char for char in compact if _CJK_RE.fullmatch(char)]
    for size in (2, 3, 4):
        for index in range(0, max(0, len(cjk_chars) - size + 1)):
            add("".join(_CJK_INITIALS.get(char, "") for char in cjk_chars[index : index + size]))

    return keys[:32]


def _pinyin_key(value: str) -> str:
    return "".join(char.lower() for char in compact_whitespace(value) if char.isascii() and char.isalnum())
