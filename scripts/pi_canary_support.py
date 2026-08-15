from __future__ import annotations

import json
import os
import plistlib
import stat
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path


PRODUCT_ROOT = Path(__file__).resolve().parents[1]
OPENAI_CODEX_PROXY_ENV = frozenset(
    {
        "ALL_PROXY",
        "HTTPS_PROXY",
        "HTTP_PROXY",
        "NO_PROXY",
        "all_proxy",
        "https_proxy",
        "http_proxy",
        "no_proxy",
    }
)
_EXCLUDED_LAUNCH_ENV = {
    "RAG_IME_AGENT_GATEWAY_WEB_DIST",
    "RAG_IME_AGENT_TOOL_URL",
    "RAG_IME_APP_SUPPORT_DIR",
    "RAG_IME_DB_PATH",
    "RAG_IME_INSTALL_MARKER",
    "RAG_IME_ROOT",
    "RAG_IME_SOURCE_ROOT",
}


def launch_environment_variables(path: Path) -> dict[str, str]:
    payload = plistlib.loads(path.expanduser().read_bytes())
    raw = payload.get("EnvironmentVariables")
    if not isinstance(raw, dict):
        raise RuntimeError("Agent Gateway LaunchAgent has no EnvironmentVariables")
    return {str(key): str(value) for key, value in raw.items()}


def launch_environment(path: Path) -> dict[str, str]:
    return {
        key: value
        for key, value in launch_environment_variables(path).items()
        if key not in _EXCLUDED_LAUNCH_ENV
    }


def installed_agent_config_dir(launch_agent_plist: Path) -> Path:
    app_support = launch_environment_variables(launch_agent_plist).get(
        "RAG_IME_APP_SUPPORT_DIR", ""
    )
    path = Path(app_support).expanduser()
    if not app_support or not path.is_absolute():
        raise RuntimeError(
            "Agent Gateway LaunchAgent has no absolute RAG_IME_APP_SUPPORT_DIR"
        )
    return path / "Agent" / "config"


def stage_openai_codex_oauth(
    source_agent_dir: Path,
    target_agent_dir: Path,
) -> Path:
    """Stage only installed Codex OAuth into private, ephemeral canary state."""

    target = target_agent_dir / "auth.json"
    if target.resolve(strict=False).is_relative_to(PRODUCT_ROOT.resolve()):
        raise RuntimeError("OAuth acceptance state must stay outside the product repository")

    source = source_agent_dir / "auth.json"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(source, flags)
    except OSError as exc:
        raise RuntimeError("installed openai-codex OAuth credential is unavailable") from exc
    with os.fdopen(descriptor, encoding="utf-8") as handle:
        source_stat = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(source_stat.st_mode)
            or source_stat.st_uid != os.getuid()
            or stat.S_IMODE(source_stat.st_mode) & 0o077
        ):
            raise RuntimeError(
                "installed openai-codex OAuth credential must be a private owned file"
            )
        try:
            payload = json.load(handle)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("installed openai-codex OAuth credential is invalid") from exc

    credential = payload.get("openai-codex") if isinstance(payload, Mapping) else None
    if (
        not isinstance(credential, Mapping)
        or str(credential.get("type") or "") != "oauth"
        or not str(credential.get("access") or "")
        or not str(credential.get("refresh") or "")
    ):
        raise RuntimeError("installed openai-codex OAuth credential is incomplete")

    target_agent_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(target_agent_dir, 0o700)
    encoded = (
        json.dumps(
            {"openai-codex": dict(credential)},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    target_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    target_flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        target_descriptor = os.open(target, target_flags, 0o600)
    except OSError as exc:
        raise RuntimeError("isolated openai-codex OAuth staging failed") from exc
    try:
        with os.fdopen(target_descriptor, "w", encoding="utf-8") as handle:
            handle.write(encoded)
    except BaseException:
        target.unlink(missing_ok=True)
        raise
    return target


@contextmanager
def temporary_environment(values: Mapping[str, str]) -> Iterator[None]:
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
