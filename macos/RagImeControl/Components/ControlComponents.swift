import SwiftUI

struct PageHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(title).font(.system(size: 27, weight: .semibold)).lineLimit(1)
            Text(subtitle).font(.system(size: 14)).foregroundStyle(.secondary).lineLimit(2)
        }
    }
}

struct ControlSectionHeader: View {
    let title: String
    var trailing: String = ""

    var body: some View {
        HStack {
            Text(title).font(.system(size: 16, weight: .semibold))
            Spacer()
            if !trailing.isEmpty {
                Text(trailing).font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            }
        }
    }
}

struct ControlMetricTile: View {
    let title: String
    let value: String
    let detail: String
    let symbol: String
    var tint: Color = .blue

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: symbol)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(tint)
                Spacer()
                Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Text(value)
                .font(.system(size: 27, weight: .semibold, design: .rounded))
                .monospacedDigit()
            Text(title).font(.callout).foregroundStyle(.secondary)
        }
        .padding(16)
        .frame(maxWidth: .infinity, minHeight: 124, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor).opacity(0.65), lineWidth: 0.7))
    }
}

struct ControlReadinessTile: View {
    let title: String
    let detail: String
    let symbol: String
    let ready: Bool

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Image(systemName: symbol)
                    .font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(ready ? Color.green : Color.orange)
                Spacer()
                Circle().fill(ready ? Color.green : Color.orange).frame(width: 8, height: 8)
            }
            Text(title).font(.headline)
            Text(detail)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(2)
                .frame(minHeight: 30, alignment: .topLeading)
        }
        .padding(15)
        .frame(maxWidth: .infinity, minHeight: 112, alignment: .leading)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor).opacity(0.65), lineWidth: 0.7))
    }
}

struct StatusRow: View {
    let status: ComponentStatus

    private var degraded: Bool { status.status == "degraded" }

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: status.ok && !degraded ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(degraded ? Color.orange : (status.ok ? Color.green : Color.red))
                .frame(width: 18)
            Text(label).frame(width: 120, alignment: .leading)
            Text(status.detail).foregroundStyle(.secondary).lineLimit(1).truncationMode(.tail)
            Spacer()
            Text(degraded ? "降级" : (status.ok ? "就绪" : "检查"))
                .font(.caption.weight(.medium))
                .foregroundStyle(degraded ? Color.orange : (status.ok ? Color.secondary : Color.red))
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

struct SourceLaneLabel: View {
    let source: String

    var body: some View {
        Label(title, systemImage: symbol)
            .font(.caption.weight(.medium))
            .foregroundStyle(color)
            .help(helpText)
    }

    private var normalized: String { source.lowercased() }

    private var title: String {
        if normalized.contains("deepseek") || normalized == "ds" { return "生成" }
        if normalized.contains("rag") { return "RAG" }
        if normalized.contains("memory") { return "记忆" }
        return "模型"
    }

    private var symbol: String {
        switch title {
        case "生成": return "bolt.horizontal.circle"
        case "RAG": return "doc.text.magnifyingglass"
        case "记忆": return "clock.arrow.circlepath"
        default: return "sparkles"
        }
    }

    private var color: Color {
        switch title {
        case "生成": return .indigo
        case "RAG": return .teal
        case "记忆": return .orange
        default: return .blue
        }
    }

    private var helpText: String {
        switch title {
        case "生成": return "知识生成"
        case "RAG": return "本地知识召回"
        case "记忆": return "个人记忆候选"
        default: return "本地实时补全"
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
