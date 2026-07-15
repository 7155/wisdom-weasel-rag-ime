from __future__ import annotations

from pathlib import Path
from typing import Any


def replace_huggingface_key(key: str) -> str:
    replacements = (
        (".layer.", ".layers."),
        (".self.key.", ".key_proj."),
        (".self.query.", ".query_proj."),
        (".self.value.", ".value_proj."),
        (".attention.output.dense.", ".attention.out_proj."),
        (".attention.output.LayerNorm.", ".ln1."),
        (".output.LayerNorm.", ".ln2."),
        (".intermediate.dense.", ".linear1."),
        (".output.dense.", ".linear2."),
        (".LayerNorm.", ".norm."),
        ("pooler.dense.", "pooler."),
    )
    for old, new in replacements:
        key = key.replace(old, new)
    return key


def build_bert(config: Any):
    try:
        import mlx.core as mx
        import mlx.nn as nn
    except ImportError as exc:
        raise RuntimeError("MLX BERT embedding requires the 'embedding-mlx' optional dependencies") from exc

    class EncoderLayer(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            dims = int(config.hidden_size)
            self.attention = nn.MultiHeadAttention(dims, int(config.num_attention_heads), bias=True)
            self.ln1 = nn.LayerNorm(dims, eps=float(config.layer_norm_eps))
            self.ln2 = nn.LayerNorm(dims, eps=float(config.layer_norm_eps))
            self.linear1 = nn.Linear(dims, int(config.intermediate_size))
            self.linear2 = nn.Linear(int(config.intermediate_size), dims)
            self.gelu = nn.GELU()

        def __call__(self, x, mask):
            attended = self.attention(x, x, x, mask)
            normalized = self.ln1(x + attended)
            return self.ln2(self.linear2(self.gelu(self.linear1(normalized))) + normalized)

    class Encoder(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.layers = [EncoderLayer() for _ in range(int(config.num_hidden_layers))]

        def __call__(self, x, mask):
            for layer in self.layers:
                x = layer(x, mask)
            return x

    class Embeddings(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            dims = int(config.hidden_size)
            self.word_embeddings = nn.Embedding(int(config.vocab_size), dims)
            self.token_type_embeddings = nn.Embedding(int(config.type_vocab_size), dims)
            self.position_embeddings = nn.Embedding(int(config.max_position_embeddings), dims)
            self.norm = nn.LayerNorm(dims, eps=float(config.layer_norm_eps))

        def __call__(self, input_ids, token_type_ids=None):
            if token_type_ids is None:
                token_type_ids = mx.zeros_like(input_ids)
            positions = mx.broadcast_to(mx.arange(input_ids.shape[1]), input_ids.shape)
            return self.norm(
                self.word_embeddings(input_ids)
                + self.position_embeddings(positions)
                + self.token_type_embeddings(token_type_ids)
            )

    class Bert(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.embeddings = Embeddings()
            self.encoder = Encoder()
            self.pooler = nn.Linear(int(config.hidden_size), int(config.hidden_size))

        def __call__(self, input_ids, token_type_ids=None, attention_mask=None):
            x = self.embeddings(input_ids, token_type_ids)
            mask = (
                mx.expand_dims(mx.log(attention_mask), (1, 2)).astype(x.dtype)
                if attention_mask is not None else None
            )
            hidden = self.encoder(x, mask)
            return hidden, mx.tanh(self.pooler(hidden[:, 0]))

    return Bert()


def load_mlx_bert(model_dir: str | Path, *, bits: int = 0, group_size: int = 64):
    try:
        import mlx.nn as nn
        from transformers import AutoConfig, AutoTokenizer
    except ImportError as exc:
        raise RuntimeError("MLX BERT embedding requires the 'embedding-mlx' optional dependencies") from exc
    root = Path(model_dir).expanduser()
    config = AutoConfig.from_pretrained(root, local_files_only=True)
    model = build_bert(config)
    if bits > 0:
        nn.quantize(model, bits=int(bits), group_size=int(group_size))
    weights = root / ("weights.safetensors" if bits > 0 else "weights.npz")
    if not weights.exists():
        raise FileNotFoundError(f"missing converted MLX BERT weights: {weights}")
    model.load_weights(str(weights))
    tokenizer = AutoTokenizer.from_pretrained(root, local_files_only=True)
    return model, tokenizer
