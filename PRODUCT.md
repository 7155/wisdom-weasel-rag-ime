# PAW 产品上下文

<!-- impeccable:product-schema 1 -->

本文件为界面设计工具提供索引；产品权威仍为 [PROJECT.md](PROJECT.md)、[OUTCOMES.md](OUTCOMES.md) 和 [PAWOS 产品契约](control-center-web/docs/pawos/requirements/PAWOS_PRODUCT_CONTRACT.md)。

## Platform

web

## Users

开发者通过本机工作台使用 Agent 完成工作；当前用户也将项目用于面试演示。

## Product Purpose

以 Agent 对话、记忆、RAG、多 Agent 协作以及垂直场景测评优化，完成可验证的实际任务。

## Operating Context

桌面 Electron 宿主中的 PAWOS 前端；Pi Session 为执行单位，Room 组织协作。当前实施顺序为状态一致性、Agent/Room 体验、Agent Lab。

用户随后将范围扩展至整个 OS 和所有 App，并允许整体重做；核心 App 仍优先，系统级改造与逐 App 验收同属当前工作。详见 [UR-251–253](control-center-web/docs/pawos/requirements/PAWOS_REQUIREMENTS_251_253.md)。

## Capabilities and Constraints

Pi 拥有执行、停止和恢复；界面只投影真实事件。保留 Session 与 Room 能力及证据入口。核心 App、Enterprise RAG 与双层优化范围见 [UR-242–245](control-center-web/docs/pawos/requirements/PAWOS_REQUIREMENTS_242_245.md)。

## Brand Commitments

PAWOS 使用白色工作界面与轻浅灰层次，以行星伙伴、轨道、各自行星的真实 Tool Agent 卫星和双向消息流保留星空身份。用户明确否定本轮深色版本，要求审美把控；长正文使用清楚、安静的阅读面。本轮用户选择直接实现并展示真实 Room，既有 UI 仅作功能参考。

这里的深色否定指较早一轮桌面方案；用户后来明确选择项目星系采用深色、纯代码绘制的艺术旋涡，并以美感优先，此例外仅约束项目星系表面，不改变正文阅读与 Runtime 事实边界。

## Evidence on Hand

仓库源码、测试、已安装 Gateway、Pi Runtime 和真实 Session/Room 持久事件。测试通过、构建、安装、真实前台验收分别记录；禁止将演示数据视为真实运行结果。

## Product Principles

- 内容与结果优先，协作细节按需展开。
- 状态由 Runtime 事实决定，重连不复活旧执行。
- 可见任务完成与可恢复体验优先。
- 当前需求与验收状态以需求账本为准。
