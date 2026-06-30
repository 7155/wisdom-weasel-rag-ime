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

输入法的数字键是高频肌肉记忆，不能简单拆成“1-5 选字、6-0 选段落”。当前实现采用统一编号：

```text
1-3: 上方本地小模型短预测
4-6: 下方 RAG / 记忆候选
```

模型候选和 RAG 候选共享同一套数字键，UI 只显示少量信息。这样既保留传统输入法速度，又能让用户看到更长记忆候选的证据摘要。

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

这个点比普通 RAG 更像输入法学习：它学的是“在这个输入意图下什么有用”，不是全局点赞。

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
- Rime/Squirrel 正式前端路线 ADR。

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
