# README 配图

这组图展示新版 Lab 的真实源码组件，数据仅来自仓库中已公开的 EnterpriseOps 历史实验元数据。它和首页对比表使用同一组运行：Sol r8 → Luna 仅换模型 r5 → Luna 提示词调整 r7。

- [项目与实验过程](lab-workspace.webp)
- [指标对照](lab-metrics.webp)
- [采集时间、源码与文件指纹](manifest.json)
- [公开元数据快照](../../../control-center-web/e2e/fixtures/readme-lab/scene.json)

三个阶段分别通过 3/3、2/3、3/3 个任务，成本估算为 $1.711214、$0.09453296、$0.07291692。图中的比例由对应阶段的通过数与同一冻结任务集的 3 道题计算。模型与提示词的组合变化不能全部归因于模型本身；金额也不是 Provider 账单。

这是只读的源码界面截图：未访问个人数据库、Session 或凭据，未重新运行实验，没有模型调用。样例页面阻止项目命令，采集器还会拒绝 API 与外部网络请求。安装版和 Release 的能力应按各自版本核对。

## 重新采集

依赖已安装的前端、Playwright Chromium 和 `cwebp`。在两个终端中分别执行：

```bash
# 终端一，从仓库根目录进入前端；关闭真实 Gateway 代理。
cd control-center-web
VITE_CONTROL_PROXY_TARGET='' pnpm dev
```

```bash
# 终端二，在仓库根目录执行，传入终端一显示的地址。
node scripts/capture_readme_lab.mjs http://127.0.0.1:5173
```

采集器会更新本目录的两张 WebP 与 manifest；原始 PNG 留在忽略的 `control-center-web/output/readme/`。截图没有做后期内容修改。像素可能随浏览器和字体版本变化，文件指纹只标识这一轮采集。

场景快照由现有的 [公开实验导出器](../../../scripts/export_agent_lab_showcase.py) 生成，取 `enterpriseops` 一项；只包含可公开的汇总指标和来源标识，不包含题目、答案或对话正文。更新实验版本时，先同步该元数据，再重新采集图片与 README 表格。

[返回 README](../../../README.md) · [其他功能图集](../current/README.md)
