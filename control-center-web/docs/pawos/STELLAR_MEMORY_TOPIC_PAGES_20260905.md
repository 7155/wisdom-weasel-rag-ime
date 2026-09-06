# 星际桌面与主题记忆：改动及依据（2026-09-05）

后续纠正与进展见[星空、Browser 与性能续接](STELLAR_BROWSER_CONTINUATION_20260905.md)：后台 Agent 以多颗星球显示，点击不再是壁纸重点；新增完整 Browser、粒子和可切换暗色模式。下文记录前一版原因与证据，不作为新要求的最终完成声明。

## User Requirement Ledger / 用户需求账本

| 直接要求 | 控制语义 | 来源与对应内容 |
| --- | --- | --- |
| “星际要酷炫，当前这个不行” | 当前淡色线框效果被否定，继续浅色宇宙与白色阅读面 | [UR-265](requirements/PAWOS_REQUIREMENTS_265_266.md#ur-265--重做被否定的星际视觉明显呈现酷炫与纵深)，下文桌面改动 |
| “记忆优化，可视化也优化” | 同时改善记忆正确性与用户理解方式 | [UR-266](requirements/PAWOS_REQUIREMENTS_265_266.md#ur-266--记忆内容与可视化一起优化)，下文主题页与图形改动 |
| “怎么改的，为什么这么改，都要有逻辑” | 原因、实现、证据及限制连成可核对记录 | [UR-264](requirements/PAWOS_REQUIREMENTS_260_264.md)，本文及[可靠性前序记录](PAWOS_RELIABILITY_CONTINUATION_20260905.md) |

主任务负责集成、实际页面、安装与最终判断。支持 Agent 的回归结果是待主任务核对的证据，不自动关闭要求。参考文章针对旧 Git 快照的判断经过当前源码复核；其示例和研究建议不当作生产数据库的事实。

## 1. 为什么重做桌面

原星际只用淡色椭圆与少量星点，色差和尺度差太小，无法体现用户明确要求的酷炫与纵深。单纯提高透明度、增加旋转线条仍不会形成可辨认的空间主体。

[PawStellarBackdrop.tsx](../../src/paw-os/shell/PawStellarBackdrop.tsx) 将星云、透明行星和近景星点分为三个平面。大行星位于右侧，斜向星环呼应星云光带；左侧保持明亮天空供桌面图标使用。图标标签有浅色底，App 仍在不透明白色表面内阅读。[stellar 样式](../../src/paw-os/styles/paw-os-stellar.css) 只改变该视觉身份，不改其他 App 的内容所有权。

鼠标视差分别为 6 / 20 / 34 px，使用两条弹簧数值直接更新 transform，避免每次指针事件重渲染 React。背景以 60–90 秒缓慢漂移，平移、缩放及旋转均在 transform 上完成。App 获得前台、协同聚焦、窗口拖动、后台页面、粗指针和减少动态效果时停止；停止不移除天空，也不影响阅读或 Runtime 的完成状态。旧地形仅在其他视觉身份继续消费原有 pulse 契约。

两张专用素材由 Imagegen 生成；PNG 内嵌生成提示，像素与原件一致，行星具有透明 alpha。尺寸、提示、来源意图及文件哈希见[素材来源](../../src/paw-os/assets/stellar/provenance.json)。PNG 选择是为了保留当前元数据工具支持的内嵌提示；不是第二个视觉真相源。

真实源码选择链为 `main.tsx → startControlCenter → App(product=paw-os) → PawOsApp → PawDesktop → Wayfinder → PawStellarBackdrop`，由[源图](../handoffs/PAWOS_REAL_FRONTEND_SOURCE_MAP.v1.json)的 product render owners 与当前调用点核对。预览不是另写的展示网页。

## 2. 为什么 Book 不能继续追加旧摘要

当前 `_derive_topic_books()` 的旧实现将已有摘要与“本次补充”相接后截到 900 字。旧摘要既占用了新修正的空间，也可能在成员被更正后仍保留旧结论。成员一致性检查能够拒绝部分失效 Book，却不能替正文重新组织认识。

[memory_curation.py](../../../rag_ime/memory_curation.py) 现在从已知当前成员重建短摘要，将本次成员放在前面，排除被更正及撤回成员；不再把旧生成文本当独立事实。短摘要继续服务导航，完整阅读不再受这段摘要的长度限制。

## 3. 主题正文为什么使用当前 Atom 投影

[memory_topic_page.py](../../../rag_ime/memory_topic_page.py) 在同一次 SQLite 读取快照内生成 `current / constraints / openQuestions / history` 和逐条来源。它不写 Atom，不建立独立数据库或另一位 Wiki Agent。[memory.entity.get](../../../rag_ime/memory_graph_read.py) 沿既有路由添加可选 `topicPage`，并保留来源展开契约；旧后端不提供时，UI 明确提示待读取而不将 catalog 摘要当作当前正文。

章节依据显式 Atom kind 分类，历史依据有效时间、claim state、谱系和替代关系。Book 自身项目范围优先约束成员、谱系及 Evidence，同时保留既有全局项；请求未带 project 也不能将其他项目同谱系内容混入。`supports` 与合法 `corrects` 来源均保留。撤回、隐藏、敏感、未生效和无可读支持的内容按既有治理约束过滤；历史后续链接仅指向最终可展示的 Atom。

主集成额外复现了两个问题：默认空 project 会串入另一项目同谱系 Atom，以及历史链接可能指向已过滤的未来 Atom。均先红后绿后才接受。缺少来源的旧 Atom 标记 `unavailable`；未提供理由时说尚未提供可核对理由，不推断原始记录一定没有理由。

这次是可重建的确定性主题阅读投影。尚未实现模型对多条依据进行新的语义综述、局部章节生成发布，或完整问题导向召回。不能把章节化展示称为这些能力已经完成。

## 4. 为什么阅读先于图形

[MemoryTopicPage.tsx](../../src/features/memory/MemoryTopicPage.tsx) 从当前认识、约束、变化、未决问题开始，每条能展开原文与依据，空章节不制造内容。深链保留 Book ID，返回来源后仍可回到同一主题；未核对摘要折叠为回看内容。

默认 Memory 入口改为主题目录，明确的 Atom/Evidence/Timeline 链接保留。图形移到主题页末尾按需展开；[MemoryRelations.tsx](../../src/features/memory/MemoryRelations.tsx) 按该主题预筛，并将标签边明确标为导航共现。页面因此先回答记住了什么，再帮助探索主题怎样联系，避免把标签共现描述成支持或因果。

## 验证与剩余边界

- 桌面三文件 71 项回归通过，包括阅读/聚焦/拖动暂停、媒体偏好、可见性和 listener 清理；TypeScript 通过。
- Memory 后端 102 项回归通过，覆盖长旧摘要后的修正、撤回、谱系、项目范围、有效时间、来源、编译和投影恢复。
- Memory 前端与 App 入口 88 项回归通过，契约生成 169 项一致性检查与 TypeScript 通过。
- 实际源码页面已观察 1280×720、1440×1000、390×844 的桌面，以及 1280 的白色阅读窗口；图片加载成功、没有横向文档溢出，前台 App 时动效暂停。视觉独立复核仍在进行。
- 新主题接口和正文需要在当前数据快照上做真实浏览器验证。上述测试不是私人记忆语义质量评测，不提供新的召回或成本收益数字；新主题/星际改动尚未安装。

安装、页面回执及最终独立复核结果在本节追加，不能从测试或截图提升为 native 验收。全 OS / 逐 App、真实长期记忆质量和其他场景评测仍继续。
