# 从测量到收益 · 2026-09-05

用户补充要求：“优化完成。测出收益，才有故事”。沿用小任务、低 token、OS 自举、保留失败与质量优先的约束。本轮不重跑大型业务数据集、不启动浏览器。

## 已冻结实验：结构化 Room 合并

- 目标对象：workflow，唯一改动为用程序校验合并代替第三个模型整合步骤；伙伴任务、模型、Prompt、输出 schema、验收器和各臂预算一致。
- 原因证据：上一三 case 对照中，两个伙伴已经有互不重叠的输出，额外整合模型没有增加正确发现。旧单 Session/Room 的 2/3 失败回执原样保留。
- 本轮控制：三 case 的字段类型在运行前向两臂同样说明，形成 `typed-contract-v2`；不能把旧 2/3 与新 3/3 拼作质量提升。
- 基线：两个伙伴 + 一个模型整合者；候选：两个伙伴 + lossless、schema-checked 程序合并。基线与候选各建一个新 Room，伙伴 Session 不共享历史。
- 自举：先跑基线，再由真实 Lab Pi 诊断选择已实现的受限 operator，最后运行候选。Host verifier 最终评分；诊断模型不投通过票，也不自行生成 Runtime 代码。
- 模型：Luna low；每臂至多 3 Provider calls / 12k observed tokens；整个基线、诊断、候选实验至多 6 calls / 20k observed tokens / 单次输出 768，一次候选。结算后停止下一调用，不宣称在途硬截断。
- 质量硬门禁：全部 3 个 case 精确正确，字段类型合法，不重复、不缺漏、不修补伙伴答案。程序合并器只看 schema 和 ID，不读取 Gold。
- 收益主指标：每个成功完整组的实际目录价估算成本下降。同步报告实际 Provider calls、完整 turn tokens、墙钟时间，优化器和候选试跑投入不隐藏。
- 推广边界：一个结构化任务的 paired Validation；不是 Room 相对单 Agent 的普遍收益，也不是生产平均节省率。

## 验收责任

主 Session 自行实施和复核。新合并器、同输入/新 Room 隔离、结算预算两项回归以及既有 micro/Room 回归已 **16/16 通过**。没有创建新的 Codex 子 Agent。

## 首轮与确认计划

首轮六次调用已全部返回，共 20,407 tokens，超过预设结算观察阈值 407。旧 runner 在最后一次结算后抛错，因此没有保存最终候选评分；原始失败回执保留。六个完整 Pi turn 重新核算一致，按原 schema、原验收器离线合并，基线/候选均 3/3；不增加模型调用或改答案。

首轮基线三次模型调用，9,911 tokens、$0.00203172；候选两次，6,391 tokens、$0.00124572。全实验 $0.00424544 含诊断，未宣称在 20k 内完成。修正 runner 将结算后预算状态与免费 Host 质量评分分开，仍禁止超过阈值后启动新付费请求。

随后只确认已冻结候选：复用该匹配基线和 Lab 的 operator 选择，新建 Room，至多 **2 Provider calls / 10k observed tokens / 768 单次输出**；不重新优化、不再诊断、不改任务或 worker Prompt。这是一次独立候选确认，不伪装为新配对基线或未见题测试。

## 确认完成

实际 2 次调用、6,394 tokens、$0.00152980，质量 3/3，处于预算内；相对保留基线少 1 次调用、tokens 降低 35.49%、目录价估算成本降低 24.70%。八条完整 turn 的用量复核通过；六条 worker 正文与冻结输入完全匹配，六个独立 Session 分属三个 Room。两个运行目录中的临时 `config/auth.json` 均已清理。

首次基线/候选有缓存命中，确认无缓存命中，成本降幅不同；摘要采用确认值。完整收益、预算超额、调用投入与可用简历表述见 [OPTIMIZATION_RESULTS.md](OPTIMIZATION_RESULTS.md)。本轮不再追加付费调用。

## 最终验证

- `python3 -m unittest tests.test_agent_lab_room_merge tests.test_agent_lab_micro tests.test_agent_lab_room_comparison -v`：**16/16**，0.813 秒。
- `python3 -m unittest tests.test_agent_lab_trials tests.test_agent_lab_trial_execution tests.test_agent_lab_trial_routes`：**38/38**，54.503 秒。测试期间出现一次未关闭 SQLite 连接的 `ResourceWarning`，不影响通过结果，未扩展到与本任务无关的清理修改。
- `python3 scripts/check_project_harness.py`、`python3 scripts/check_import_boundaries.py`、本任务路径 `git diff --check` 通过。九份修改文件另通过 Python 语法、尾部空白与本地链接检查；根 OUTCOMES 为 1,295 words，低于 1,300 上限。
- 两次运行使用同一 Pi Runtime identity；两个模型调用进程组均已退出，实际 `config/auth.json` 不存在。完整证明索引保存于确认目录 `verified-gain.json`，包含七份原始/核验回执 hash。
- 本轮不修改已安装 Runtime、个人 Skill、生产数据库或简历母版；未提交、推送、发布。共享目录已有的无关修改保持原样。
