from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class SettingsUpdateResult:
    settings: dict[str, object]
    audit_id: int
    changed_keys: tuple[str, ...]


@dataclass(frozen=True)
class UserProfile:
    profile_id: str
    profile_kind: str
    label: str
    description: str
    settings: dict[str, Any]
    enabled: bool = True


@dataclass(frozen=True)
class UserVocabularyItem:
    vocab_id: str
    surface: str
    aliases: tuple[str, ...] = ()
    pinyin: str = ""
    tags: tuple[str, ...] = ()
    scope: str = "global"
    priority: int = 0
    status: str = "active"
