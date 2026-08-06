from __future__ import annotations

import unittest

from rag_ime.mlx_bert import replace_huggingface_key
from scripts.convert_bge_to_mlx import _is_huggingface_parameter_key


class MlxBertTests(unittest.TestCase):
    def test_huggingface_attention_and_mlp_keys_map_to_mlx_bert(self) -> None:
        self.assertEqual(
            replace_huggingface_key("encoder.layer.0.attention.self.query.weight"),
            "encoder.layers.0.attention.query_proj.weight",
        )
        self.assertEqual(
            replace_huggingface_key("encoder.layer.0.attention.output.LayerNorm.weight"),
            "encoder.layers.0.ln1.weight",
        )
        self.assertEqual(
            replace_huggingface_key("encoder.layer.0.output.dense.weight"),
            "encoder.layers.0.linear2.weight",
        )
        self.assertEqual(replace_huggingface_key("pooler.dense.bias"), "pooler.bias")

    def test_converter_filters_huggingface_runtime_buffers(self) -> None:
        self.assertFalse(
            _is_huggingface_parameter_key("embeddings.position_ids")
        )
        self.assertFalse(
            _is_huggingface_parameter_key("embeddings.token_type_ids")
        )
        self.assertTrue(
            _is_huggingface_parameter_key("embeddings.position_embeddings.weight")
        )


if __name__ == "__main__":
    unittest.main()
