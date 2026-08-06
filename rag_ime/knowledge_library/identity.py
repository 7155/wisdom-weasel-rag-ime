from __future__ import annotations

import hashlib
import json
from pathlib import Path


def normalized_knowledge_root(root: Path) -> str:
    return str(Path(root).expanduser().resolve(strict=False))


def knowledge_worker_fingerprint(
    root: Path,
    *,
    mineru_enabled: bool,
    mineru_port: int,
    idle_seconds: float,
    python_executable: str,
    python_version: str,
    embedding_provider: str,
    embedding_model: str,
    dense_backend: str,
    embedding_profile_sha256: str = "",
    reranker_provider: str = "none",
    reranker_model_path: str = "",
    reranker_model_revision: str = "",
    reranker_profile_sha256: str = "",
) -> str:
    payload = {
        "idleSeconds": float(idle_seconds),
        "mineruEnabled": bool(mineru_enabled),
        "mineruPort": int(mineru_port),
        "root": normalized_knowledge_root(root),
        # A virtualenv's python is normally a symlink to the base interpreter.
        # Preserve that configured path so two runtimes with different optional
        # dependencies cannot be mistaken for the same worker identity.
        "pythonExecutable": str(Path(python_executable).expanduser().absolute()),
        "pythonVersion": str(python_version),
        "embeddingProvider": str(embedding_provider).strip().lower(),
        "embeddingModel": str(embedding_model).strip(),
        "embeddingProfileSha256": str(embedding_profile_sha256).strip().lower(),
        "denseBackend": str(dense_backend).strip().lower(),
        "rerankerProvider": str(reranker_provider).strip().lower(),
        "rerankerModelPath": str(reranker_model_path).strip(),
        "rerankerModelRevision": str(reranker_model_revision).strip(),
        "rerankerProfileSha256": str(reranker_profile_sha256).strip().lower(),
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
