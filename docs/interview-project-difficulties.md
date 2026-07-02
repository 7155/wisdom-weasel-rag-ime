# RAG 输入法项目难点面试材料

## 项目一句话

这是一个本地优先的 RAG 输入法：用户在打字时，输入法会从本地历史、记忆库和相关上下文里召回材料，再把材料压缩成可选择的输入候选。它不是让 Agent 事后猜上下文，而是在用户输入过程中完成上下文对齐。

## 核心难点

### 1. RAG 的输出不能直接变成输入法候选

传统 RAG 召回的是 chunk、段落、历史对话、源文档片段；输入法候选需要的是可快速扫视、可用数字键选择、能直接插入的短文本。

我把中间层设计成 candidateization：

```text
RetrievedMemory
  -> short surface text
  -> insert text
  -> evidence preview
  -> expanded source
  -> accept / skip / pin / downrank feedback
```

这让检索结果不直接污染输入框，而是先变成输入场景可消费的候选。

### 2. 候选字和候选段落共用 1-9 数字键

输入法的数字键是高频肌肉记忆，不能简单拆成“1-5 选字、6-0 选段落”。这个项目的产品判断是：如果 RAG/LLM 候选永远排在传统候选后面，它就只是普通输入法的附属功能，项目亮点会消失。当前正式前端策略是统一数字键，但候选源按“智能候选优先、Rime 兜底”合并：

```text
1-8: 本地小模型 / RAG / 记忆候选优先占位
剩余: Rime / 词库 / 拼音方案候选兜底
```

显示上再分层：LLM 短预测适合横向排列，像普通词候选一样快速扫视；RAG/记忆候选往往是短句或片段，需要纵向排列，保留可读性。选择路由仍然不同：Rime 候选调用 librime 的 `select_candidate_on_current_page`，side candidate 由前端直接插入 `insertText` 并回写选择反馈。

### 3. 输入法是实时系统，RAG 不能阻塞打字

输入法和普通聊天窗口不同，打字路径必须低延迟、可取消、失败不影响输入。

当前工程策略是：

- 先用 SQLite/FTS5 做低成本召回；
- 小模型预测走可选 OpenAI-compatible 本地服务；
- 每次预测设置短超时，失败直接返回空候选；
- Swift 输入法前端异步调用 JSON bridge；
- 只展示最新 composition 对应的候选，避免旧请求覆盖新输入。

面试表达可以这样说：我不是把 RAG 简单接进输入法，而是把检索和模型预测做成输入法实时链路上的可降级候选源。

### 4. 本地隐私和模型资源冲突

这个项目的亮点是个人输入历史不上传云端。但本地同时跑 embedding、reranker、小语言模型，会占用显存和内存。

所以架构上分层：

```text
Mac:
  InputMethodKit 原型 / Squirrel-Rime 正式前端
  SQLite 本地事件库
  FTS/BM25 基线召回
  可选 0.6B/1.7B 小模型预测

用户自己的 WSL 机器:
  embedding / rerank / 更大模型实验
```

这和“云端 RAG”不同：默认不把个人输入交给第三方服务，远端也只考虑用户自己的设备。

### 5. 记忆反馈不能做成全局加权

用户在一个上下文里 pin 某条记忆，不代表这条记忆在所有问题里都应该排第一。

因此记忆治理要和 query 绑定：

- accept/pin 对相似查询强加权；
- skip/downrank 对相似查询强惩罚；
- 不相关查询只受弱影响；
- delete/hide 才是全局可见性控制。

这个点比普通 RAG 更像输入法学习：它学的是“在这个输入意图下什么有用”，不是全局点赞。Squirrel patch 已经把 side candidate 的选择回写成 `commit` 和 `accepted` action，让用户每次选中记忆候选都能反过来改善排序。

### 6. Debug UI 和真实输入法 UI 必须分离

RAG 有很多调试信息：召回耗时、embedding、rerank、证据来源、action 日志。但真实输入法窗口很小，不能展示这些。

当前设计把两者分开：

```text
debug page:
  看 pipeline、耗时、payload、action、证据

native IME panel:
  只看短候选、少量 RAG 候选、一行证据摘要
```

这能保证产品体验不被工程调试信息拖垮，同时保留可观测性。

### 7. 不能重复造 RAG / 记忆系统

另一个方向的 PI 插件也需要 RAG/记忆。如果输入法单独建一套 SQLite、索引、action 反馈，会导致两套记忆不一致。

所以边界是：

```text
shared core:
  SQLite / FTS / embedding / action governance / agent context

adapters:
  PI extension
  macOS IME
  debug page
```

输入法只做 adapter 和候选展示，不拥有底层记忆治理。这是长期可维护的关键。

### 8. 不能让大模型替代词库和拼音解析

大模型擅长续写和重排，但不适合直接解析用户的原始拼音按键流。真实输入里会有简拼、错拼、分词不确定和数字混入，如果直接交给模型猜，延迟和稳定性都会变差。

所以正式框架选择 Rime/Squirrel：

```text
raw key input
  -> Rime 方案 / 词库 / 拼写纠错
  -> preedit + candidates + labels + comments
  -> LLM rerank / continuation
  -> RAG / memory side candidates
```

这里的工程判断是：不要重新造一个拼音输入法，也不要让模型替代确定性的输入引擎。创新点应该放在候选增强、记忆召回、证据反馈和本地模型延迟控制上。

### 9. 首 token 低延迟不是简单换小模型

输入法里的模型预测看的是 TTFT，也就是第一个可见候选出现的时间，而不是完整回复耗时。一个 0.8B 模型如果每次都走 HTTP、重复系统 prompt、输出解释文字，仍然会慢到不适合打字。

当前方案把模型 lane 拆成三层：

```text
Mac 快速实验:
  text-only Qwen3 0.6B/1.7B + MLX-LM resident service
  -> stream_generate + prompt_cache

短期对照:
  Ollama qwen3.5:0.8b-mlx
  -> 只作为 smoke baseline, 不作为最终输入法模型 lane

最终可控内核:
  native llama.cpp/Metal 或 direct MLX provider
  -> stable prompt KV cache
  -> multi-sequence candidate sampling
```

这个难点的面试表达是：我没有把“本地小模型”当成黑盒，而是把实时输入法拆成可测的首 token 路径。模型必须常驻、非思考、短输出、可流式、可复用 prompt/KV cache；如果超过预算，输入法继续显示 Rime/RAG 候选，模型 lane 自动降级。

目前已经有可讲的实测结果：在 Mac 上用无代理下载的
`qwen3.5:0.8b-mlx`，warm sequential TTFT 的 p50 首 chunk 是 46ms，说明
“200ms 内出现第一个模型侧候选”不是空想。但同一模型在 34 条历史上下文预测
case 上只通过 2 条，完整 JSON 响应也仍然要数百毫秒。所以项目的真正难点不是
“下载一个 0.8B 小模型”，而是把它改造成输入法可用的实时 side lane：首候选流式
展示，完整候选异步补齐，事实和个人记忆仍由 RAG 负责。

最新工程修正是：Qwen3.5 小模型路线在 Hugging Face / MLX-community 上更偏
VLM，`Qwen3.5-0.8B` 标为 image-text，MLX 版本需要 `mlx-vlm`。输入法并不需要
视觉 encoder，所以 MVP 改成 text-only Qwen3 + `mlx-lm`，先试
`mlx-community/Qwen3-0.6B-4bit`，质量不够再升到 `Qwen3-1.7B-4bit`。这个判断
可以作为面试亮点：我不是追最新模型名，而是按输入法首候选延迟、常驻内存和
输出协议选择最小可控模型。

这里还有一个工程判断：Ollama MLX 是当前已测最快 smoke baseline，不等于最终
产品内核。真正面试时可以强调我把两件事分开了：短期用 Ollama MLX 保证本地
调试和 Squirrel/RAG 闭环继续前进；中长期用 native `llama.cpp`/Metal 或 direct
MLX-LM 争取可控的 KV cache、取消过期请求、序列复制和批量多候选采样。这样讲
比“我换了一个小模型”更像实时系统优化。

为了避免把 smoke baseline 误包装成最终成果，我把这个判断做成了
`quality-gate --require-predictor-capability ...`。默认 gate 可以验证 RAG、
sidecar、缓存和候选展示；最终模型 lane gate 还必须显式通过 `promptCache`、
`sequenceFork`、`batchCandidates`。这对应 Wisdom-Weasel
`LlamaCppProvider::PrepareSystemPrompt()` 和 `GenerateCandidatesBatch()` 的源码机制，
也让面试时能说清楚：我不是只报一个快的 token 数，而是把底层能力变成了可重复
验收的工程条件。进一步说，MLX 这条实验 lane 现在会通过 `/health` 做 runtime
capability probe；`promptCache=true` 要求缓存已经被生成路径实际使用，不能只靠
“启动时准备了缓存”来算通过。

### 10. 后端有候选不等于系统输入法真的显示了候选

这次真实集成里踩到的一个关键坑是：sidecar、RAG、MLX 模型都可以在 HTTP/doctor
里返回候选，但用户看到的候选框仍然可能是纯 Rime。原因不是 RAG 没有返回，而是
macOS 实际运行的 `/Library/Input Methods/Squirrel.app` 还是旧系统 bundle；用户
目录里的新版 `Squirrel.app` 已经有补丁，但系统输入源加载的是同 bundle id 的旧前台。

为了解这个问题，我把验收从“接口能返回”升级成三层：

```text
backend contract:
  /api/rime-suggest 返回 displayCandidates
  -> model/inline + rag/block + shared selectionKey

installed app contract:
  Squirrel 二进制必须包含 sidecar_request_scheduled
  + rag-ime.foreground-trace.v2
  + sidecar_empty_response_cleared
  + panel_text_layout

system runtime contract:
  macOS 当前 selected input source
  -> /Library/Input Methods/Squirrel.app 是新版
  -> strict doctor 无 stale same-bundle app
```

这个点的面试表达是：输入法项目不能只测后端 API，因为用户路径在系统输入法前台。
我最后把“系统正在运行哪个 app bundle、当前 selected input source 是否真的是
Squirrel、前台是否真的 apply sidecar 候选、空响应是否覆盖旧候选”都变成了可检查的
工程 gate。它解释了为什么这个项目比普通 RAG demo 难：
它既有模型/RAG 排序问题，也有 macOS 输入法生命周期、bundle 注册和前台实时渲染问题。
真实前台 trace 现在能验收 `modelInline=5`、`ragBlock=3`、横向模型行、纵向记忆行，
以及数字键从 `number_key_route` 到 `side_candidate_commit` 的完整提交链路。

## 我已经落地的工程点

- macOS `InputMethodKit` 前端壳；
- AppKit `NSPanel` 小候选面板；
- Swift -> Python JSON bridge；
- 本地 SQLite/FTS5 MVP core；
- shared-core JSON adapter；
- debug server 和浏览器调试页；
- `modelPredictions` 顶层候选 payload；
- OpenAI-compatible 本地小模型预测 provider；
- 数字键统一选择模型候选和 RAG 候选；
- accept / commit / action 本地记录链路；
- 单测和 macOS app 构建验证；
- Rime/Squirrel 正式前端路线 ADR；
- Squirrel patch pack：在 Rime 候选生成后调用本地 sidecar，异步合并 side candidates，按显示候选路由数字键，并在用户接受 RAG 候选后回写 commit/action。
- 系统级 patched Squirrel 安装 gate：检测新版前台标记，避免 macOS 加载同 bundle id 的旧系统 app 后继续显示纯 Rime 候选。
- strict doctor 现在能验收 `display=8 model=5 rag=3 rime=0`、MLX next-token logits/top-k、本地 LaunchAgent、系统输入源 selected=true、真实前台 trace，以及 stale same-bundle app 检测。
- 模型 holdover 按 `project + committedContext fingerprint` 分桶，并覆盖外层 dispatch 超时，避免旧模型线程完成后污染当前输入上下文。
- `predictor-ttft` 首 chunk 和 first parsed candidate 延迟测量；
- Mac 本地推理路线调研：Ollama MLX tag、MLX-LM prompt cache、llama.cpp/Metal KV cache、Core ML stateful KV、MiniVLLM/vLLM 取舍。
- 实测 `qwen3.5:0.8b-mlx` 在 Mac warm path 上达到 46ms p50 first chunk，同时用质量评测证明 0.8B 模型不能替代本地 RAG 记忆。

## 面试讲法

可以按这个顺序讲：

1. 传统 RAG 的问题是 Agent 事后猜上下文，容易召回噪声。
2. 我的切入点是输入法，因为输入法是用户最高频的上下文生产入口。
3. 难点不是简单检索，而是把检索结果变成用户愿意在输入过程中选择的候选。
4. 我把系统拆成 shared memory core 和输入法 adapter，避免和 PI 插件重复造库。
5. 正式前端复用 Rime/Squirrel 的成熟拼音解析和词库，不让大模型直接猜 raw pinyin。
6. 我用本地 SQLite/FTS5 先保证闭环，再把本地小模型预测作为可选候选源。
7. 输入法 UI 和 debug UI 分离，真实面板只保留小面积候选，调试页负责 pipeline 可观测性。
8. 整个系统默认本地完成，适合个人知识库和 Agent 上下文对齐。

## 一句话亮点

这个项目不是“给输入法加一个大模型”，而是把输入法变成个人记忆系统的反馈入口：用户每次选择、跳过、固定候选，都会反过来提升本地 RAG 和 Agent 上下文对齐质量。
