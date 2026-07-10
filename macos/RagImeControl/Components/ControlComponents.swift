import SwiftUI

struct PageHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.title2.weight(.semibold))
            Text(subtitle).font(.callout).foregroundStyle(.secondary)
        }
    }
}

struct StatusRow: View {
    let status: ComponentStatus

    var body: some View {
        HStack(spacing: 10) {
            Circle()
                .fill(status.ok ? Color.green : Color.red)
                .frame(width: 8, height: 8)
            Text(label).frame(width: 120, alignment: .leading)
            Text(status.detail).foregroundStyle(.secondary)
            Spacer()
            Image(systemName: status.ok ? "checkmark" : "exclamationmark.triangle")
                .foregroundStyle(status.ok ? Color.secondary : Color.red)
        }
        .padding(.vertical, 7)
    }

    private var label: String {
        switch status.id {
        case "inputMethod": return "输入法"
        case "sidecar": return "Sidecar"
        case "predictor": return "本地模型"
        case "foregroundContext": return "前台上下文"
        case "hybridRag": return "Hybrid RAG"
        case "memoryCompiler": return "记忆编译"
        case "sqlite": return "SQLite"
        default: return status.id
        }
    }
}

struct PendingApplyBanner: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        if !model.pendingApplyModes.isEmpty {
            HStack(spacing: 10) {
                Image(systemName: "arrow.clockwise.circle.fill").foregroundStyle(.orange)
                Text("部分设置需要应用到运行组件")
                Spacer()
                Button("立即应用") {
                    Task { await apply() }
                }
            }
            .padding(10)
            .background(Color.orange.opacity(0.09))
            .overlay(Rectangle().frame(height: 1).foregroundStyle(Color.orange.opacity(0.3)), alignment: .bottom)
        }
    }

    private func apply() async {
        let modes = model.pendingApplyModes
        if modes.contains("redeploy_rime") { await model.run(action: "redeploy_rime") }
        if modes.contains("restart_predictor") { await model.run(action: "restart_predictor") }
        if modes.contains("restart_sidecar") { await model.run(action: "restart_sidecar") }
        if modes.contains("restart_input_method") { await model.run(action: "register_input_source") }
    }
}

struct EmptyState: View {
    let symbol: String
    let text: String

    var body: some View {
        VStack(spacing: 10) {
            Image(systemName: symbol).font(.system(size: 28)).foregroundStyle(.secondary)
            Text(text).foregroundStyle(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}
