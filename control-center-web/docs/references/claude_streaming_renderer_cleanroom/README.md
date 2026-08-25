# Claude Progressive Markdown Renderer — Clean-room TypeScript/React 实现

这是根据一份 Claude Desktop Web SPA 构建的**可观察行为**独立重写的流式 Markdown renderer。它不是 Anthropic 原始源码，也不包含其 bundle。

核心目标：

```text
稳定前缀冻结 + 仅更新活动尾块
```

适合聊天、Agent transcript、thinking stream、工具结果和长代码输出。

## 已实现

- 增量 Markdown block scanner：只扫描新增后缀
- `completedChunks + streamingChunk`
- React 自定义 memo 冻结旧块
- 未闭合 fenced code 快路径
- 完整行增量语法高亮与 grammar state 延续
- Markdown safe text release / hold-back
- streaming flag deferred latch
- 嵌套 fence、bullet、Setext heading 输入修复
- settled 后全篇 AST 按 source offset 回填的基础函数
- Long Animation Frame 性能采样
- bundle marker 自动定位脚本

## 目录

```text
src/core/
  blockScanner.ts                 增量块边界扫描
  openFence.ts                    未闭合顶层 fence 检测
  incrementalTokenizer.ts        完整行 tokenizer cache
  shikiAdapter.ts                 Shiki grammar-state 适配
  safeInlineBoundary.ts          安全显示边界
  normalizeStreamingMarkdown.ts  LLM Markdown 容错
  positionedTree.ts              settled 全篇 AST 分块

src/react/
  ProgressiveMarkdown.tsx        renderer-agnostic 主组件
  ReactMarkdownAdapter.tsx       react-markdown 开箱适配
  IncrementalCodeBlock.tsx       增量代码组件
  useDeferredStreaming.ts        deferred latch
  useProgressiveChunks.ts        scanner React hook
  useSafeTextRelease.ts          rAF 显示调度

src/telemetry/
  longFrameObserver.ts           LoAF 测量
```

## 安装

```bash
npm install
npm run build
npm test
```

`react-markdown` 和 `remark-gfm` 是可选依赖；只使用 core 或 renderer-agnostic React 层时不需要它们。发布包中适配器单独从 `./react-markdown` 导出。

## 最简 React 用法

```tsx
import { ReactMarkdownProgressive } from "./src/react/ReactMarkdownAdapter.js";

export function AssistantMessage(props: {
  messageId: string;
  text: string;
  isStreaming: boolean;
}) {
  return (
    <ReactMarkdownProgressive
      documentKey={props.messageId}
      text={props.text}
      isStreaming={props.isStreaming}
      className={
        props.isStreaming
          ? "progressive-markdown"
          : "standard-markdown"
      }
      holdBack
      openFenceFastPath
    />
  );
}
```

## 接入已有 Markdown renderer

主组件不绑定 `react-markdown`：

```tsx
import { ProgressiveMarkdown } from "./src/react/index.js";
import MyMarkdown from "./MyMarkdown.js";

<ProgressiveMarkdown
  documentKey={message.id}
  text={message.text}
  isStreaming={message.status === "streaming"}
  renderChunk={({ text, active, settled, openFence }) => {
    if (openFence) {
      return (
        <>
          <MyMarkdown>{openFence.prefix}</MyMarkdown>
          <MyIncrementalCode
            language={openFence.language}
            code={openFence.value}
            streaming
          />
        </>
      );
    }

    return (
      <MyMarkdown data-active={active} data-settled={settled}>
        {text}
      </MyMarkdown>
    );
  }}
/>
```

`renderChunk` 应尽量用 `useCallback` 保持稳定。即使它变化，流式期间已冻结块也不会仅因 callback identity 改变而重渲染；`renderVersion` 可显式强制失效，例如切换代码主题：

```tsx
<ProgressiveMarkdown renderVersion={themeName} ... />
```

## 增量代码高亮

高亮器只需要实现逐行、可传递状态的接口：

```ts
interface StatefulLineTokenizer<Token, State> {
  key: string;
  initialState: State;
  tokenizeLine(
    line: string,
    stateBefore: State,
  ): {
    tokens: readonly Token[];
    stateAfter: State;
  };
}
```

使用：

```tsx
<IncrementalCodeBlock
  code={code}
  language="typescript"
  streaming={isStreaming}
  tokenizer={typescriptTokenizer}
/>
```

行为：

- 已完成行只 tokenize 一次；
- 当前未完成末行先显示 plain text；
- 新换行后才高亮该行；
- stream 结束时高亮最后一行；
- 早期行变化时，从第一条不一致行截断缓存；
- 默认超过 204,800 字符退化为 plain rendering。

## Settled 全篇语义

流式期间逐块 parse 很快，但 reference links、footnotes 等语义可能跨块。`ProgressiveMarkdown` 提供 `finalizeDocument`：

```tsx
<ProgressiveMarkdown
  ...
  finalizeDocument={({ text, chunkOffsets }) => {
    const finalRoot = parseWholeDocumentToHast(text);
    const buckets = splitPositionedChildrenByOffsets(
      finalRoot.children,
      chunkOffsets,
    );
    return buckets.map(renderHastBucket);
  }}
/>
```

若 parser 插件会把 root child 替换成没有 position 的新节点，可在 transform 前后调用：

```ts
rememberRootChildren(root, file);
// transforms...
restoreInsertedRootPositions(root, file);
```

## PAW / Agent UI 的推荐边界

不要把整轮消息做成一个不断变化的大对象：

```text
Turn
├─ TextChunk 0        🔒
├─ ToolCall           独立 live island
├─ ToolResult         🔒
├─ TextChunk 1        🔒
├─ SubAgentStatus     独立 live island
└─ ActiveTextTail     🔄
```

Markdown renderer 只负责文本块；ToolCall、Todo、subagent、artifact 等各自使用独立 store selector 和 memo 边界。这才是把 Claude 的思想扩展到 Agent OS 的正确方式。

## 验证

```bash
npm test
```

当前结果：

- core TypeScript 编译通过
- 21 个测试全部通过
- scanner 通过 20,000 份随机 Markdown 差分验证
- 7 个 React/TSX 文件通过语法转译检查

本环境没有安装 React 类型依赖，因此没有用真实 `@types/react` 执行最终 package 全量 typecheck；源码另外通过了本地 API shim 的严格 TypeScript 检查。安装依赖后应运行：

```bash
npm run build
```

## Benchmark

```bash
npm run bench -- 600 24
```

本次合成测试：

```json
{
  "documentChars": 42858,
  "updates": 1786,
  "chunks": 1229,
  "incrementalMs": 27.86,
  "fullRescanMs": 311.15,
  "speedup": 11.17
}
```

这里只比较 scanner；不代表 React + Markdown + DOM 的整体加速倍数。

## 定位未来 Claude 构建

```bash
npm run inspect -- /path/to/ion-dist
```

脚本会按以下 marker 给 bundle 排序：

- `completedChunks`
- `streamingChunkOffset`
- `openFenceTailGrafted`
- `streamingTextRootChildren`
- `chat.code_stream_render`
- `long-animation-frame`
- `completeLines`

当前上传构建中，`shared-10-Dndtc5mJ.js` 以 93 分显著排在第一位。

## 分析报告

详见 [`analysis/CLAUDE_RENDERER_FINDINGS.md`](analysis/CLAUDE_RENDERER_FINDINGS.md)。
