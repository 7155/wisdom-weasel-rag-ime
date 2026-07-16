from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


VOICE_HOTWORD_SCHEMA_VERSION = "rag-ime.voice-hotwords.v1"
VOICE_AGENT_STATUS_SCHEMA_VERSIONS = {
    "rag-ime.voice-agent-status.v2",
    "rag-ime.voice-agent-status.v3",
    "rag-ime.voice-agent-status.v4",
}
MAX_HOTWORD_COUNT = 32
MIN_HOTWORD_CHARACTERS = 2
MAX_HOTWORD_CHARACTERS = 9
VOICE_PROVIDER_SCHEMA_VERSION = "rag-ime.voice-provider.v1"
VOICE_HOTKEY_SCHEMA_VERSION = "rag-ime.voice-hotkey.v1"
VOICE_BUILD_MARKER_SCHEMA_VERSION = "rag-ime.voice-build-marker.v1"
VOICE_PROVIDERS = frozenset(
    {"native_streaming", "realtime_websocket", "http_transcription"}
)
VOICE_HOTKEYS = frozenset({"middle_mouse", "right_option", "option_space"})

# Inline BigASR context accepts mixed Chinese/English words and numeric forms
# such as CO2. Keep punctuation restricted to common technical-name
# separators so JSON/control characters never enter the provider context.
ALLOWED_TECHNICAL_SEPARATORS = frozenset(".-_+#/&")


class VoiceHotwordValidationError(ValueError):
    pass


@dataclass(frozen=True)
class VoiceHotwordConfig:
    enabled: bool
    words: tuple[str, ...]

    @property
    def effective_words(self) -> tuple[str, ...]:
        return self.words if self.enabled else ()

    def payload(self) -> dict[str, object]:
        return {
            "schemaVersion": VOICE_HOTWORD_SCHEMA_VERSION,
            "enabled": self.enabled,
            "words": list(self.words),
        }


def normalize_voice_hotwords(
    words: object,
    *,
    enabled: bool | None = None,
) -> tuple[str, ...]:
    if not isinstance(words, (list, tuple)):
        raise VoiceHotwordValidationError("voice.hotwords must be an array")
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_word in words:
        if not isinstance(raw_word, str):
            raise VoiceHotwordValidationError("voice.hotwords entries must be strings")
        word = " ".join(raw_word.strip().split())
        if not word:
            continue
        length = len(word)
        if length < MIN_HOTWORD_CHARACTERS or length > MAX_HOTWORD_CHARACTERS:
            raise VoiceHotwordValidationError(
                f'voice hotword "{word}" must contain 2 to 9 characters'
            )
        if not all(_allowed_hotword_character(char) for char in word):
            raise VoiceHotwordValidationError(
                f'voice hotword "{word}" contains unsupported characters'
            )
        dedupe_key = unicodedata.normalize("NFKC", word).casefold()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized.append(word)
        if len(normalized) > MAX_HOTWORD_COUNT:
            raise VoiceHotwordValidationError(
                f"voice.hotwords supports at most {MAX_HOTWORD_COUNT} entries"
            )
    if enabled is True and not normalized:
        raise VoiceHotwordValidationError("enabled voice hotwords require at least one word")
    return tuple(normalized)


def _allowed_hotword_character(char: str) -> bool:
    if char.isspace() or char in ALLOWED_TECHNICAL_SEPARATORS:
        return True
    return unicodedata.category(char).startswith(("L", "N"))


class VoiceHotwordConfigStore:
    def __init__(self, support_directory: str | Path):
        self.support_directory = Path(support_directory).expanduser()
        self.path = self.support_directory / "voice-hotwords.json"

    def read(self) -> VoiceHotwordConfig:
        if not self.path.exists():
            return VoiceHotwordConfig(enabled=False, words=())
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise VoiceHotwordValidationError("voice hotword file is unreadable") from exc
        if not isinstance(payload, Mapping):
            raise VoiceHotwordValidationError("voice hotword file must contain an object")
        if payload.get("schemaVersion") != VOICE_HOTWORD_SCHEMA_VERSION:
            raise VoiceHotwordValidationError("voice hotword schema version is unsupported")
        enabled = payload.get("enabled")
        if not isinstance(enabled, bool):
            raise VoiceHotwordValidationError("voice hotword enabled must be a boolean")
        words = normalize_voice_hotwords(payload.get("words"), enabled=enabled)
        return VoiceHotwordConfig(enabled=enabled, words=words)

    def read_status(self) -> dict[str, object]:
        try:
            config = self.read()
        except VoiceHotwordValidationError as exc:
            return {
                "ok": False,
                "schemaVersion": VOICE_HOTWORD_SCHEMA_VERSION,
                "fileExists": self.path.exists(),
                "enabled": False,
                "words": [],
                "count": 0,
                "revision": "",
                "error": str(exc),
            }
        payload = config.payload()
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            "ok": True,
            **payload,
            "fileExists": self.path.exists(),
            "count": len(config.words),
            "revision": "sha256:" + hashlib.sha256(encoded).hexdigest()[:16],
        }

    def write(self, config: VoiceHotwordConfig) -> None:
        words = normalize_voice_hotwords(list(config.words), enabled=config.enabled)
        payload = VoiceHotwordConfig(enabled=config.enabled, words=words).payload()
        self.support_directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(
            prefix=".voice-hotwords-",
            suffix=".json",
            dir=self.support_directory,
        )
        temporary_path = Path(temporary)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, self.path)
            os.chmod(self.path, 0o600)
        finally:
            temporary_path.unlink(missing_ok=True)


def read_voice_preferences(support_directory: str | Path) -> dict[str, str]:
    support = Path(support_directory).expanduser()
    return {
        "provider": _read_voice_provider(support / "voice-provider.json"),
        "hotkey": _read_voice_hotkey(support / "voice-hotkey.json"),
    }


def write_voice_preferences_from_settings(
    support_directory: str | Path,
    settings: Mapping[str, object],
) -> None:
    voice = settings.get("voice") if isinstance(settings.get("voice"), Mapping) else {}
    provider = _text(voice.get("provider"))
    hotkey = _text(voice.get("hotkey"))
    if provider not in VOICE_PROVIDERS:
        raise VoiceHotwordValidationError("voice.provider is unsupported")
    if hotkey not in VOICE_HOTKEYS:
        raise VoiceHotwordValidationError("voice.hotkey is unsupported")
    support = Path(support_directory).expanduser()
    _write_private_json(
        support / "voice-provider.json",
        {"schemaVersion": VOICE_PROVIDER_SCHEMA_VERSION, "provider": provider},
    )
    _write_private_json(
        support / "voice-hotkey.json",
        {"schemaVersion": VOICE_HOTKEY_SCHEMA_VERSION, "choice": hotkey},
    )


def _write_private_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}-", suffix=".json", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(dict(payload), handle, ensure_ascii=False, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary_path, 0o600)
        os.replace(temporary_path, path)
        os.chmod(path, 0o600)
    finally:
        temporary_path.unlink(missing_ok=True)


def voice_hotword_config_from_settings(settings: Mapping[str, object]) -> VoiceHotwordConfig:
    voice = settings.get("voice") if isinstance(settings.get("voice"), Mapping) else {}
    enabled = voice.get("hotwordsEnabled")
    if not isinstance(enabled, bool):
        raise VoiceHotwordValidationError("voice.hotwordsEnabled must be a boolean")
    words = normalize_voice_hotwords(voice.get("hotwords"), enabled=enabled)
    return VoiceHotwordConfig(enabled=enabled, words=words)


def resolve_voice_support_directory(db_path: str | Path) -> Path:
    configured = str(os.environ.get("RAG_IME_APP_SUPPORT_DIR") or "").strip()
    if configured:
        return Path(configured).expanduser()
    database = Path(db_path).expanduser()
    if database.is_absolute():
        return database.parent
    return Path.home() / "Library" / "Application Support" / "RagIme"


def read_voice_control_status(
    support_directory: str | Path,
    *,
    binary_path: str | Path | None = None,
) -> dict[str, object]:
    support = Path(support_directory).expanduser()
    hotwords = VoiceHotwordConfigStore(support).read_status()
    agent = _read_agent_status(support / "voice-agent-status.json")
    preferences = read_voice_preferences(support)
    provider = preferences["provider"]
    deployed = _deployed_recognition_contract(
        _resolved_voice_binary(support, binary_path=binary_path),
        agent=agent,
    )
    telemetry = agent.get("telemetry") if isinstance(agent.get("telemetry"), Mapping) else {}
    loaded_enabled = agent.get("hotwordsEnabled") is True
    loaded_count = _nonnegative_int(agent.get("hotwordCount"))
    saved_enabled = hotwords.get("enabled") is True
    saved_count = _nonnegative_int(hotwords.get("count"))
    agent_running = _agent_is_running(agent)
    hotword_in_sync = bool(
        hotwords.get("ok") is True
        and (
            not agent_running
            or (loaded_enabled == saved_enabled and loaded_count == (saved_count if saved_enabled else 0))
        )
    )
    return {
        "schemaVersion": "rag-ime.voice-control-status.v1",
        "ok": hotwords.get("ok") is True,
        "provider": provider,
        "hotkey": preferences["hotkey"],
        "hotwords": {
            **hotwords,
            "agentRunning": agent_running,
            "agentLoadedEnabled": loaded_enabled,
            "agentLoadedCount": loaded_count,
            "inSync": hotword_in_sync,
            "applyState": (
                "loaded"
                if hotword_in_sync and agent_running
                else "next_session"
                if hotwords.get("ok") is True
                else "invalid"
            ),
        },
        "agent": {
            "available": bool(agent),
            "running": agent_running,
            "processId": _nonnegative_int(agent.get("processID")),
            "state": _text(agent.get("state")),
            "hotkeyMode": _text(agent.get("hotkeyMode")),
            "credentialsConfigured": agent.get("credentialsConfigured") is True,
            "microphoneAuthorization": _text(agent.get("microphoneAuthorization")),
            "accessibilityTrusted": agent.get("accessibilityTrusted") is True,
            "updatedAtMs": _nonnegative_int(agent.get("updatedAtMs")),
        },
        "recognition": {
            "deployed": deployed,
            "lastSession": {
                "finalReceived": telemetry.get("finalReceived") is True,
                "finalLatencyMs": _optional_nonnegative_int(telemetry.get("finalLatencyMs")),
                "partialRevisionCount": _nonnegative_int(telemetry.get("partialRevisionCount")),
                "droppedPcmFrameCount": _nonnegative_int(telemetry.get("droppedPCMFrameCount")),
            },
        },
    }


def _read_agent_status(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("schemaVersion") not in VOICE_AGENT_STATUS_SCHEMA_VERSIONS:
        return {}
    return payload


def _read_voice_provider(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "native_streaming"
    if not isinstance(payload, Mapping):
        return "native_streaming"
    provider = _text(payload.get("provider"))
    return provider if provider in VOICE_PROVIDERS else "native_streaming"


def _read_voice_hotkey(path: Path) -> str:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return "middle_mouse"
    if not isinstance(payload, Mapping):
        return "middle_mouse"
    hotkey = _text(payload.get("choice"))
    return hotkey if hotkey in VOICE_HOTKEYS else "middle_mouse"


def _resolved_voice_binary(
    support_directory: Path,
    *,
    binary_path: str | Path | None,
) -> Path | None:
    if binary_path is not None:
        return Path(binary_path).expanduser()
    configured = str(os.environ.get("RAG_IME_VOICE_BINARY") or "").strip()
    if configured:
        return Path(configured).expanduser()
    production_support = Path.home() / "Library" / "Application Support" / "RagIme"
    if support_directory.resolve() != production_support.resolve():
        return None
    return Path.home() / "Applications" / "RagImeVoice.app" / "Contents" / "MacOS" / "RagImeVoice"


def _deployed_recognition_contract(
    binary_path: Path | None,
    *,
    agent: Mapping[str, object],
) -> dict[str, object]:
    if binary_path is None or not binary_path.is_file():
        return {
            "binaryFound": False,
            "secondPass": False,
            "semanticSmoothing": False,
            "fullResultReplacement": False,
            "reportedByAgent": False,
            "state": "missing",
            "reason": "installed voice binary is missing",
        }
    try:
        binary = binary_path.read_bytes()
    except OSError:
        return {
            "binaryFound": False,
            "secondPass": False,
            "semanticSmoothing": False,
            "fullResultReplacement": False,
            "reportedByAgent": False,
            "state": "unreadable",
            "reason": "installed voice binary is unreadable",
        }
    reported = agent.get("recognition") if isinstance(agent.get("recognition"), Mapping) else {}
    marker = _voice_build_marker(binary_path)
    marker_capabilities = (
        marker.get("capabilities")
        if isinstance(marker.get("capabilities"), Mapping)
        else {}
    )
    reported_by_agent = bool(reported)
    second_pass = (
        reported.get("finalSecondPass") is True
        or marker_capabilities.get("finalSecondPass") is True
        or b"enable_nonstream" in binary
    )
    semantic_smoothing = (
        reported.get("semanticSmoothing") is True
        or marker_capabilities.get("semanticSmoothing") is True
        or b"semanticSmoothing" in binary
    )
    full_result_replacement = (
        reported.get("fullResultReplacement") is True
        or marker_capabilities.get("fullResultReplacement") is True
        or b"fullResultReplacement" in binary
    )
    all_capabilities = second_pass and semantic_smoothing and full_result_replacement
    if reported_by_agent:
        state = "ready" if all_capabilities else "unsupported"
        reason = "running voice agent reported its recognition contract"
    elif all_capabilities:
        state = "restart_required"
        reason = "installed voice binary supports final replacement but the running agent has not reported it"
    else:
        state = "outdated"
        reason = "installed voice binary does not contain the complete final-result contract"
    return {
        "binaryFound": True,
        "secondPass": second_pass,
        # Short Swift dictionary keys may be encoded as immediate values and do
        # not necessarily appear as byte strings in an optimized executable.
        # The native status contract supplies runtime truth; the long Codable
        # field names remain a build-time fallback before the agent restarts.
        "semanticSmoothing": semantic_smoothing,
        "fullResultReplacement": full_result_replacement,
        "reportedByAgent": reported_by_agent,
        "state": state,
        "reason": reason,
        "buildMarkerFound": bool(marker),
        "sourceCommit": _text(marker.get("gitCommit")),
        "sourceDirty": marker.get("gitDirty") is True,
        "updatedAtMs": int(binary_path.stat().st_mtime * 1000),
    }


def _voice_build_marker(binary_path: Path) -> dict[str, object]:
    marker_path = binary_path.parent.parent / "Resources" / "rag-ime-voice-build-marker.json"
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    if payload.get("schemaVersion") != VOICE_BUILD_MARKER_SCHEMA_VERSION:
        return {}
    return payload


def _agent_is_running(agent: Mapping[str, object]) -> bool:
    if agent.get("running") is not True:
        return False
    pid = _nonnegative_int(agent.get("processID"))
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    return True


def _text(value: object) -> str:
    return str(value or "").strip()


def _nonnegative_int(value: object) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _optional_nonnegative_int(value: object) -> int | None:
    if value is None:
        return None
    return _nonnegative_int(value)
