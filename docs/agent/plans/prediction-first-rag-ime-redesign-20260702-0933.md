# Prediction-first RAG IME 方案重审
- 时间: 20260702-0933
- 触发词: Goal / 方案重审
- 上下文: 当前 patched Squirrel/Rime 版本虽然 sidecar、doctor、模型服务可以启动，但用户在 Codex App 等真实场景里无法稳定输入拼音，已经不满足输入法 MVP 的最低要求。后续不再把“补完当前补丁”当主线，而是重新确定交互范式和工程边界。

## 目标
- 重新设计并实现 Prediction-first RAG IME 的 MVP：拼音选首词，LLM/RAG 预测后文，用户继续输入拼音约束预测，再选择、再预测。
- 硬约束: 普通拼音输入、英文/代码输入必须永远可用；AI 候选只能增强输入，不能抢断、覆盖或阻塞基础输入。
- 项目定位: 不是“传统输入法 + AI 挂件”，而是“预测优先的个人记忆输入法”。

## 方案对照

### A. Wisdom-Weasel / LLM 输入法路线
- 优点:
  - 保留 Rime/Weasel 原生输入链路，LLM 候选追加到 Rime 候选后，降低破坏基础输入的概率。
  - 有上下文历史、记忆压缩、llama.cpp 本地后端、HF 拼音约束后端。
  - llama.cpp 后端已有 system prompt KV cache、并行候选生成、耗时日志等低延迟意识。
  - HF 后端用 `LogitsProcessor` 做拼音约束，说明“拼音约束生成”是可行方向。
- 问题:
  - 主体仍是 Rime 候选 + LLM 追加候选，不是预测优先范式。
  - 当前源码逻辑里，LLM 模式下用户继续输入字母会退出 LLM 模式；这和我们想要的“继续输入拼音约束预测”相反。
  - RAG/个人记忆还没有变成候选生成器，更多只是上下文历史和摘要。

### B. 用户提出的 Prediction-first RAG IME
- 优点:
  - 交互范式清晰: 首词锚定 -> 后文预测 -> 拼音纠偏 -> 再预测。
  - RAG 的位置正确: 不是把大段检索结果塞给 Agent，而是压缩成用户可选择的短候选，并可展开证据。
  - 候选池思想正确: 每次按键只做本地过滤，不每键调用模型，延迟和稳定性都更可控。
  - 面试亮点强: 把 RAG 从“替用户找上下文”变成“输入过程中让用户校准上下文”。
- 风险:
  - 需要自定义状态机和候选生命周期；直接 patch Squirrel 很容易破坏系统输入事件。
  - 段落级候选不能塞进小候选框，需要短候选、短句、展开面板分层。
  - 模型不能直接处理乱拼音/缩写拼音，必须先有 Rime/拼音索引/约束解码兜底。

### C. 当前 patched Squirrel + sidecar 路线
- 已验证:
  - sidecar、LaunchAgent、MLX provider、doctor gate、候选合并测试可以跑。
  - 能把 Rime、LLM、RAG 三类候选拼到一个候选列表。
- 失败点:
  - 真实输入体验失败：Codex App 等场景里用户无法稳定输入拼音，甚至切回豆包才能继续打字。
  - AI overlay 介入活跃拼音时，会出现拼音和预测不是同一条语义路径的问题。
  - doctor 绿灯只证明服务链路存在，不证明系统输入法可用。
- 结论:
  - 当前代码先冻结为实验验证材料，不作为下一阶段主路线。

## 新状态机
1. `RAW_INPUT`
   - 空闲或英文/代码直通。
   - 任何 AI 组件不得拦截普通字符输入。
2. `ANCHOR_PINYIN`
   - 用户输入首词拼音。
   - 传统拼音/Rime/万象候选优先，AI 只后台预取，不抢 1 号候选。
3. `PREDICTIVE_CONTINUATION`
   - 首词或短语上屏后进入预测接龙。
   - 候选主要来自 CandidatePool: RAG/记忆、LLM、最近短语、项目词汇。
4. `PREFIX_CONSTRAINED_PREDICTION`
   - 用户继续输入拼音不是退出 AI，而是用拼音过滤/约束 CandidatePool。
   - 不匹配拼音约束的预测候选降权或隐藏；普通拼音候选作为兜底。
5. `EVIDENCE_EXPANDED`
   - 用户用 Ctrl+数字或触发键查看 RAG 来源、历史片段、时间和文件。
   - 不占用常规候选框面积。

## 20260702 补充收敛: Wisdom-Weasel 双通道候选
- 采纳判断: 另一个 AI 提出的“双通道候选”是有价值的，应作为当前最优实现策略。
- 关键修正: 不在预测态强行截获用户继续输入的字母键。用户继续打拼音时，仍让 Rime 正常进入 composition；PredictionManager 只读取当前 composition/prefix，用它过滤 CandidatePool，并把匹配的 LLM/RAG/记忆候选插到 Rime 候选前面。
- 原因:
  - 最大限度保留 Rime/Wisdom-Weasel 已验证的输入链路。
  - 避免自己实现拼音编辑、按键回放、输入焦点和 composition 生命周期。
  - 避免再次出现基础拼音输入被 AI overlay 破坏的问题。
- 两个候选通道:
  1. `PostCommitPredictionPanel`: 上屏后 80-150ms 内出现预测面板，视觉上接在原候选框位置，但生命周期独立于 Rime composition。
  2. `PrefixConstrainedComposition`: 用户继续输入拼音后，Rime 正常产生 composition；预测候选根据拼音 prefix 过滤后插到 Rime 候选前面，普通 Rime 候选兜底。
- Wisdom-Weasel 当前反例: 现有逻辑里，LLM 模式下输入字母会退出 LLM 预测模式；新方案要把这条分支改成“进入 prefix-constrained composing”，而不是退出预测。
- 产品一句话: 首词靠拼音，后文靠预测；预测不准，继续拼音约束；RAG/记忆候选在预测态优先于传统词库。

## 候选原则
- 首词阶段: 传统拼音候选 > 用户词频/词库 > AI 预取。
- 预测阶段: RAG/记忆候选 > LLM 续写候选 > 用户短语候选 > 拼音兜底。
- 拼音约束阶段: 拼音匹配变成硬约束或高权重约束。
- 候选单位: 2 到 20 个字的可输入片段，不能直接展示单 token softmax 结果。
- 段落级内容: 只显示入口，不直接塞进候选栏。
- 英文/代码: 必须有 raw candidate / direct pass-through，适配 vibe coding 场景。

## 技术路线
1. 先写交互状态机和候选池核心，独立于 macOS 系统输入法验证。
2. 复用 Wisdom-Weasel 的可取经验:
   - commit 后触发预测；
   - 历史上下文进入预测；
   - system prompt / prefix cache；
   - 多候选并行生成；
   - 拼音约束解码；
   - 异步请求序号丢弃旧结果。
3. 修正 Wisdom-Weasel 的关键不足:
   - 用户继续输入字母时不退出预测，而进入拼音约束预测。
   - LLM/RAG 候选不只是追加到 Rime 后面，而是在预测态成为主候选。
4. RAG/记忆作为候选生成器:
   - 检索本地记忆、历史输入、项目文档；
   - 压缩为短候选、短句候选、证据卡；
   - 记录用户选择作为后续排序信号。
5. macOS 前端 adapter 最后选型:
   - 先调研现有 macOS 输入法框架和 Wisdom-Weasel 可迁移做法；
   - 不再直接把 patched Squirrel 当唯一主线；
   - 真实 App 连续输入通过后再接 LLM/RAG。

## MVP 开发顺序
1. `v0` mock 状态机:
   - 用固定预测候选验证 `Anchor -> Predict -> Constrain`。
   - 必须证明普通拼音、英文/代码输入不会被预测态破坏。
2. `v1` Prefix constrained candidate injection:
   - 用户继续输入拼音时，Rime 正常 composition。
   - 预测候选按拼音过滤后插到 Rime 候选前，Rime 候选保留兜底。
3. `v2` Post-commit prediction panel:
   - 上屏后显示预测候选，解决“候选框消失后没有接龙”的体验。
   - 面板生命周期和 Rime 候选框分离，只追随光标位置。
4. `v3` 本地短语记忆和拼音索引:
   - 记录上屏文本、短语、拼音、首字母、应用来源、最近时间、接受率。
   - 先用快速记忆层提供 30-80ms 候选。
5. `v4` 接 Qwen/MLX 小模型:
   - 只做短句续写、候选生成、候选改写、RAG 材料压缩。
   - 不让模型承担原始拼音转汉字职责。
6. `v5` 接本地 RAG:
   - SQLite、FTS5/BM25、向量索引、RAGRetriever、SuggestionCompiler。
   - 支持 Ctrl+数字查看证据，Alt+Enter 展开长段落。
7. `v6` 个性化排序:
   - 接受候选加权，忽略候选轻微降权，继续拼音纠偏作为训练信号。
   - 当前应用/项目权重和最近使用权重进入排序。
8. `v7` 管理面板 / 可观测面板:
   - 参考 OpenLess 的 Tauri/Rust + React 管理窗口形态，但不提前打断输入法主线。
   - 面板至少展示输入历史、候选来源、RAG 证据、模型联想耗时、候选接受/拒绝、万象/Rime 兜底命中、词典/热词和本地模型状态。
   - 目标是让用户清楚看到“输入过什么、系统联想过什么、哪些记忆/RAG 被召回、为什么排序靠前”。

## 必须避免
- 不把 Qwen softmax top token 直接显示为候选；候选必须是可插入短语或短句。
- 不把 RAG 原文段落直接塞进候选栏；先经 SuggestionCompiler 压缩成短候选。
- 不把 OpenAI/API 作为主产品路线；云端只能做效果对照和 benchmark。
- 不让 AI 候选覆盖首词拼音候选；首词阶段 Rime/万象仍然优先。
- 不让候选频繁跳动；候选出现后至少冻结约 300ms，避免用户按数字时错选。

## 数据 / 运行配置
- 本地模型: 优先 MLX `Qwen/Qwen3.5-0.8B` 文本模型，non-thinking/streaming，常驻进程。
- RAG/记忆: 使用本地 SQLite/FTS/vector core；不上传云端。
- 拼音能力: 首词和兜底使用万象词库/Rime 方案；模型只做后文候选、候选改写、拼音约束生成，不负责原始拼音转汉字。
- 调试界面: 可以保留 web/debug UI，但它不是输入法本体，只用于查看状态机、候选来源、耗时和证据。

## 当前 Goal
- 持续迭代实现 Prediction-first RAG IME。
- 词库: 使用万象作为首词拼音锚定和兜底。
- 主线: Wisdom-Weasel/Rime 负责基础输入链路，Prediction-first 引擎负责上屏后的 LLM/RAG/记忆预测接龙。
- 验收底线: 普通拼音、英文、代码、路径和命令输入稳定可用，AI 不抢断基础输入。

## 20260702 实现进展
- 已新增 `rag_ime/prediction_first.py`，把 `raw_input / anchor_composing / post_commit_predicting / prefix_constrained_composing` 状态和 CandidatePool 合并逻辑独立出来。
- 已在 sidecar 中加入显式开关 `predictionFirstMerge`；默认保持旧合并路径，开启后才使用 Prediction-first 合并。
- 已验证 prefix constrained 场景: 用户继续输入 `sj` 时，匹配拼音的 RAG/LLM 候选排到万象/Rime 候选前，万象候选仍保留兜底。
- 已验证 post-commit 场景: 上屏后用 `commitTextPreview + forceSideCandidates` 触发 `post_commit_predicting`，RAG/模型以刚上屏文本作为预测锚点。
- debug 页面已加入 Prediction-first 开关；开启后接受候选会走 `/api/rime-select` 记录选择，并立即触发下一轮 post-commit 预测。
- 已新增零依赖 `pinyin_index`，`SuggestionCompiler` 会给本地记忆候选自动补 `initials / pinyin_prefixes`；用户继续输入拼音时，CandidatePool 可以直接用这些 metadata 过滤历史短语候选。
- 已验证本地短语记忆路径: SQLite 里记录的“设计一个候选展示方式”无需手写 metadata，也能在用户输入 `sj` 时排到万象/Rime 兜底候选前。
- 已把拼音索引写入 SQLite/FTS5 文档；用户输入 `sj` 时，SQLite 可以直接召回历史短语，而不是等 RAG 候选出来后再过滤。
- 频率排序已有基础:
  - 参考 Rime/librime 用户词典的公开实现：候选上屏后更新 userdb entry 的 `commits`，并结合 tick/衰减值计算候选权重。
  - 当前本地 SQLite 先实现两个稳定信号：`accepted_count` 表示用户主动接受该候选；同一 `committed_text` 反复上屏会增量写入 `phrase_stats.input_frequency`，查询时直接 join 进入排序分数，避免输入过程中反复全表聚合。
  - 已加入 Rime 式时间衰减的本地版本：`input_frequency` 会按 `phrase_last_seen_ms` 衰减，另有 `recent_boost` 让近期表达自然上浮，避免旧高频短语永久霸榜。
  - delete/hide/restore 会刷新对应 `phrase_stats`，被隐藏的输入不继续贡献词频。
  - `SuggestionCompiler` 会把 `state.input_frequency / project_input_frequency / effective_frequency_scope / phrase_age_days / frequency_boost / recent_boost / accepted_count / pinned / downranked` 透传到候选 metadata，便于 debug 页面和后续管理面板解释“为什么这个候选靠前”。
  - 已增加项目维度词频：`phrase_project_stats` 记录 `(committed_text, project)` 频次；当前项目内事件优先使用项目词频，避免另一个项目里的同名命令、路径、代码短语污染本项目排序。
  - 应用维度词频暂缓到 macOS adapter 能稳定提供前台 bundle id 后接入；目标是让 Codex/IDE/浏览器里的命令、路径和英文标识符只在对应应用里强升权。
- Python 使用边界:
  - Python 适合作为常驻 sidecar，负责 SQLite/RAG、候选排序、MLX 调用、debug server 和管理面板 API。
  - Python 不适合作为 macOS 前台输入法事件链和候选框渲染层；按键、composition、候选窗口应使用原生 Swift/ObjC/Rime 路线，避免阻塞基础输入。
- 当前仍未完成真实 macOS adapter 验收；debug 页面只用于观察候选来源、mode、prefix、sideInserted、wanxiangFallbackCount。

## 验收 / 退出条件
- 在 Codex App、Edge、TextEdit 三个真实场景连续输入不少于 10 分钟。
- 能稳定输入普通拼音，能稳定输入英文/代码/路径/命令。
- 首词候选不会被 LLM/RAG 覆盖。
- 上屏后 0-200ms 内出现缓存/记忆预测候选；模型候选允许异步刷新但不得阻塞输入。
- 用户继续输入拼音时，候选根据拼音约束收敛，而不是退出预测或显示无关候选。
- Esc、Shift+数字、英文模式有明确可恢复行为。
- RAG 候选可查看来源，但默认候选框保持小面积。

## 风险 / 开放问题
- macOS 输入法事件链比 Windows TSF 更脆，可能需要放弃 patch Squirrel，转为更薄的 native input method adapter。
- 0.8B 模型的候选质量可能不足，需要依赖 RAG/记忆和本地短语池补足。
- 拼音约束生成在 MLX 上需要重新实现 logits mask 或先在 Python/transformers 原型验证。
- 候选稳定性比模型质量更重要；候选跳动会直接破坏数字键选择。

## 参考
- 本地路径:
  - `../Wisdom-Weasel/RimeWithWeasel/RimeWithWeasel.cpp`
  - `../Wisdom-Weasel/WeaselServer/LlamaCppProvider.cpp`
  - `../Wisdom-Weasel/hf_backend/app/inference_service.py`
  - `../Wisdom-Weasel/hf_backend/app/pinyin_constraint.py`
- 公开资料:
  - `https://github.com/scukeqi/Wisdom-Weasel`
  - `https://github.com/scukeqi/Wisdom-Weasel/issues`
  - `https://github.com/rime/librime`
  - `https://raw.githubusercontent.com/rime/librime/master/src/rime/dict/user_dictionary.cc`
  - `https://github.com/Open-Less/openless`
  - `https://arxiv.org/abs/2203.00249`
