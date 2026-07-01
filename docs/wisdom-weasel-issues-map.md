# Wisdom-Weasel Open Issues Map

- 调研时间: 2026-07-01
- 来源: <https://github.com/scukeqi/Wisdom-Weasel/issues>
- 目的: 把 Wisdom-Weasel 尚未解决的问题转成 RAG-IME 的兼容性清单，能直接规避的先在本项目里落地。

## 本轮源码精读结论

Checked source snapshots:

- `scukeqi/Wisdom-Weasel@64ba2fd`
- `rime/weasel@93eec2d`

Wisdom-Weasel 的 LLM 输入法路径不是“每个按键都问大模型”：

```text
Rime commit
  -> ContextHistory.AddText()
  -> meaningful commit enters LLM prediction mode
  -> background PredictCandidates(context, current_input)
  -> request sequence drops stale result
  -> append LLM candidates after Rime candidates
  -> numeric selection branches: Rime index vs LLM side index
```

对 RAG-IME 的直接要求：

- 只在有稳定语义信号时跑模型/RAG，不能用 raw dirty pinyin 当唯一输入。
- Rime/Squirrel 候选优先，side candidates 只填剩余显示槽。
- 选择 side candidate 时要清 composition、提交文本、写回本地记忆反馈。
- 本地模型 provider 需要有 chat 和 base-prefix completion 两条路；chat 适合 Qwen instruct，completion 更接近 Wisdom-Weasel base 模型补全路径。
- 真正的低延迟下一步不是换 prompt，而是原生 llama.cpp/MLX provider：稳定 prompt KV cache + multi-candidate batch sampling。

## Issue 对照

| Issue | Wisdom-Weasel 诉求 | RAG-IME 对应策略 | 当前状态 |
| --- | --- | --- | --- |
| [#16](https://github.com/scukeqi/Wisdom-Weasel/issues/16) | 云端模型 thinking/base 模型配置不透明 | 默认不依赖云端；本地 OpenAI-compatible provider 只要求短候选，失败返回空候选；支持 `RAG_IME_PREDICTOR_PROFILE=instant|completion-instant`、`RAG_IME_PREDICTOR_DISABLE_THINKING=1`、`RAG_IME_PREDICTOR_EXTRA_BODY_JSON` / `RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON` | 已覆盖 chat/base 两种 OpenAI-compatible 入口 |
| [#15](https://github.com/scukeqi/Wisdom-Weasel/issues/15) | 小白配置教程不足 | 保留 `README.md`、`docs/macos-frontend-adapter.md`、debug page 和 preview-json 验证命令 | 继续完善安装/配置文档 |
| [#13](https://github.com/scukeqi/Wisdom-Weasel/issues/13) | 将用户输入作为模型已有输出，然后继续生成 | 将最近 committed input 历史和显式 recentContext 合并，传给本地小模型预测 | 本轮已实现历史上下文预测 |
| [#12](https://github.com/scukeqi/Wisdom-Weasel/issues/12) | 4B 模型实时解码、rerank 延迟约 200ms | 用 `predict-benchmark` / `predictor-ttft` / `eval-prediction` 固定完整响应、首 chunk、质量三类门槛；Squirrel patch 已加 debounce；当前 Mac 路线优先 MLX text-only 0.8B logits top-k，后续再做 native KV/batch provider | 已跑通 MLX `next-token-logits` 多候选，doctor 可强制验证；native KV/batch provider 待实现 |
| [#11](https://github.com/scukeqi/Wisdom-Weasel/issues/11) | LLM 流式解码降低延迟 | 已加 `predictor-ttft` 测首 chunk；但 Wisdom-Weasel 真正快点不是 streaming，而是 native llama.cpp system prompt KV cache + 多序列 batch sampling；当前 MLX 服务先用 logits top-k 直接拿多个短候选，避免 JSON 多 token 生成 | MLX logits/top-k 已接入并纳入 strict doctor；真实 KV cache 命中生成仍待做 |
| [#8](https://github.com/scukeqi/Wisdom-Weasel/issues/8) | Transformer 拼音输入法，上下文 + 拼音 beam search | 当前先做上下文短预测；Rime/Squirrel 负责 raw pinyin parsing；RAG/模型优先看 commit preview 或 Rime candidates；无 Rime 候选但有最近已提交中文时，用 committedContext 继续预测并让 Squirrel 短暂 holdover，不让 LLM 直接解 `asdioj` | 已规避 LLM 解脏拼音，并纳入 strict doctor；拼音约束 logits / beam search 待做 |
| [#6](https://github.com/scukeqi/Wisdom-Weasel/issues/6) | 后台可执行文件、基础词库和本体自动更新 | RAG-IME 当前优先解决本地可运行；自动更新涉及签名、模型包和词库版本治理 | 暂不做 |
| [#5](https://github.com/scukeqi/Wisdom-Weasel/issues/5) | 收集原始拼音、上下文、最终选择文本用于微调 | 本项目默认本地保存 committed_text/recent_context/preedit/candidate_rank/provider_name；不默认上传 | 已以 local-first 方式覆盖 |
| [#4](https://github.com/scukeqi/Wisdom-Weasel/issues/4) | llama.cpp 后端支持约束解码和束搜索 | 当前已有 `/v1/completions` prefix baseline；MLX 侧已先实现 next-token logits top-k，多候选来自一次 logits 排序而不是让模型写 JSON；后续仍要做原生 llama.cpp/MLX batch/constraint provider，复用 KV cache 并并行采样多候选 | 部分覆盖，约束解码/beam/native provider 待实现 |
| [#2](https://github.com/scukeqi/Wisdom-Weasel/issues/2) | Linux 支持 | 当前目标是 macOS InputMethodKit；Linux 可参考 fcitx5 adapter 作为下一平台 | 暂不做 |

## 本轮加入 Goal 的内容

新增长期要求：

```text
RAG-IME 不只参考 Wisdom-Weasel 的已实现功能，也要把 Wisdom-Weasel open issues 作为问题清单：
优先解决上下文预测、本地输入数据闭环、配置可调试性和本地模型延迟；
暂缓自动更新、Linux adapter 和完整 llama.cpp 约束解码，等 macOS MVP 稳定后进入下一阶段。
```

## 已落地的 #13 / #5 路径

```text
commit text
  -> LocalSqliteCoreClient.input_events
  -> recent_input_context(project, limit, max_chars)
  -> build_prediction_context(explicit recentContext + history)
  -> local OpenAI-compatible predictor
  -> modelPredictions top row
```

环境变量:

```text
RAG_IME_HISTORY_CONTEXT_EVENTS=6
RAG_IME_HISTORY_CONTEXT_CHARS=420
RAG_IME_PREDICTOR_PROFILE=instant
```

把 `RAG_IME_HISTORY_CONTEXT_EVENTS=0` 即可关闭历史输入上下文进入预测。
把 `RAG_IME_PREDICTOR_PROFILE=completion-instant` 即可让 OpenAI-compatible provider 调 `/v1/completions`，用 `history + current_input` 前缀补全并通过 `n` 请求多个候选。

## 下一批可做

1. 把 `PredictionProvider` 继续升级：MLX text-only 0.8B 的 `next-token-logits` 已跑通；下一步做真实 prompt KV cache 命中生成、原生 llama.cpp/Metal KV cache/batch sampling，以及约束候选过滤。
2. 用 `predict-benchmark` / `predictor-ttft` 对 Qwen/Ollama MLX/MLX-LM/llama.cpp endpoint 跑真模型，记录 p50/max latency、首 chunk、候选命中和 over-budget 次数。
3. 针对 Qwen 等模型继续压制 verbose 输出；当前支持 `RAG_IME_PREDICTOR_PROFILE=instant` / `RAG_IME_PREDICTOR_DISABLE_THINKING=1`，并在解析层继续清理 `<think>`/JSON/list 格式。
4. 将 history context 拆成 `typed_history`、`accepted_memory`、`active_document_tail` 三类，减少上下文噪声。
5. 做 Rime candidate reranker，而不是端到端拼音生成：输入 Rime candidates + RAG hits + active context，输出 side score/reorder 建议。
