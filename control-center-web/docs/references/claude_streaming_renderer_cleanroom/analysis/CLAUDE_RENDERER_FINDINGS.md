# Claude 新流式 Markdown Renderer：bundle 逆向结论

## 结论先说

这份 Claude Desktop / Web SPA 构建证明，新 renderer 的核心并不是简单换一个更快的 Markdown 库，而是把一次回答拆成：

```text
normalized stream
      │
      ├─ completedChunks[]  ── 已完成、稳定、可冻结
      │
      └─ streamingChunk     ── 唯一持续变化的尾块
```

随后又叠加了四个专门优化：

1. **增量块扫描器**只扫描新增后缀，上一条未完成物理行会在下一次追加时重扫。
2. **React.memo 自定义比较器**冻结已完成块；流式期间甚至刻意忽略 parser/components 等对象身份变化。
3. **未闭合 fenced code 快路径**只解析到 opening fence，然后把增长中的代码正文嫁接到代码 AST 节点，避免每个 token 重跑 Markdown parser。
4. **逐行增量语法高亮**缓存完整物理行和 grammar state，未完成末行先按纯文本显示，结束时再高亮一次。

因此它把每帧成本从“与整条回答长度相关”压缩为“主要与当前 mutable tail 和新完成代码行相关”。

---

## 分析对象

上传压缩包：

- 大小：62,438,180 bytes
- SHA-256：`d3ef57aad1acd7aa399b758fa2acc40cf46531e136da9499589be50a0a3d045a`

解压后：

- 约 2,350 个 JavaScript 模块
- 约 134 MB 有效内容
- 未发现 `.map` sourcemap
- `index.html` 元数据：
  - `data-build-id="spa-dev"`
  - `data-git-hash="local"`
  - `data-build-timestamp="1787278227"`
  - 对应 UTC：2026-08-21 02:10:27

关键构建文件：

| 文件 | SHA-256 | 作用 |
|---|---|---|
| `assets/v1/shared-10-Dndtc5mJ.js` | `879ab3d72b1aff93c37482dfc158ef03d87b4450157d86ee0655907ace216f28` | 流式 Markdown、代码高亮、性能遥测核心 |
| `assets/v1/shared-5-CykGk_Dj.js` | `9f07b0df7f5630bf67b811e4263610c098d15030bbac618d3cad18a69a7bdde5` | Markdown 输入规范化、deferred streaming hook |
| `assets/v1/c3e2391e3-BQJuX05U.js` | `452c34ca282f15038ef61febe26c92e3cb15e65521da0f18f41ae2390837c63b` | Chat 消息层调用 progressive renderer |

完整哈希见 [`BUILD_EVIDENCE.json`](./BUILD_EVIDENCE.json)。

---

## 1. `completedChunks + streamingChunk` 是明确存在的

`shared-10-Dndtc5mJ.js` 中保留了以下可读属性名：

- `completedChunks`
- `streamingChunk`
- `streamingChunkOffset`

压缩后的内部函数可暂记为：

- `ai`：增量 Markdown 块扫描器
- `ci`：把扫描状态转换成 completed/tail 结构
- `Si`：单个 chunk 的 memoized renderer
- `ki`：外层 progressive Markdown renderer

扫描器状态包含：

```text
codeFence
inMathBlock
inList
listPendingBlank
inTable
inBlockquote
inIndentedCode
indentedCodePendingBlank
hadBlankLine
hadContent
offset
```

它会判断新文本是否以旧文本开头：

- 是：从保存的 `offset` 继续扫描；
- 否：视为内容重写，从初始状态重新扫描。

最后一条物理行不会永久提交到扫描状态，因为下一次追加可能把：

```text
-
```

变成：

```text
- list item
```

也可能把普通行变成表格、fence 或 Setext heading。因此它保留“重扫最后一行”的安全余量。

### 直接效果

已完成块的字符串和对象引用不再变化，只有尾块继续增长：

```text
Chunk 0  🔒
Chunk 1  🔒
Chunk 2  🔒
Tail     🔄
```

这才是官方所说“only touch what's still changing”的具体实现。

---

## 2. 它不只是 `React.memo()`，而是有意设计了冻结语义

单块 renderer 使用自定义 memo comparator。它会比较：

- chunk 文本
- 动画边界
- settled 状态
- 已缓存 HAST
- open-fence fast-path 开关
- word-fade carry 状态

关键细节是：

> 流式期间，若旧块文本没有变化，它不会因为 processor、transform options 或 components 对象身份变化而重新渲染；结束后才重新把这些配置纳入比较。

这比普通：

```tsx
export default React.memo(Message)
```

更强。普通 memo 很容易因为父组件每次创建新对象、新回调而失效；Claude 的比较器把“流式旧块必须冻结”直接编码成组件语义。

---

## 3. `requestAnimationFrame` 的真实职责：安全释放文字

之前可以合理猜测 rAF 被用于 token batching，但这份 bundle 给出了更精确的答案：

> 在这个 renderer 内部，rAF 主要控制“已经收到的字符串何时安全地显示”，而不是证明网络 delta 本身都由 rAF 合批。

它维护一个可见字符位置，并检查：

- 裸 list marker
- ATX heading marker
- 未闭合 inline code
- directive
- 未闭合链接/图片括号
- 未闭合 emphasis
- partial word

调度参数可从构建中直接观察到：

- 常规步长约 40 字符
- 目标间隔近似 `clamp(12000 / backlog, 25, 150ms)`
- 超长未闭合结构不会无限卡住，存在最大 hold-back 范围
- 页面从 hidden 恢复可见时会直接释放到当前安全 ceiling

所以它解决的不只是性能，还解决流式 Markdown 常见的视觉抖动：

```text
**bold
[link](htt
-
##
```

不会过早以错误结构闪现，再突然重排。

### 不能从本 bundle 证明的事

上游 SSE/WebSocket delta 是否还有额外批处理，可能存在于别的状态层，但不能仅凭这个 renderer 的 rAF 代码下结论。

---

## 4. 未闭合代码块有专门的 AST graft 快路径

构建中保留了明确标记：

```text
openFenceTailGrafted
```

处理流程是：

```text
当前 tail
  │
  ├─ Markdown before opening fence
  ├─ opening fence
  └─ growing code body
```

如果尾部存在一个顶层、尚未关闭的 fenced code block：

1. 只把文本解析到 opening fence；
2. 找到最后一个 code MDAST node；
3. 验证它的位置正好对应 opening fence；
4. 直接更新该节点的 `value` 和结束位置；
5. 再执行后续 HAST 转换。

这样 500 行代码在继续生成第 501 行时，不需要重新 Markdown-parse 前 500 行代码正文。

代码包中的对应实现：

- `src/core/openFence.ts`
- `src/react/ReactMarkdownAdapter.tsx`

干净重写版没有复制 Anthropic AST 代码，而是采取等价的 renderer-level bypass：前缀走 Markdown，增长中的 code value 直接交给增量代码组件。

---

## 5. 代码高亮是“完整行缓存 + grammar state 延续”

`shared-10` 中的内部类（压缩名 `Ac`）明确执行：

1. 按 `\r?\n` 拆出完整物理行和 trailing partial line；
2. 比较旧缓存与新输入的最长公共完整行前缀；
3. 从第一条变化行开始截断缓存；
4. 新行调用高亮器，并把上一行的 grammar state 传给下一行；
5. 流式期间 trailing partial line 保持纯文本；
6. settled 时再高亮最后一行；
7. 若高亮超时或 grammar state 异常，退化为 plain rendering；
8. 超过约 204,800 bytes 的代码块禁用高亮快路径。

这对多行注释、模板字符串等跨行语法尤其重要，因为不能把每一行完全独立 tokenize。

代码包中的对应实现：

- `src/core/incrementalTokenizer.ts`
- `src/core/shikiAdapter.ts`
- `src/react/IncrementalCodeBlock.tsx`

---

## 6. 流结束后会做一次全篇 parse，而不是永远分块 parse

单独解析每个 chunk 会破坏部分 whole-document 语义，例如：

- reference link definition
- 跨块 footnote
- 某些插件产生的 root-level node
- 转换后节点的 source position

Claude 的解决方法：

1. streaming 时逐 chunk parse；
2. settled 后全篇 parse 一次；
3. 以 processor/options/text 为键缓存最终 HAST；
4. 按 chunk 的 absolute source offset，把最终 root children 重新分配到各 chunk；
5. 保留原先 chunk 布局，避免结束时整棵 UI 突然替换。

构建还包含两段 position repair 插件：

- transform 前保存 root children，标记名为 `streamingTextRootChildren`；
- transform 后给新插入、缺少 position 的 element 恢复对应源节点位置。

干净重写版提供了独立原语：

- `rememberRootChildren`
- `restoreInsertedRootPositions`
- `splitPositionedChildrenByOffsets`

位于 `src/core/positionedTree.ts`。

---

## 7. streaming flag 还做了 deferred latch

`shared-5` 中存在一个很小但重要的 hook：

```text
return currentStreaming || useDeferredValue(currentStreaming)
```

效果是：网络层刚把 `isStreaming` 改为 false 时，progressive renderer 会再保留一个 deferred render，然后再进入 settled/finalized 模式。

这减少：

- 同一个高优先级更新里同时切模式和全篇 parse；
- 尾块动画突然消失；
- DOM 结构瞬间大换血。

干净重写版对应 `src/react/useDeferredStreaming.ts`。

---

## 8. Markdown 输入在 parse 前会先修复

`shared-5` 中的 normalizer 做了三类处理：

1. 把模型常输出的 `•` 转成 Markdown `-`；
2. 处理嵌套 backtick fences：让父 fence 比内部示例 fence 更长；
3. 去掉 fence 行缩进；
4. streaming 时临时隐藏末尾可能尚未完成的 Setext underline。

对应实现：`src/core/normalizeStreamingMarkdown.ts`。

这说明新 renderer 的稳定性并不只依赖 React，而是包含一层“面向 LLM 输出习惯的 Markdown 容错”。

---

## 9. Anthropic 在主动测 Long Animation Frames

代码中保留：

- `long-animation-frame`
- `chat.code_stream_render`

统计字段包括：

- update count
- plain update count
- stream duration
- text length / line count
- 字符编码类别
- long frame 数量
- blocked 总时长 / 最大值
- long frame duration 总和
- 页面是否曾 hidden
- 结束原因

这说明优化不是靠主观观感。他们为代码流式渲染建立了浏览器端真实性能遥测，并能比较 plain/highlighted、live stream、语言类型等维度。

干净重写版提供精简的：

- `observeLongAnimationFrames()`
- `createStreamRenderProbe()`

位于 `src/telemetry/longFrameObserver.ts`。

---

## 10. Chat 层确实在使用 progressive renderer

`c3e2391e3-BQJuX05U.js` 的消息渲染层会根据消息是否仍在流式输出切换 class：

```text
progressive-markdown
standard-markdown
```

文本消息和 thinking 内容都接入同一套 progressive Markdown 组件，并默认打开 streaming fade-in。

这不是一个未接入的实验模块，而是当前聊天消息路径的一部分。

---

## 完整架构图

```text
transport text
      │
      ▼
LLM-oriented Markdown normalization
      │
      ▼
safe inline release scheduler (rAF)
      │
      ▼
incremental block scanner
      │
      ├──────── completed chunks ────────┐
      │                                  │
      └──────── active tail              │
                    │                    │
          open fence detected?           │
             │             │             │
            yes            no            │
             │             │             │
       code-tail graft   normal parse    │
             │             │             │
       line tokenizer      │             │
             └──────┬──────┘             │
                    ▼                    ▼
                 React.memo frozen chunk islands
                    │
                    ▼
                 minimal DOM changes
                    │
           stream end + deferred latch
                    │
                    ▼
        one full-document final parse + HAST split
```

---

## 本项目的验证结果

### 单元测试与差分验证

- 21/21 单元测试通过
- 增量 scanner 与从 bundle 行为重建的私有 reference harness 做了 20,000 份随机 Markdown 文档差分，chunk 边界与扫描状态全部一致
- 覆盖：
  - chunk commit
  - append-only identity stability
  - code fence/list/table/blockquote 边界
  - 非前缀重写 reset
  - open fence detection
  - safe inline boundary
  - incremental line tokenization
  - nested fence normalization
  - finalized positioned-tree splitting

### 合成扫描 benchmark

配置：

- 文档：42,858 UTF-16 字符
- 追加更新：1,786 次
- 最终 chunk：1,229 个

本次运行：

| 模式 | 时间 |
|---|---:|
| 保存扫描状态、只扫后缀 | 27.86 ms |
| 每次从头扫描 | 311.15 ms |
| 比值 | 11.17× |

注意：这只测 block scanner，不是整个 React/Markdown/DOM 的端到端 benchmark；结果也会随机器和运行波动。

---

## 可信度边界

### 可以确认

- progressive chunk 数据结构
- 增量 suffix scanner
- React.memo 冻结策略
- safe-release rAF scheduler
- open-fence AST graft
- complete-line incremental highlighter
- settled whole-document parse 和按 offset 分配 HAST
- deferred streaming latch
- Long Animation Frame telemetry
- Chat 消息路径已接入

### 不能确认

- 原始 TypeScript 文件名、变量名和源码注释
- Anthropic 服务端如何组织 token/delta
- renderer 外层是否还有额外 network-event batching
- 官方“4×”数字的具体实验样本和统计口径

原因是当前构建没有 sourcemap，只有生产 bundle。本文使用的短压缩名仅用于定位，不应被当作原始源码命名。

---

## 代码性质

`claude_streaming_renderer_cleanroom` 是根据可观察行为和构建结构独立重写的实现：

- 不包含 Anthropic bundle；
- 不复制其压缩函数正文；
- API 和命名重新设计；
- 核心模块可独立编译并有测试；
- React 适配层可直接迁移到 PAW 一类 Agent UI。
