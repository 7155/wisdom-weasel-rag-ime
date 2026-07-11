import SwiftUI

struct DiagnosticsPage: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(title: "诊断与修复", subtitle: "检查输入法、Sidecar、模型、数据库和系统权限")
                Spacer()
                Button {
                    Task { await model.refreshAll() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .help("刷新状态")
            }
            .padding(20)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    if let components = (model.runtime?.components ?? model.overview?.components) {
                        ForEach(components.values.sorted { $0.id < $1.id }) { StatusRow(status: $0); Divider() }
                    }
                    repairActions
                    if !model.lastRuntimeActionReport.isEmpty {
                        supervisorResult
                    }
                    destructiveNotice
                }
                .padding(24)
                .frame(maxWidth: 760, alignment: .leading)
            }
        }
    }

    private var supervisorResult: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("最近一次外部监督器结果").font(.headline)
            Text(model.lastRuntimeActionReport)
                .font(.system(.caption, design: .monospaced))
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 6))
    }

    private var repairActions: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("修复操作").font(.headline)
            HStack {
                actionButton("重新注册输入源", "keyboard.badge.ellipsis", "register_input_source")
                actionButton("重启 Sidecar", "arrow.clockwise", "restart_sidecar")
                actionButton("重启本地模型", "cpu", "restart_predictor")
            }
            HStack {
                actionButton("重新部署 Rime", "shippingbox", "redeploy_rime")
                Button { Task { await model.openAccessibilitySettings() } } label: {
                    Label("打开辅助功能设置", systemImage: "lock.shield")
                }
            }
        }
    }

    private func actionButton(_ title: String, _ symbol: String, _ action: String) -> some View {
        Button { Task { await model.run(action: action) } } label: { Label(title, systemImage: symbol) }
    }

    private var destructiveNotice: some View {
        VStack(alignment: .leading, spacing: 7) {
            Text("危险操作").font(.headline)
            Text("清空历史、清空全部记忆、恢复默认配置和卸载必须先预览影响范围并再次确认。本版本不提供任意 Shell 输入框。")
                .font(.callout).foregroundStyle(.secondary)
        }
        .padding(.top, 10)
    }
}
