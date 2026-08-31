# PAWOS 用户需求账本 · UR-207

> 导航：[UR-206](PAWOS_REQUIREMENTS_206_206.md) · [总索引](../PAWOS_REQUIREMENTS.md) · 下一份：[UR-208](PAWOS_REQUIREMENTS_208_208.md)
>
> `current` 只表示当前控制语义，不表示实现完成。实施状态与证据见
> [PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)。

### UR-207 — PAWOS 垂直 App 自举、独立源码、Skill、SGG 沙盒与安装生命周期

- **状态 / 优先级：** `current / P0 self-hosting`
- **真实需求：** PAWOS 内的普通 Agent 能为一个垂直场景制作和迭代 App，按
  对话模式调整 App 内的 Agent 对话界面，同时设计 App 专属 Skill，并用 Trace、
  Eval 和受控沙盒测试后继续优化。垂直业务源码不得散入 PAWOS 核心，而应由
  独立 Extension App 目录持有；核心只提供通用注册、宿主、图标和生命周期接缝。
  第一个真实自举样例是“掌柜问数”，以现有 SGG `fixture-v2` 作为离线自测套件，
  但不得把 fixture 冒充真实经营数据。每个 Extension App 必须有自己的图标，并
  通过受管 Package 的安装、启用、停用、卸载和回滚状态控制桌面、Dock、窗口与
  专属 Skill 的可用性。
- **原话依据：** “垂直app还能os的agent自己修改app前端来制作app安装，自己设计垂直技能，自己trace沙盒测试进行优化，例如，根据对话模式修改app的agent对话界面”；“你现在理解os内制作和安装app的流程了吗，这个需要配备自举的技能的”；“掌柜问数用sgg的这个进行测试自举开发。自举开发不要进入项目，或者加入extenionapp文件夹啥的。这个app就能完成掌柜问数”；“还有app的icon这些，安装还有，卸载这些。”来源：当前任务，2026-08-30。

## 继续阅读 / 编辑

- 下一份：[UR-208](PAWOS_REQUIREMENTS_208_208.md)
- 实施状态：[PAWOS_REQUIREMENT_STATUS.md](../PAWOS_REQUIREMENT_STATUS.md)
- 总入口：[PAWOS_REQUIREMENTS.md](../PAWOS_REQUIREMENTS.md)
