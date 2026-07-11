#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    args = parser.parse_args()

    import mlx.core as mx
    import mlx.nn as nn
    from transformers import AutoConfig, AutoModel, AutoTokenizer

    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    source = AutoModel.from_pretrained(args.model, local_files_only=True)
    config = AutoConfig.from_pretrained(args.model, local_files_only=True)
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    model = build_bert(config)
    weights = {replace_huggingface_key(key): mx.array(value.detach().cpu().numpy()) for key, value in source.state_dict().items()}
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
        json.dumps({"bits": args.bits, "dtype": args.dtype, "groupSize": args.group_size, "pooling": "cls", "normalize": True}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({"output": str(output), "bits": args.bits, "groupSize": args.group_size}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
