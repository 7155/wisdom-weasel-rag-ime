# 交互模式映射：Clowder → 纸面语言（2026-07-26）

| Clowder 行为 | 我们的需求 | 纸面化改写 | 验证 |
|---|---|---|---|
| scrollToMessage：raf 重试 + 1.5s 蓝色 ring 闪烁 | 跳转定位需要短暂强调 | 左缘墨线 + 纸面水洗渐settle（1.3s，单次、不闪烁；reduced-motion 只留墨线） | data-history-target 样式 + 时序已由 AgentTimeline 计时器控制 |
| 线程级草稿 Map（unmount 前 useLayoutEffect 写回 + LRU） | 切换 Room 不丢草稿 | **已有等价实现**：roomDraftsRef Map + 切换恢复 + 发送后清除（rooms/index 127/210/340/865） | 焦点探针：输入→切换→返回，文本保留 |
| ime.isComposing() 集中防抖 | 组合期 Enter 不发送 | 已有：两个 Composer 共用 229/isComposing 三重判据 | 单测覆盖（chat/composer 套件） |
| textarea scrollHeight 自增 | 输入自增不抖动 | 更优：field-sizing:content + 测量式 clearance（增长 0 位移，CLS 0） | perf 探针 growthDelta=0px |
| Enter 运行中 → 入队 | 忙碌时不丢消息 | 已有语义：干预/接续投递模式 + 检查器消息队列 | 现有 e2e |
| MessageNavigator 上下条 | 长对话定位 | 已有右缘 minimap 圆点 + 预览；不引入第二导航 | 现状保留 |
| ToastContainer 线程级通知/切线程清理 | 路由/线程切换无陈旧提示 | 不适用之改写：错误就地内联（会话头/房间槽），全局区仅连接级通知 | 检查器/头部内联样式已验证 |
| RightStatusPanel 渐进披露 | 状态面板不淹没 | 已有：Session 可折叠节 + Room 静态节（信息模型差异，保留） | 现状 |
| 执行条 stop/cancel/retry 区分 | 动作语义清晰 | 已有：停止(warning)/重试(内联)/破坏性删除(danger 确认) 三分 | 现有 UI |
| 底部锚定线程 | 对话贴近书写缘 | 已实现：Room Virtuoso alignToBottom+followOutput | 房间无死腔（本轮截图） |

不引入：猫拟物、发光呼吸、bounce/shake、emoji 通知、Clowder 依赖或整组件拷贝。
