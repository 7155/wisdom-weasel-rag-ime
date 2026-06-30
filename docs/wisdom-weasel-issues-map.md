# Wisdom-Weasel Open Issues Map

- 调研时间: 2026-06-30
- 来源: <https://github.com/scukeqi/Wisdom-Weasel/issues>
- 目的: 把 Wisdom-Weasel 尚未解决的问题转成 RAG-IME 的兼容性清单，能直接规避的先在本项目里落地。

## Issue 对照

| Issue | Wisdom-Weasel 诉求 | RAG-IME 对应策略 | 当前状态 |
| --- | --- | --- | --- |
| [#16](https://github.com/scukeqi/Wisdom-Weasel/issues/16) | 云端模型 thinking/base 模型配置不透明 | 默认不依赖云端；本地 OpenAI-compatible provider 只要求短候选，失败返回空候选 | 已规避云端默认依赖 |
| [#15](https://github.com/scukeqi/Wisdom-Weasel/issues/15) | 小白配置教程不足 | 保留 `README.md`、`docs/macos-frontend-adapter.md`、debug page 和 preview-json 验证命令 | 继续完善安装/配置文档 |
| [#13](https://github.com/scukeqi/Wisdom-Weasel/issues/13) | 将用户输入作为模型已有输出，然后继续生成 | 将最近 committed input 历史和显式 recentContext 合并，传给本地小模型预测 | 本轮已实现历史上下文预测 |
| [#12](https://github.com/scukeqi/Wisdom-Weasel/issues/12) | 4B 模型实时解码、rerank 延迟约 200ms | 先保留 OpenAI-compatible provider；后续 benchmark Qwen3/Qwen3.5 0.6B/1.7B/4B 和 rerank | 待性能评测 |
| [#11](https://github.com/scukeqi/Wisdom-Weasel/issues/11) | LLM 流式解码降低延迟 | IME 默认不能等待完整长输出；后续可把 provider 扩展为流式首候选更新 | 待 provider v2 |
| [#8](https://github.com/scukeqi/Wisdom-Weasel/issues/8) | Transformer 拼音输入法，上下文 + 拼音 beam search | 当前先做上下文短预测；真正拼音约束/beam search 应在 Rime/Squirrel 或 llama.cpp sampler 层做 | 部分覆盖上下文预测 |
| [#6](https://github.com/scukeqi/Wisdom-Weasel/issues/6) | 后台可执行文件、基础词库和本体自动更新 | RAG-IME 当前优先解决本地可运行；自动更新涉及签名、模型包和词库版本治理 | 暂不做 |
| [#5](https://github.com/scukeqi/Wisdom-Weasel/issues/5) | 收集原始拼音、上下文、最终选择文本用于微调 | 本项目默认本地保存 committed_text/recent_context/preedit/candidate_rank/provider_name；不默认上传 | 已以 local-first 方式覆盖 |
| [#4](https://github.com/scukeqi/Wisdom-Weasel/issues/4) | llama.cpp 后端支持约束解码和束搜索 | 后续将 OpenAI-compatible provider 升级为 llama.cpp batch/constraint provider；保留 RAG evidence source | 待实现 |
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
```

把 `RAG_IME_HISTORY_CONTEXT_EVENTS=0` 即可关闭历史输入上下文进入预测。

## 下一批可做

1. 读取 Wisdom-Weasel llama.cpp provider 的 batch sampling/KV cache 代码，做成本项目 `PredictionProvider` v2。
2. 增加本地模型 benchmark 脚本：p50/p95 首候选延迟、总候选延迟、候选命中率。
3. 加 `thinking`/verbose 输出抑制策略，避免 Qwen 等模型在 IME 场景输出解释文本。
4. 将 history context 拆成 `typed_history`、`accepted_memory`、`active_document_tail` 三类，减少上下文噪声。
