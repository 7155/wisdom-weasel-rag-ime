#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path
from typing import Any


VISION_CONFIG_KEYS = (
    "vision_config",
    "image_token_id",
    "video_token_id",
    "vision_start_token_id",
    "vision_end_token_id",
)
COPY_FILES = (
    ".gitattributes",
    "README.md",
    "added_tokens.json",
    "chat_template.jinja",
    "configuration.json",
    "merges.txt",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive a text-only MLX-LM directory from a Qwen3.5 MLX-VLM directory."
    )
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--target-dir", required=True, type=Path)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    try:
        summary = derive_text_mlx_model(
            source_dir=args.source_dir,
            target_dir=args.target_dir,
            overwrite=bool(args.overwrite),
            dry_run=bool(args.dry_run),
        )
    except Exception as exc:
        print(json.dumps({"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def derive_text_mlx_model(
    *,
    source_dir: Path,
    target_dir: Path,
    overwrite: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    source_dir = source_dir.expanduser().resolve()
    target_dir = target_dir.expanduser().resolve()
    config_path = source_dir / "config.json"
    weights_path = source_dir / "model.safetensors"
    if not config_path.is_file():
        raise FileNotFoundError(f"source config missing: {config_path}")
    if not weights_path.is_file():
        raise FileNotFoundError(f"source weights missing: {weights_path}")

    config = json.loads(config_path.read_text(encoding="utf-8"))
    text_config = config.get("text_config") if isinstance(config.get("text_config"), dict) else None
    if not text_config:
        raise ValueError("source config has no text_config; refusing to derive text-only Qwen3.5 model")
    if not isinstance(config.get("vision_config"), dict):
        raise ValueError("source config has no vision_config; source already looks text-only")

    output_config = _text_only_config(config, source_dir)
    copied_files = [name for name in COPY_FILES if (source_dir / name).is_file()]
    summary: dict[str, Any] = {
        "ok": True,
        "sourceDir": str(source_dir),
        "targetDir": str(target_dir),
        "dryRun": dry_run,
        "sourceDiskBytes": weights_path.stat().st_size,
        "copiedFiles": copied_files,
        "config": _config_summary(output_config),
    }
    if dry_run:
        return summary

    if target_dir.exists():
        if not overwrite and any(target_dir.iterdir()):
            raise FileExistsError(f"target exists and is not empty: {target_dir}")
    target_dir.mkdir(parents=True, exist_ok=True)

    (target_dir / "config.json").write_text(
        json.dumps(output_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for name in copied_files:
        shutil.copy2(source_dir / name, target_dir / name)

    started = time.perf_counter()
    weight_count, text_weight_count = _write_text_only_weights(weights_path, target_dir / "model.safetensors")
    summary.update(
        {
            "weightCount": weight_count,
            "textWeightCount": text_weight_count,
            "targetDiskBytes": (target_dir / "model.safetensors").stat().st_size,
            "elapsedMs": int((time.perf_counter() - started) * 1000),
        }
    )
    return summary


def _text_only_config(config: dict[str, Any], source_dir: Path) -> dict[str, Any]:
    output = dict(config)
    for key in VISION_CONFIG_KEYS:
        output.pop(key, None)
    output["rag_ime_derived_text_only"] = True
    output["rag_ime_source_model"] = str(source_dir)
    return output


def _config_summary(config: dict[str, Any]) -> dict[str, Any]:
    text_config = config.get("text_config") if isinstance(config.get("text_config"), dict) else {}
    return {
        "modelType": config.get("model_type"),
        "textModelType": text_config.get("model_type"),
        "hasVisionConfig": isinstance(config.get("vision_config"), dict),
        "vocabSize": text_config.get("vocab_size") or config.get("vocab_size"),
        "hiddenSize": text_config.get("hidden_size") or config.get("hidden_size"),
        "numHiddenLayers": text_config.get("num_hidden_layers") or config.get("num_hidden_layers"),
        "quantization": config.get("quantization") or config.get("quantization_config") or {},
    }


def _write_text_only_weights(source_path: Path, target_path: Path) -> tuple[int, int]:
    try:
        import mlx.core as mx
    except ImportError as exc:  # pragma: no cover - depends on local MLX install
        raise RuntimeError("mlx is required for real weight derivation; run with the MLX Python environment") from exc

    weights = mx.load(str(source_path))
    text_weights = {key: value for key, value in weights.items() if key.startswith("language_model.")}
    if not text_weights:
        raise ValueError("no language_model.* weights found in source safetensors")
    mx.save_safetensors(
        str(target_path),
        text_weights,
        metadata={"format": "mlx", "rag_ime_text_only": "true"},
    )
    return len(weights), len(text_weights)


if __name__ == "__main__":
    raise SystemExit(main())
