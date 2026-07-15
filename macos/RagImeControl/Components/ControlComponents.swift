import SwiftUI

enum ControlDesign {
    static let contentMaxWidth: CGFloat = 1160
    static let pageHorizontalPadding: CGFloat = 34
    static let pageVerticalPadding: CGFloat = 28
    static let sectionSpacing: CGFloat = 26
    static let surfaceRadius: CGFloat = 8
    static let controlHeight: CGFloat = 34
    static let iconButtonSize: CGFloat = 32
    static let valueColumnWidth: CGFloat = 260
    static let pageTitleFont = Font.system(size: 29, weight: .semibold)
    static let sectionTitleFont = Font.system(size: 18, weight: .semibold)
    static let bodyFont = Font.system(size: 15)
    static let detailFont = Font.system(size: 14)
    static let metadataFont = Font.system(size: 13)
    static let brand = Color(red: 0.06, green: 0.55, blue: 0.58)
    static let quietSurface = Color(nsColor: .controlBackgroundColor)
    static let hairline = Color(nsColor: .separatorColor).opacity(0.58)
}

struct PageHeader: View {
    let title: String
    let subtitle: String

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Text(title).font(ControlDesign.pageTitleFont).lineLimit(1)
            Text(subtitle).font(ControlDesign.detailFont).foregroundStyle(.secondary).lineLimit(2)
        }
    }
}

struct ControlSectionHeader: View {
    let title: String
    var trailing: String = ""

    var body: some View {
        HStack {
            Text(title).font(ControlDesign.sectionTitleFont)
            Spacer()
            if !trailing.isEmpty {
                Text(trailing).font(ControlDesign.metadataFont.monospacedDigit()).foregroundStyle(.secondary)
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

/// Stable two-column row for native management surfaces. The value column has
/// one shared width so toggles, pickers, shortcut recorders, and buttons do not
/// drift as labels change.
struct ControlLabelValueRow<Value: View>: View {
    let label: String
    let detail: String
    private let value: Value

    init(
        _ label: String,
        detail: String = "",
        @ViewBuilder value: () -> Value
    ) {
        self.label = label
        self.detail = detail
        self.value = value()
    }

    var body: some View {
        HStack(alignment: .center, spacing: 24) {
            VStack(alignment: .leading, spacing: 3) {
                Text(label)
                    .font(ControlDesign.bodyFont.weight(.medium))
                if !detail.isEmpty {
                    Text(detail)
                        .font(ControlDesign.metadataFont)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            value
                .frame(width: ControlDesign.valueColumnWidth, alignment: .trailing)
        }
        .frame(maxWidth: .infinity, minHeight: 52, alignment: .leading)
        .padding(.vertical, 6)
    }
}

struct ControlSettingsSection: View {
    @EnvironmentObject private var model: AppModel
    let section: SettingsSection

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ControlSectionHeader(title: title)
            ControlSurface {
                VStack(spacing: 0) {
                    ForEach(visibleFields) { field in
                        ControlSettingsFieldRow(field: field)
                            .padding(.horizontal, 16)
                        if field.id != visibleFields.last?.id {
                            Divider()
                        }
                    }
                }
            }
        }
    }

    private var visibleFields: [SettingsField] {
        section.fields.filter { model.expertMode || !$0.expert }
    }

    private var title: String {
        [
            "interaction": "基本行为与快捷键",
            "display": "候选界面",
            "pinyin": "拼音",
            "rag": "RAG",
            "models": "模型",
            "activeRag": "显式生成",
            "memory": "记忆",
        ].first { $0.key == section.id }?.value ?? section.label
    }
}

private struct ControlSettingsFieldRow: View {
    @EnvironmentObject private var model: AppModel
    let field: SettingsField

    var body: some View {
        ControlLabelValueRow(field.label, detail: field.description) {
            control
        }
    }

    @ViewBuilder
    private var control: some View {
        switch field.type {
        case "boolean":
            Toggle("", isOn: boolBinding)
                .labelsHidden()
                .frame(width: ControlDesign.valueColumnWidth, alignment: .trailing)
        case "integer", "float":
            Stepper(value: numberBinding, in: numberRange, step: field.step ?? 1) {
                Text(numberLabel)
                    .font(ControlDesign.bodyFont.monospacedDigit())
                    .frame(maxWidth: .infinity, alignment: .trailing)
            }
            .frame(width: ControlDesign.valueColumnWidth)
        case "enum":
            Picker("", selection: stringBinding) {
                ForEach(field.options ?? [], id: \.self) { option in
                    Text(optionLabel(option)).tag(option)
                }
            }
            .labelsHidden()
            .frame(width: ControlDesign.valueColumnWidth)
        case "shortcut":
            ShortcutRecorder(value: stringBinding)
                .frame(width: ControlDesign.valueColumnWidth, height: ControlDesign.controlHeight)
        default:
            TextField("", text: stringBinding)
                .textFieldStyle(.roundedBorder)
                .font(ControlDesign.bodyFont)
                .frame(width: ControlDesign.valueColumnWidth)
        }
    }

    private var boolBinding: Binding<Bool> {
        Binding(
            get: { model.value(for: field).boolValue },
            set: { value in Task { await model.update(field: field, value: .bool(value)) } }
        )
    }

    private var numberBinding: Binding<Double> {
        Binding(
            get: { model.value(for: field).numberValue },
            set: { value in Task { await model.update(field: field, value: .number(value)) } }
        )
    }

    private var stringBinding: Binding<String> {
        Binding(
            get: { model.value(for: field).stringValue },
            set: { value in Task { await model.update(field: field, value: .string(value)) } }
        )
    }

    private var numberRange: ClosedRange<Double> {
        (field.min ?? 0)...(field.max ?? 10_000)
    }

    private var numberLabel: String {
        let value = model.value(for: field).numberValue
        let number = field.type == "integer" ? String(Int(value)) : String(format: "%.2f", value)
        return field.unit.isEmpty ? number : "\(number) \(field.unit)"
    }

    private func optionLabel(_ option: String) -> String {
        let labels = [
            "compact": "紧凑",
            "expanded": "展开",
            "pass_through": "输入数字",
            "select_prediction": "选择预测",
            "accept_top_prediction": "接受第一项",
            "rime_default": "Rime 默认",
            "disabled": "关闭",
            "sichuan-mild": "四川轻度",
            "none": "关闭",
            "replace_selection": "替换选区",
            "insert_after_selection": "选区后插入",
            "show_only": "仅显示",
        ]
        return labels[option] ?? option
    }
}

struct ControlDetailRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack(alignment: .firstTextBaseline, spacing: 18) {
            Text(label)
                .font(ControlDesign.metadataFont.weight(.medium))
                .foregroundStyle(.secondary)
                .frame(width: 104, alignment: .leading)
            Text(value.isEmpty ? "未设置" : value)
                .font(ControlDesign.bodyFont)
                .textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding(.vertical, 4)
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
                Text(detail).font(ControlDesign.metadataFont).foregroundStyle(.secondary).lineLimit(1)
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
                Text(detail).font(ControlDesign.metadataFont).foregroundStyle(.tertiary).lineLimit(1)
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
            .font(ControlDesign.metadataFont.monospaced().weight(.semibold))
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
                Text(detail).font(ControlDesign.metadataFont).foregroundStyle(.secondary).lineLimit(2)
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
                Text(detail).font(ControlDesign.metadataFont).foregroundStyle(.secondary).lineLimit(1)
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
                .font(ControlDesign.metadataFont)
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
                .font(ControlDesign.metadataFont.weight(.medium))
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
            .font(ControlDesign.metadataFont.weight(.medium))
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
