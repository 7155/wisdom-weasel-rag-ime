# PAWOS 用户需求账本 · UR-271

`current` 表示控制语义，完成程度见[实施状态](../PAWOS_REQUIREMENT_STATUS.md)。

### UR-271 — 项目文件夹可切换全屏星系、选择行星并阅读项目 docs

- **状态：** `current`。
- **直接原话：** “文件夹点开能否选择可视化为全屏星系来选择，星系能看到各个行星进度和星球状态，还有这个项目的docs。”
- **来源：** 继续任务 `01a071a1-a095-7e73-a2d5-e97cfefaa09f`，`msg_01a071d9-21bd-70c0-a6fc-5a50d6b5a5fa`，`2026-09-05T13:54:10.511Z`。附件 `codex-clipboard-e4cf8f20-7f40-45d1-902e-f90169309b16.png` 展示三个“未绑定项目”文件夹；随后 `codex-clipboard-6902fea7-2f94-4557-8ffc-12f939f444fd.png` 补充展开后的对话列表。截图用于定位入口，不作为 Runtime 状态证明。
- **实施解释：** 保留文件夹列表，在展开头部提供“全屏星系”；在 OS 视口中用可选择的行星展示该文件夹的实际 Session/Room，读取现有状态和公开进度。Room 有真实任务条目时展示完成数/总数；Session 没有总任务数时不制造百分比。
- **文档边界：** 从项目已有 Session 的工作区读取实际 docs 与根目录文档，允许目录导航、有限预览及在 Files 中完整阅读。不把 UI 分组键当后端 Project ID，不猜测工作区或文档路径。未绑定文件夹引导打开原对话选择目录。
- **验收：** 文件夹→星系→选择→打开原对话、返回列表及焦点恢复；真实状态/进度更新、文档读取/失败重试/未绑定状态；窄屏和键盘；行星分页、惰性加载、隐藏和减少动效。仍保留全 OS、Browser 及后台多 Agent 要求。

- 上一份：[UR-270](PAWOS_REQUIREMENTS_270_270.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-272–UR-274](PAWOS_REQUIREMENTS_272_274.md)
- 实施记录：[星空、Browser 与性能续接](../STELLAR_BROWSER_CONTINUATION_20260905.md)
