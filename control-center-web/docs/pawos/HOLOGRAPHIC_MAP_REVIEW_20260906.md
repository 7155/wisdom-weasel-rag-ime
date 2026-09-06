# 全息项目星图：未通过视觉验收

当前状态：用户拒绝该视觉。源码中的全息试验不能作为被接受的设计或安装完成证据。当前等待用户选择放弃全息，或保留全息但重新设计画面；不得继续以提高亮度、加粒子替代风格决定。

## 直接需求与修正

- `msg_01a0745e-4b83-7101-b765-5c3ca0e11f77`，`2026-09-06T01:38:51.907Z`：“做全息战术星图”。延续 UR-282 的风格选择，UR-283 的列表/星系双模式继续有效。
- `msg_01a07473-03ab-7a90-8ede-f8fd63c82793`，`2026-09-06T02:01:29.771Z`：“全息战术星图很不好看”。该直接反馈优先于构建、测试和 Agent 视觉判断。

## 源码试验边界

主要文件位于 `control-center-web/src/paw-os/shell/`：`PawProjectGalaxy.tsx`、`PawProjectGalaxyScene.tsx`、`paw-project-galaxy.css`、`project-galaxy-stage.ts`、`project-galaxy-hologram.ts`、`project-galaxy-shaders.ts`、`project-galaxy-model.ts`。形态为倾斜刻度盘、线框球、三臂线条和点阵。该造型被拒绝，不应继续把它当既定设计。

可独立保留的功能：真实 ID 选中与导航、模型读取的 exact Session 约束、公开进度、docs、列表/星系切换、选中时稳住星位、隐藏暂停/降低动态效果/资源释放。`SatelliteModelBadge.tsx` 支持 inspector 内联显示，`PawWayfinderWork.tsx` 注入对应 Session 的模型；Room 没有伪造共同模型。没有虚构卫星或百分比。桌面壁纸没有被本轮替换。

## 证据

- 9 个相关前端测试文件、55 项通过，日志 `/tmp/paw-holographic-tests-20260906.log`。覆盖选择、分页、docs、隐藏/降低动态效果、轨道资源释放、选中冻结后恢复、模型自身归属和内联展示。测试通过不等于视觉通过。
- 初版 `pnpm exec vite build --outDir output/holographic-build` 通过，日志 `/tmp/paw-holographic-build-20260906.log`；后来调亮/放大和增加点阵未做新的生产构建。不得混写成最终版本构建完成。
- 实际 Edge 源码页 `http://127.0.0.1:5183/?frontend=paw-os` 看到 4 个真实对话；选中 Install canary 后模型为 GPT-5.3 Codex Spark、docs 进入实际读取；这不是一次 Provider 调用。首轮没有捕获控制台错误。
- 首轮截图：`.impeccable/review/holographic-20260906/desktop.png`、`mobile.png`。后续亮度/节点尺寸调整不在这两张截图内。
- 机械检测 `/tmp/paw-holographic-design-detect-20260906.json` 为 `[]`，不证明美感。
- Astra 独立复核结论 `rebuild`：主体暗小且无焦点；经纬球/同心盘成为工程雷达；星图和右侧重复列表割裂；窄屏盘面裁切与标签拥挤。不能只靠加亮、放大、粒子解决。
- 安装协调任务 `01a071a5-79a2-76e3-ba41-fde3a5e58e80` 已收到本轮星图不能进入 App 的约束，并确认安装 patch 排除上述星图试验文件。本任务未执行安装、commit、push 或 Pi/Gateway 重启。

下一步：承接用户对保留/放弃全息的回答，再重做整体视觉构图；用户没有接受当前试验，不应将 DESIGN.md 更新成接受态。
