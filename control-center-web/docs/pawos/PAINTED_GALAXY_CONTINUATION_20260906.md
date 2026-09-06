# 纯代码艺术星系 · 2026-09-06

## 当前控制方向

承接任务 `01a071a1-a095-7e73-a2d5-e97cfefaa09f`，原始继续目标为 `01a070e8-ba60-7390-a628-8bef2d3c2e1b`。完整原话、时间和消息 ID 见 [UR-282](requirements/PAWOS_REQUIREMENTS_278_283.md)。

用户选择艺术化旋涡、允许梵高式星空，随后明确“你用代码画”。首个细碎双旋臂被评价“缺少美”。最新优先级为“首先是美，实用性不怎么要求”和“任你发挥，美就行”。这些是直接用户要求。此前 NASA、生成图和全息试验均不构成当前视觉验收。

## 柔光笔触版本（星尘细化之前）

项目星系采用不对称构图：长外旋臂与较短内旋臂围绕温暖中心，深墨底色留白，蓝金笔触沿曲线缓慢流动。底层连续色带与较清楚的颜料纹理分开绘制。项目星系没有加载生成图片、照片或行星贴图。

任务以光点出现；靠近、键盘焦点或选择时显示名称和状态。选择时任务目标与标注停住，详情仍使用真实 Session/Room、自己的模型、进度与项目 docs。普通 Session 没有伪造完成百分比。文字列表和全屏星系继续共存。原来的桌面壁纸和完整 Browser 不是本轮重绘范围。

- `src/paw-os/shell/project-galaxy-paint.ts`：连续底色、曲线笔触、程序纹理；四个绘制批次，11,800 个笔触实例，笔触与底面合计 103,202 个三角形。每帧只更新时间 uniform，几何不重建。
- `src/paw-os/shell/project-galaxy-shaders.ts`：抽象星光与背景星点。
- `src/paw-os/shell/project-galaxy-stage.ts`：渲染生命周期、镜头、轨道、悬停标注与选择；隐藏时停绘、像素预算、资源释放。
- `src/paw-os/shell/PawProjectGalaxy.tsx`、`paw-project-galaxy.css`：画面优先的布局和按需详情。
- `src/paw-os/shell/project-galaxy-model.ts`：真实项目项的稳定视觉投影。`PawProjectGalaxyScene.tsx` 保持可访问的同 ID 按钮与 WebGL fallback。

被弃用的 `project-galaxy-hologram.ts` 已无消费者并移除。之前生成的参考图移出产品资源目录，保留在忽略的 review 历史中，没有接入产品。

## 柔光笔触版本验证

以下均为这轮本地证据，不能代替用户审美判断。

| 项目 | 结果与边界 |
| --- | --- |
| 定向检查 | 9 个测试文件，58 项通过；覆盖真实数据投影、列表切换、标签避让、选择锁定、轨道/入场、暂停时悬停、窄窗口目标可达、GPU 资源复用与释放、自己的 Session 模型。 |
| 生产构建 | `VITE_CONTROL_TRANSPORT=http VITE_BUILD_CHANNEL=production pnpm run build --outDir output/painterly-build` 通过，包含 TypeScript。保留共享大 chunk 告警。 |
| 所有权检查 | `python3 scripts/check_import_boundaries.py` 与 `python3 scripts/check_route_ownership.py` 通过。 |
| 浏览器 | 完整 Edge 源码页，桌面 CSS 1525×716 与窄窗口 CSS 354×767；页面现有 110% 缩放。四个实际视图已捕获：默认/选中 × 桌面/窄窗口。模型读取为 GPT-5.6 Sol；未绑定项目明确说明 docs 的工作区条件。 |
| 画面审阅 | 首轮 `fix`：局部雾化压住笔触、冗余眉题、旧设计文档。一次修复后 reviewer 对三项分别给出 resolved，disposition 为 `ship`，仅覆盖该修复清单。 |
| 性能范围 | 渲染节流约 30 FPS、DPR 上限 1.5、约 180 万像素预算；隐藏窗口停止 RAF/绘制，慢帧可降低分辨率。没有独立 GPU 基准或跨设备流畅度结论。 |
| 发布范围 | 源码预览；本轮没有 App 安装、提交、推送，也没有发起新的 Provider/Agent 执行。 |

定向命令在 `control-center-web` 中运行：

```sh
pnpm exec vitest run src/paw-os/shell/PawProjectGalaxy.test.tsx src/paw-os/shell/PawProjectGalaxyScene.test.tsx src/paw-os/shell/project-galaxy-stage.test.ts src/paw-os/shell/project-galaxy-model.test.ts src/paw-os/shell/project-galaxy-labels.test.ts src/paw-os/shell/project-galaxy-physics.test.ts src/paw-os/shell/project-galaxy-entrance.test.ts src/paw-os/shell/PawWayfinderWork.test.tsx src/features/paw-os/SatelliteModelBadge.test.tsx
```

本地证据位于 `.impeccable/review/painterly-20260906/`：`direction.md`、`assets.json`、`desktop.png`、`selected.png`、`mobile.png`、`mobile-selected.png`、`finish-review.md`、`finish-verdict.md`。日志为 `/tmp/paw-painted-galaxy-tests-20260906.log` 和 `/tmp/paw-painted-galaxy-build-20260906.log`。这些忽略路径服务于本机续接，GitHub 续接以源码、本文和需求账本为入口。

`DESIGN.md`、`.impeccable/design.json` 和专属 surface brief 已只同步项目星系范围。设计选择由用户给定，未运行概念抽签，不虚构 seed 或已批准设计稿；项目 hash 仅控制颜料分布。

## 星尘材质细化 · 2026-09-06 03:21 UTC 用户反馈之后

用户直接反馈“质感不对，粒子太少，不过柔和酷炫”，精确消息见 UR-282。本次保留构图、蓝金柔光、缓慢流动和已有交互，把材质重心从连续色带移向细密星尘。没有再次换风格。

- 新增 `src/paw-os/shell/project-galaxy-dust.ts`：150,000 颗细粒与 2,000 颗较深的柔光微粒，共两个 `THREE.Points` 批次；星核、旋臂与稀疏外晕使用不同空间分布。程序点精灵提供柔和边缘，不加载贴图。
- `project-galaxy-paint.ts` 将连续底色和笔触亮度减弱，笔触降到 2,300 个；连同底面为 37,202 个三角形。整幅背景画由五个批次组成：底色、两层笔触、两层星尘。原 11,800 笔触/103,202 三角形数据仅属于上一版。
- `project-galaxy-stage.ts` 将远景星点从 720 增至 2,200，并在尺寸或渲染比例变化时同步粒子的透视像素尺度。星尘几何属性合计 7,296,000 字节，每帧只更新时间 uniform，不重建或上传粒子缓冲。
- 原生命周期测试已扩展：限制星尘数量、几何字节数、绘制批次和笔触三角形；检查动画/进度更新不重建或上传属性、尺寸改变更新粒径投影，关闭后所有层的几何和材质只释放一次。9 个定向文件共 58 项通过，生产构建（含 TypeScript）通过。构建仍有共享大 chunk 告警。
- 本机完整 Edge 源码页实看默认/选中 × 桌面/窄窗口，窄窗口 CSS 354×767；真实选中模型为 GPT-5.6 Sol，页面读取的错误日志为空。最终恢复完整桌面、收起详情、1× 播放。截图位于 `.impeccable/review/stardust-20260906/`；日志为 `/tmp/paw-stardust-tests-20260906.log` 和 `/tmp/paw-stardust-build-20260906.log`。

仍保留约 30 FPS 节流、像素预算和隐藏停绘；本轮没有独立 GPU 基准或跨设备帧率结论。没有新增图片资产、Provider/Agent 执行、App 安装、提交或推送。上一节 reviewer 的 `ship` 只属于当时三项修正，本次素材细化为主 Agent 的实际画面检查，不延用为新的独立审阅或用户认可。

## 下一步边界

[打开源码预览](http://127.0.0.1:5183/?frontend=paw-os#/agent)，从项目文件夹进入星系。当前保留 1× 播放。视觉需求仍记录为 `in_progress / unverified`：用户先前拒绝的版本、自动审阅通过、功能测试通过和用户认可分别保留。继续时以用户对实际新画面的反馈为准，不重复询问已经确定的方向，也不把本轮源码更新写成 App 安装完成。
