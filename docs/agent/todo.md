# Todo

## Now

- [ ] 三遍阅读协议（每个参考模块都必须执行）
  - [x] 第一遍：当前先读源码，记录真实机制、文件路径、函数名、关键分支和不能照搬的地方。
  - [x] 第二遍：写本项目对应代码前，重新打开同一批参考文件，对照确认要迁移的机制。
  - [x] 第三遍：实现完成后，再按同一 TODO 回查参考源码和本项目 diff，确认没有偏离核心交互。
- [ ] Felix3322/Wisdom-Weasel 逐文件阅读和迁移清单
  - [x] 00 基线：记录 Felix fork、原 Wisdom-Weasel、当前项目三者关系。
  - [x] 01 `WeaselServer/LLMProvider.h` / `WeaselServer/LLMProvider.cpp`：请求类型、候选切片、prompt、provider 边界。
  - [x] 02 `RimeWithWeasel/RimeWithWeasel.cpp`：按键生命周期、display candidates、数字键路由、pending commit、scheduler。
  - [x] 03 `WeaselServer/ContextHistory.h` / `WeaselServer/ContextHistory.cpp`：commit -> context history -> no-input prediction 闭环。
  - [x] 04 `third_party/alpha-input/src/user_frequency.rs`：同一短语反复上屏后的 session / long-term 频率先验。
  - [x] 05 `third_party/alpha-input/src/predictive_similarity.rs` / `preference.rs`：semantic / preference / frequency score breakdown 与正负反馈。
  - [x] 06 `alpha_backend/src/main.rs`：rerank HTTP 边界、branch context、top1 guard、trace 字段。
  - [x] 07 `hf_backend/app/prompting.py` / `hf_backend/app/main.py`：小模型 prompt、shown / selected / rejected telemetry。
  - [x] 08 Rime Lua / Alpha bridge：Lua filter、C++ bridge、用户反馈注入点。
  - [x] 09 rime-wanxiang：schema、Lua hooks、词库和用户词频接入边界。
  - [x] 10 Weasel UI / candidate list：候选显示、source label、布局与候选框生命周期。
  - [x] 11 installer / build docs：只提取可迁移的安装、诊断、重启、签名经验。
- [ ] 本项目迁移实现
  - [x] 写代码前复读：`RimeWithWeasel/RimeWithWeasel.cpp` 的按键退出、display candidate、commit 后预测、stale request 丢弃。
  - [x] 写代码前复读：`alpha_rerank.lua` 的 commit feedback、query variants、top1 guard、日志字段。
  - [x] 写代码前复读：`wanxiang.schema.yaml` / `super_english.lua` / `auto_phrase.lua` 的首词锚定、英文、用户词频边界。
  - [x] 写代码前复读：`LLMProvider.cpp` / `hf_backend/app/prompting.py` 的短候选 prompt 与 candidateization。
  - [x] prediction-first top1 guard，避免低价值短词长期占首位。
  - [x] `/rime-select` 接收 `shownCandidates`，记录 selected 与 skipped-higher feedback。
  - [ ] SQLite / FTS5 频率与反馈路径对齐 Felix user-frequency / preference 思路。
  - [ ] MLX prompt 与 candidateization 对齐 Felix 的短候选策略。
  - [ ] debug / doctor 输出 source、score、guard、latency、backend，能定位 RAG / LLM / memory 是否真的生效。
  - [x] tests 覆盖候选生命周期、反馈、top1 guard、RAG/记忆/LLM 三路候选。
  - [x] 完成后第三遍核对：逐项打开参考源码和本项目 diff，确认候选框不会常驻、数字键不会被无输入预测长期占用、LLM/RAG/memory 来源可见且可选择。

## Next

- [ ] 对照 Felix prompt，重写 Qwen/MLX 小模型候选生成 prompt，避免解释性长句和“剪贴板式候选”。
- [ ] 对照 Felix scheduler，调整本项目候选框消失、刷新冻结、旧请求丢弃、无输入时不常驻的问题。
- [ ] 对照 rime-wanxiang，确认首词锚定、传统词库兜底、用户词频上浮的最佳接入点。
- [ ] 对照 Wisdom-Weasel 原始项目，补齐本项目缺失的真实输入法闭环，而不是只做 sidecar demo。

## Blocked

- [ ] `/Library/Input Methods` 下历史 Squirrel / RAG-IME 重复项仍需要管理员权限清理；输入法安装验证必须先确认当前选中的 bundle 是最新构建。

## Done (today)

- [x] 记录 Felix3322/Wisdom-Weasel 为重点参考仓库并推送 `fb1ac7f`。
- [x] 完成 Felix/Wisdom-Weasel 第一遍逐项阅读：LLMProvider、RimeWithWeasel、ContextHistory、alpha-input、alpha_backend、hf_backend、Rime Lua bridge、Wanxiang schema/hooks、候选 UI 生命周期、安装/诊断脚本。
- [x] 完成三遍阅读协议在本轮实现上的闭环：二次复读参考源码、实现 top1 guard / shownCandidates feedback、第三遍对照 diff，并通过全量 312 个测试。
