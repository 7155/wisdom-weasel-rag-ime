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
| [#12](https://github.com/scukeqi/Wisdom-Weasel/issues/12) | 4B 模型实时解码、rerank 延迟约 200ms | 用 `predict-benchmark` / `eval-prediction` 固定延迟和质量门槛；Squirrel patch 已加 debounce；completion mode 可测试 base 模型前缀补全 | 已有 benchmark/eval 和 completion mode，待真模型评测 |
| [#11](https://github.com/scukeqi/Wisdom-Weasel/issues/11) | LLM 流式解码降低延迟 | IME 默认不能等待完整长输出；后续可把 provider 扩展为流式首候选更新；当前用短输出 + 超时 fail-open | 待 provider v2 |
| [#8](https://github.com/scukeqi/Wisdom-Weasel/issues/8) | Transformer 拼音输入法，上下文 + 拼音 beam search | 当前先做上下文短预测；Rime/Squirrel 负责 raw pinyin parsing，RAG/模型只看 commit preview 或 Rime candidates | 已规避 LLM 解脏拼音 |
| [#6](https://github.com/scukeqi/Wisdom-Weasel/issues/6) | 后台可执行文件、基础词库和本体自动更新 | RAG-IME 当前优先解决本地可运行；自动更新涉及签名、模型包和词库版本治理 | 暂不做 |
| [#5](https://github.com/scukeqi/Wisdom-Weasel/issues/5) | 收集原始拼音、上下文、最终选择文本用于微调 | 本项目默认本地保存 committed_text/recent_context/preedit/candidate_rank/provider_name；不默认上传 | 已以 local-first 方式覆盖 |
| [#4](https://github.com/scukeqi/Wisdom-Weasel/issues/4) | llama.cpp 后端支持约束解码和束搜索 | 当前已有 `/v1/completions` prefix baseline；后续仍要做原生 llama.cpp/MLX batch/constraint provider，复用 KV cache 并并行采样多候选 | 部分覆盖，原生 provider 待实现 |
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

1. 把 `PredictionProvider` 继续升级：可选 streaming 首候选、原生 llama.cpp/MLX KV cache/batch sampling。
2. 用 `predict-benchmark` 对 Qwen/llama.cpp/MLX endpoint 跑真模型，记录 p50/max latency 和候选命中。
3. 针对 Qwen 等模型继续压制 verbose 输出；当前支持 `RAG_IME_PREDICTOR_PROFILE=instant` / `RAG_IME_PREDICTOR_DISABLE_THINKING=1`，并在解析层继续清理 `<think>`/JSON/list 格式。
4. 将 history context 拆成 `typed_history`、`accepted_memory`、`active_document_tail` 三类，减少上下文噪声。
5. 做 Rime candidate reranker，而不是端到端拼音生成：输入 Rime candidates + RAG hits + active context，输出 side score/reorder 建议。
