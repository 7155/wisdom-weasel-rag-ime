#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from rag_ime.mlx_bert import build_bert, replace_huggingface_key


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert a Hugging Face BERT embedding model to MLX")
    parser.add_argument("--model", default="BAAI/bge-base-zh-v1.5")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bits", type=int, choices=(0, 4, 6, 8), default=8)
    parser.add_argument("--dtype", choices=("fp16", "fp32"), default="fp16")
    parser.add_argument("--group-size", type=int, default=64)
    parser.add_argument(
        "--source-format",
        choices=("auto", "safetensors", "transformers"),
        default="auto",
        help="Use direct safetensors conversion to avoid requiring PyTorch",
    )
    args = parser.parse_args()

    import mlx.core as mx
    import mlx.nn as nn
    from transformers import AutoConfig, AutoTokenizer

    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    config = AutoConfig.from_pretrained(args.model, local_files_only=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    model = build_bert(config)
    weights, source_format, source_weights_path = _load_source_weights(
        args.model,
        source_format=str(args.source_format),
        mx=mx,
    )
    model.load_weights(list(weights.items()))
    if args.bits > 0:
        nn.quantize(model, bits=args.bits, group_size=args.group_size)
        mx.eval(model.parameters())
        model.save_weights(str(output / "weights.safetensors"))
    else:
        if args.dtype == "fp16":
            model.set_dtype(mx.float16)
            mx.eval(model.parameters())
        model.save_weights(str(output / "weights.npz"))
    config.save_pretrained(output)
    tokenizer.save_pretrained(output)
    (output / "mlx_embedding_config.json").write_text(
        json.dumps(
            {
                "bits": args.bits,
                "dtype": args.dtype,
                "groupSize": args.group_size,
                "pooling": "cls",
                "normalize": True,
                "sourceModel": str(args.model),
                "sourceFormat": source_format,
                "sourceWeightsSha256": (
                    _file_sha256(source_weights_path)
                    if source_weights_path is not None
                    else ""
                ),
                "sourceParameterCount": len(weights),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(output),
                "bits": args.bits,
                "groupSize": args.group_size,
                "sourceFormat": source_format,
                "sourceParameterCount": len(weights),
            },
            indent=2,
        )
    )
    return 0


def _load_source_weights(
    model: str,
    *,
    source_format: str,
    mx,
) -> tuple[dict[str, object], str, Path | None]:
    model_path = Path(model).expanduser()
    safetensors_path = model_path / "model.safetensors"
    direct = source_format == "safetensors" or (
        source_format == "auto" and safetensors_path.is_file()
    )
    if direct:
        if not safetensors_path.is_file():
            raise FileNotFoundError(
                f"direct conversion requires {safetensors_path}"
            )
        try:
            from safetensors import safe_open
        except ImportError as exc:
            raise RuntimeError(
                "direct conversion requires the safetensors package"
            ) from exc
        weights: dict[str, object] = {}
        with safe_open(safetensors_path, framework="np") as source:
            for key in source.keys():
                if not _is_huggingface_parameter_key(key):
                    continue
                weights[replace_huggingface_key(key)] = mx.array(
                    source.get_tensor(key)
                )
        if not weights:
            raise ValueError("source safetensors contains no BERT parameters")
        return weights, "safetensors", safetensors_path

    try:
        from transformers import AutoModel
    except ImportError as exc:
        raise RuntimeError("transformers conversion requires AutoModel") from exc
    source = AutoModel.from_pretrained(model, local_files_only=True)
    weights = {
        replace_huggingface_key(key): mx.array(value.detach().cpu().numpy())
        for key, value in source.state_dict().items()
        if _is_huggingface_parameter_key(key)
    }
    return weights, "transformers", None


def _is_huggingface_parameter_key(key: str) -> bool:
    return not key.endswith((".position_ids", ".token_type_ids"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
