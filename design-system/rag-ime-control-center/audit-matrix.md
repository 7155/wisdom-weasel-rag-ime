# 前端路由 × 状态 覆盖矩阵（2026-07-26 完成审计）

图例：I=已实现并经真实页面/源码核验 · S=由共享系统实现（QueryState 骨架+错误重试 / 壳层连接监视 / EmptyState）· C=契约支持并在预览数据中呈现 · e2e=由通过的套件覆盖 · B=需要新的后端语义（不伪造）

| 路由 | 填充 | 空态 | 加载 | 错误/重试 | 离线/受限 | 审批/确认 | 取消/暂停/部分 | 窄屏/移动 | 深色 |
|---|---|---|---|---|---|---|---|---|---|
| agent | I | I(新对话欢迎) | S | I(头部警示+重试) | S(壳层 离线/连接受限) | I(检查器审批门) | I(停止/e2e) | I | I |
| rooms | I(对话/任务/伙伴) | S | S | I(room-error 槽) | S | I(待验收+批准) | I(中止/e2e) | e2e 抽屉+I | I |
| overview | I | I | S | S | S | – | – | I | I |
| memory | I | S | S | S | S | I(等你确认 4) | – | I | I |
| knowledge | I | I(资料/队列) | S | S | S | – | C(处理中/需处理) | I(移动全出血) | I |
| planning | I | I | S | S | S | – | C(唤醒计划含已暂停) | e2e | I |
| roles | I | I(空目录文案) | I(目录警示) | I(catalogNotice+重试文案) | S | – | – | e2e | I |
| plugins | I | I(未启用/回执占位) | S | S | S | – | I(已停用) | I | I |
| browser | I | I(尚未截图·内嵌虚线框) | S | S | I(预览环境提示) | I(协同确认) | I(停止) | e2e | I |
| voice | I | I | S | S | I(浏览器预览提示) | I(保存前确认) | – | e2e | I |
| input | I | I | S | S | I(等待系统状态) | I(切换模式确认) | – | e2e | I |
| history | I | I | S | S | S | – | – | e2e | I |
| governance | I | I(0 项) | I | I(errorCode/dead_letter 徽记) | S | I(待确认规则) | – | e2e | I |
| context-debug | I | I(不可用态) | I | I(DebugNotice/查询级) | S | – | – | e2e | I |
| observability | I | I | S | S | S | – | I(已完成/失败徽记) | e2e | I |
| diagnostics | I | I | S | S | I(等待后台状态) | I(修复先预览) | – | e2e | I |
| configuration | I | – | S | I(模型账号不可用) | S | I(变更先看影响) | – | I | I |

## 审计发现与处置
- 导航↔页面 17/17 一一对应；无缺页、无孤立入口、无重复路由。
- `RoutePlaceholder.tsx` 为不可达死代码 → 已删除。
- Session 欢迎态原不可预览 → 预览传输新增空会话「新对话」(session-fresh)。
- 三条“另一产品”路由（knowledge/context-debug/roles）→ 采纳共享纸面语法（画布上的纸张、统一 gutter、衬线标题）。
- 浏览器截图空区由死空间改为内嵌虚线待捕获框；任务页焦点句采用展示衬线。

## 需后端语义（记录，不伪造）
- 各路由细粒度断连呈现目前统一由壳层 ConnectionIndicator/通知承担；如需逐页降级视图，需要传输层暴露每能力的可用性信号。
- 任务“部分完成”聚合进度（跨多目标）无既有投影字段。
