import SwiftUI

enum ControlDesign {
    static let contentMaxWidth: CGFloat = 1160
    static let pageHorizontalPadding: CGFloat = 34
    static let pageVerticalPadding: CGFloat = 28
    static let sectionSpacing: CGFloat = 26
    static let surfaceRadius: CGFloat = 8
    static let brand = Color(red: 0.06, green: 0.55, blue: 0.58)
    static let quietSurface = Color(nsColor: .controlBackgroundColor)
    static let hairline = Color(nsColor: .separatorColor).opacity(0.58)
}

struct PageHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(.system(size: 29, weight: .semibold)).lineLimit(1)
            Text(subtitle).font(.system(size: 14.5)).foregroundStyle(.secondary).lineLimit(2)
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

struct ControlSurface<Content: View>: View {
    private let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .background(ControlDesign.quietSurface)
            .clipShape(RoundedRectangle(cornerRadius: ControlDesign.surfaceRadius))
            .overlay(
                RoundedRectangle(cornerRadius: ControlDesign.surfaceRadius)
                    .stroke(ControlDesign.hairline, lineWidth: 0.7)
            )
    }
}

struct ControlReadinessItem: View {
    let title: String
    let detail: String
    let symbol: String
    let ready: Bool

    var body: some View {
        HStack(spacing: 11) {
            Image(systemName: symbol)
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(ready ? ControlDesign.brand : Color.orange)
                .frame(width: 28, height: 28)
                .background((ready ? ControlDesign.brand : Color.orange).opacity(0.09))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.callout.weight(.semibold)).lineLimit(1)
                Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
            Spacer(minLength: 6)
            Circle()
                .fill(ready ? Color.green : Color.orange)
                .frame(width: 7, height: 7)
        }
        .frame(maxWidth: .infinity, minHeight: 58, alignment: .leading)
        .padding(.horizontal, 14)
    }
}

struct ControlMetricItem: View {
    let title: String
    let value: String
    let detail: String
    let symbol: String
    var tint: Color = ControlDesign.brand

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 17, weight: .medium))
                .foregroundStyle(tint)
                .frame(width: 24)
            VStack(alignment: .leading, spacing: 2) {
                HStack(alignment: .firstTextBaseline, spacing: 7) {
                    Text(value)
                        .font(.system(size: 23, weight: .semibold, design: .rounded))
                        .monospacedDigit()
                        .lineLimit(1)
                        .minimumScaleFactor(0.72)
                        .fixedSize(horizontal: true, vertical: false)
                    Text(title).font(.callout).foregroundStyle(.secondary)
                }
                Text(detail).font(.caption).foregroundStyle(.tertiary).lineLimit(1)
            }
            Spacer(minLength: 4)
        }
        .frame(maxWidth: .infinity, minHeight: 74, alignment: .leading)
        .padding(.horizontal, 16)
    }
}

struct ControlShortcutKey: View {
    let text: String

    var body: some View {
        Text(text)
            .font(.caption.monospaced().weight(.semibold))
            .foregroundStyle(ControlDesign.brand)
            .padding(.horizontal, 8)
            .padding(.vertical, 5)
            .background(ControlDesign.brand.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 5))
            .overlay(
                RoundedRectangle(cornerRadius: 5)
                    .stroke(ControlDesign.brand.opacity(0.24), lineWidth: 0.7)
            )
    }
}

struct ControlNoticeBanner: View {
    enum Kind: Equatable {
        case error
        case report

        var color: Color { self == .error ? .orange : ControlDesign.brand }
        var symbol: String { self == .error ? "exclamationmark.triangle.fill" : "checkmark.circle.fill" }
    }

    let kind: Kind
    let title: String
    let detail: String
    let onDismiss: () -> Void

    var body: some View {
        HStack(spacing: 11) {
            Image(systemName: kind.symbol).foregroundStyle(kind.color)
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.callout.weight(.semibold))
                Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
            }
            Spacer()
            Button(action: onDismiss) {
                Image(systemName: "xmark").frame(width: 24, height: 24)
            }
            .buttonStyle(.plain)
            .help("关闭")
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 10)
        .background(kind.color.opacity(0.08))
        .overlay(Rectangle().fill(kind.color.opacity(0.36)).frame(height: 1), alignment: .bottom)
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
