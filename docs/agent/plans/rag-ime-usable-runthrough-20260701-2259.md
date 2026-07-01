# RAG-IME 真实可用跑通 Goal
- 时间: 20260701-2259
- 触发词: goal
- 上下文: 当前目标从原型/调研切到 macOS 系统输入法真实可用跑通。用户要求 patched Squirrel/Rime、MLX 本地模型、RAG/记忆和数字键选择形成完整闭环。

## 目标
- 在 macOS 系统输入法中使用 patched Squirrel/Rime，默认简体输入。
- 真实候选面板能同时显示 Rime 候选、RAG/记忆候选、LLM 本地模型候选。
- 1-9/0 数字键能按显示候选正确选择并提交。
- sidecar、MLX 本地模型、Rime 配置、LaunchAgent、debug/doctor gate 都能重复启动和验证。
- 8 个候选位优先给 MLX/RAG，Rime 只作为 fallback；当 MLX/RAG 不可用、超时或没有稳定语义信号时，Rime 候选立即兜底。
- 模型候选长期优化方向必须参考 Wisdom-Weasel：logits/top-k、KV cache、sequence fork / batch candidates，而不是长期依赖 JSON 文本生成。
- raw 拼音/误拼输入不能直接交给 LLM 猜中文；必须先通过 Rime 候选、拼音切分或 logits processor 约束得到可解释的中文候选，再让 LLM/RAG 做排序、续写和记忆增强。

## 计划步骤
1. 固定当前候选合并策略：`MLX 模型候选 -> RAG/记忆候选 -> Rime fallback`。
2. 放宽 side slot 上限到 8，使默认 8 个候选位都可被 MLX/RAG 占用。
3. 修改触发逻辑：Rime 候选占满页面时仍允许 side lane 刷新，因为 Rime 现在是 fallback 而不是主占位。
4. 测试候选选择 JSON：每个 display candidate 都带 `selectionKey`、`selectionRank`、`selectionAction`、`sourceType` 和插入文本。
5. 跑 sidecar / predictor / MLX 聚焦测试，确保失败时仍返回 Rime。
6. 用真实 LaunchAgent 重启 sidecar 和 MLX predictor，执行 doctor gate 和手工 `/rime-suggest` 验证。
7. 对 3 个已下载 MLX safetensors 建模型目录并做 TTFC / 多候选质量对比。
8. 实现或记录下一步 MLX logits/top-k 原生候选接口，目标是替代 JSON completion。
9. 设计 raw 拼音处理边界：Rime 有候选时用候选作为语义输入；Rime 没候选时跳过 side lane 或进入拼音约束解码，不让模型自由猜音码。

## 进度 (TODO)
- [x] 确认 Wisdom-Weasel 的 `GenerateCandidatesBatch` 使用 system KV cache、prefill 一次、复制序列、并行采样多个候选。
- [x] 确认 Wisdom-Weasel HF backend 使用 beam search / logits processor 做拼音约束。
- [x] 更新 sidecar 合并策略和默认 side slot。
- [x] 更新测试和文档里的旧 `1-5 Rime, 6 model, 7-8 RAG` 口径。
- [x] 运行聚焦测试、`py_compile`、`git diff --check`。
- [x] 重启 LaunchAgent 并跑真实 doctor / sidecar payload。
- [ ] 完成 3 个 MLX 模型对比。
- [ ] Git 同步。

## 数据 / 运行配置
- 输入法前端: patched Squirrel/Rime。
- sidecar: `http://127.0.0.1:8766`。
- MLX predictor: `http://127.0.0.1:8767`。
- 当前可加载模型: `/Volumes/undo 4t/models/mlx-community-Qwen3.5-0.8B-4bit`。
- 已下载候选模型文件: `/Volumes/undo 4t/MyGlobalDownloads/model.safetensors`、`model (1).safetensors`、`model (2).safetensors`。
- 默认候选数: `maxVisibleCandidates=8`，`maxSideCandidates=8`。

## 验收 / 退出条件
- 系统输入法里选择 Squirrel/Rime 后，真实输入窗口可以输入简体。
- 稳定 Rime candidate 或 commit preview 触发后，候选列表优先展示 MLX/RAG，Rime 只在空位或失败时显示。
- 数字键选择 side candidate 会提交 `insertText`，选择 Rime candidate 仍走 Rime 原生选择。
- `scripts/doctor_squirrel_integration.sh` 通过。
- 聚焦测试通过，且 `git diff --check` 无空白错误。
- 文档记录当前边界、难点和下一步 logits/top-k/KV cache 路线。

## 风险 / 开放问题
- MLX-LM 当前 JSON completion 多候选速度慢，stream-first 快但通常只有 1 个候选。
- 需要确认 MLX-LM 能否低成本暴露下一 token logits；如果不能，下一步应转 llama.cpp/Metal 或更底层 MLX forward。
- Rime fallback 后移会改变传统输入法肌肉记忆，需要真实连续输入测试确认是否可接受。
- 3 个 safetensors 需要逐一识别 config/tokenizer，不能只按文件名假设模型。
- `asdioj` 这类 raw key sequence 可能是误拼、双拼或英文缩写；没有 Rime 候选或拼音约束时，模型自由生成会产生噪声，必须 fail closed。

## 参考
- `/Volumes/undo 4t/git/learnA/Wisdom-Weasel/WeaselServer/LlamaCppProvider.cpp`
- `/Volumes/undo 4t/git/learnA/Wisdom-Weasel/hf_backend/app/inference_service.py`
- `/Volumes/undo 4t/git/learnA/Wisdom-Weasel/hf_backend/app/pinyin_constraint.py`
