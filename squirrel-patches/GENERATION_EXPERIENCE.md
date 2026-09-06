# 输入法 LLM 与补全检查（2026-09-05）

对应 [O7](../OUTCOMES.md)：用户要求阅读 PAW 的输入法 LLM/补全实现，优化交互、推理和系统稳健性，并让截图中的生成展示更直观。截图是现状参考，未把图片内容当作新的执行指令。

## 检查范围与实现

| 链路 | 责任边界 | 本次改动 |
| --- | --- | --- |
| Rime 原生输入 → 上屏后联想 | `rime_sidecar.py` → `prediction_trigger.py`，保留本地、限流与旧结果丢弃 | 旧请求不能给新输入施加冷却，也不能扣掉新请求的调用计数 |
| 显式生成 → 上下文与依据 → 模型 | `active_rag_service.py`，沿用上下文预算、候选治理和现有 Provider/Pi 路径 | 超时展示与后台请求结束分开；失败不伪装成成功；取消使用实际 Provider 请求 ID |
| sidecar → Squirrel | `0001-add-rag-ime-sidecar.patch` 中的模型、Client、InputController | 投影真实 `workerPending`；超时后继续查询；停止/重试/过期启动响应取消对应后台请求；流式更新按正文与状态去重 |
| 光标附近的生成浮层 | `sources/RagImeSuggestionCardView.swift`、`RagImeAssistantPanelController.swift` | 默认 380×112，步骤展开至 380×296；突出当前操作、真实输入/依据、等待时间和“停止”；中断片段明确标注 |

四个详细步骤仍可查看。缺少状态不意味着检索完成，零命中不写“已找到”，未引用的近期输入不计入使用摘要。减少动态效果时仍更新经过时间；折叠、隐藏和结束后停止步骤动画。敏感区域阻止生成时显示明确终态。

正文流式返回和最终可插入状态都参与更新判断，避免稳定候选 ID 把后续文字挡住。后台尚未结束时不开放键盘插入。取消只发送准确的后台 Session ID，不附带输入正文；本地立即失效旧回调，迟到的启动响应会取消自身请求。

## 验证与边界

行为回归覆盖旧补全冷却/调用计数、缺省进度、零命中、未用历史、流式同 ID 更新、超时后状态收敛、键盘就绪和取消请求身份。

最终合并回归：上述三组 unittest 一次运行共 376 项通过（193.079 秒）；原生浮层 Swift 类型检查、项目上下文检查、导入边界、路由归属、补丁解析和 `git diff --check` 通过。

复现命令：

```sh
python3 -m unittest tests.test_prediction_trigger tests.test_prediction_manager tests.test_prediction_stability tests.test_prediction_first tests.test_predictor tests.test_rime_sidecar tests.test_side_lane_scheduler
python3 -m unittest tests.test_active_rag_service tests.test_active_rag_candidate_compiler tests.test_active_rag_retriever tests.test_active_rag_debug_server tests.test_active_rag_eval tests.test_deepseek_completion
python3 -m unittest tests.test_assistant_generation_behavior tests.test_assistant_generation_stage_plan tests.test_build_patched_squirrel tests.test_assistant_overlay tests.test_prediction_status tests.test_native_active_rag_cancel
python3 scripts/preview_assistant_generation.py --output-dir "$(pwd)/output/ime-generation-preview"
python3 scripts/check_project_harness.py
python3 scripts/check_import_boundaries.py
python3 scripts/check_route_ownership.py
git diff --check
```

原生预览已生成浅色/深色共 16 个案例，覆盖紧凑/展开、17 秒等待、零命中、流式、中断片段和错误；真实按钮点击与 280/320/380 宽度检查通过。预览文件与报告位于本地 `output/ime-generation-preview-20260905/`。

原生预览编译实际 AppKit 浮层源码，以合成输入验证布局和控件；它不代表输入法已安装或真实编辑器前台验收。本机 sidecar 健康检查通过，自动补全使用本地 MLX；正在运行的 Squirrel 未替换。本次未提交或推送。

`check_public_release.py --repository-only` 未通过：工作区已有其他修改，另有范围外文件包含机器路径。未修改这些内容，也未生成发布清单。本轮没有声称模型质量、首字延迟或全产品稳定性已经提高。

下一验收边界：构建并安装候选输入法，在真实编辑器验证连续上屏、删除/切换应用丢弃旧结果、流式首段与最终插入、停止后重试、服务不可用及敏感区域。安装前不得将预览或当前旧安装的事件当成本轮验收。
