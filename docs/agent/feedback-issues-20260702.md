# RAG IME Feedback Issues - 2026-07-02

## 当前必须修复的问题

1. 候选像剪贴板：`recent_context` 被直接切成 `memory` 候选，导致刚输入的内容反复出现在候选栏。
2. RAG 候选不可用：Codex 历史导入后，候选里出现工具日志、patch、工作状态、安装脚本和调试流水账，而不是可上屏短语。
3. LLM 候选缺失或不明显：用户需要看到明确的 LLM 预测来源；模型失败时要有诊断，不能静默退回传统 Rime。
4. RAG/embedding 调用链不清：检索 query 不能只用当前刚输入的零散文本；应使用当前输入、上屏锚点、上下文窗口、项目标签和清洗后的语义 query。
5. 过期候选挡住输入：旧 AI 面板不能在 raw input 变化、空响应、英文/数字/URL/路径输入时继续吃掉数字键。
6. Demo 不可用：至少要做到真实输入时候选能辅助输出，候选应是“预测用户想表达什么”，而不是 `py 通过`、`installation yaml`、`你要自己调试` 这类碎片。

## 当前验收口径

- 输入“这个输入法还是一个输入法，内容得能够预测到用户想要输入什么”时，应出现预测型短候选，而不是安装/脚本/工具日志。
- 输入“RAG 到底怎么调用 embedding”时，应优先给出“embedding 检索应该用上下文窗口”“RAG 不应直接显示原文日志”“先清洗 query 再召回”等可上屏候选。
- 候选来源必须能区分 `model`、`rag`、`memory`、`rime`。
- 若 MLX 或 embedding 未启用，debug/doctor 必须明确显示，而不是让用户从坏候选里猜。
- 普通拼音、英文、数字、代码、路径输入必须保持可用。

## 2026-07-02 14:10 修复记录

- Codex 历史导入默认只保留 `role=user` 的真实用户输入；`assistant`、`event_msg`、工具输出、系统注入和 `MEMORY_SUMMARY` 不再进入输入法记忆候选池。
- 本地 SQLite 检索新增旧库兼容过滤；已经导入过的 `py 通过`、`git diff --check`、`installation.yaml`、`index.ts 先改成依赖 core`、`MEMORY_SUMMARY` 等残留即使仍在 DB 里，也不会进入候选。
- `SuggestionCompiler` 继续压缩 RAG 结果为可上屏短候选，并过滤“你参考/你看一下/打不了字/没想到/裸模型尺寸”等不适合输入法候选的聊天残句。
- 候选来源修正：`model` 来自 MLX，小模型候选横向；`rag` 来自 RAG/embedding/检索；`memory` 来自 curated/user-input/frequency 记忆。
- 空输入时预测面板改为 post-commit holdover：只有没有 Rime fallback 且距离上次更新不超过 `ragImePostCommitDisplayHoldoverDuration=0.9s` 才短暂保留，否则清空，避免一直吃掉数字键。
- sidecar 实测通过：`/api/rime-suggest` 返回 `modelLane.called=true`、`ragLane.called=true`，display candidates 同时包含 `rag`、`memory`、`model`，且 side candidates 的 `selectionAction=commit_side_candidate`。

## 2026-07-02 14:45 Wisdom-Weasel 对齐记录

- 重新对齐候选显示方式：参考 Wisdom-Weasel 的预测态，不再把 AI 候选当作常驻剪贴板面板；只有活动 composition 或活动 prediction session 且存在候选时才显示。
- sidecar 返回新增 `predictionFirst.policy.panelVisible / hideWhenEmpty / sessionBound`，给 macOS 前端一个明确契约：空候选、过期 post-commit、失焦、Esc、普通数字/英文输入都必须隐藏预测层。
- post-commit continuation 收敛为 0.85-0.9 秒 TTL：刚上屏后可以视觉连续地接上预测候选，超过窗口就清空，避免几秒后仍挡住输入。
- 模型 holdover 改成绑定输入状态：cache fingerprint 现在包含当前语义 query；用户从 `sj` 继续变成 `sja` 时不会复用旧模型候选，避免 LLM 横排看起来常驻。
- 继续拼音约束时不让 LLM 猜脏拼音：只把 1-4 位短拼音前缀作为约束加入语义 query，长 raw pinyin 仍交给 Rime/万象候选处理。
- `CandidatePool` 改为先保留 `rag`、`memory`、`model` 三条语义 lane 的首个候选，再按分数补齐，避免某一类候选把其他来源挤掉。
- SQLite 检索改为两阶段过滤：优先用原始 query 和拼音索引过滤，必要时才使用扩展 query 宽松召回，减少“刚开始没含义”的输入触发错误历史。

## 剩余风险

- `/Library/Input Methods/Squirrel.app` 仍有同 bundle id 的旧系统版 Squirrel；当前用户目录 `/Users/undo/Library/Input Methods/Squirrel.app` 已安装 patched app，但 macOS 可能因重复 app 加载旧版本。需要管理员权限运行 `scripts/replace_system_squirrel_app.sh` 或手动移除系统旧版。
- doctor 的模型专项 case 仍提示 “no MLX model predictions to validate”，但手动 `/api/rime-suggest` 已验证 650ms 内可返回 `sourceType=model`。后续应把 doctor 的模型专项 case 改成与真实 post-commit demo 一致。
