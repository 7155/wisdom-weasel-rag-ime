import SwiftUI

struct SchemaFieldView: View {
    @EnvironmentObject private var model: AppModel
    let field: SettingsField

    var body: some View {
        HStack(alignment: .center, spacing: 14) {
            VStack(alignment: .leading, spacing: 3) {
                Text(field.label)
                Text(field.description)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            Spacer(minLength: 20)
            control
                .frame(maxWidth: 250, alignment: .trailing)
        }
        .padding(.vertical, 8)
    }

    @ViewBuilder
    private var control: some View {
        switch field.type {
        case "boolean":
            Toggle("", isOn: boolBinding).labelsHidden()
        case "integer", "float":
            HStack(spacing: 8) {
                Stepper("", value: numberBinding, in: (field.min ?? 0)...(field.max ?? 10000), step: field.step ?? 1)
                    .labelsHidden()
                Text(numberLabel).monospacedDigit().frame(minWidth: 68, alignment: .trailing)
            }
        case "enum":
            Picker("", selection: stringBinding) {
                ForEach(field.options ?? [], id: \.self) { Text(optionLabel($0)).tag($0) }
            }
            .labelsHidden()
            .frame(width: 190)
        case "shortcut":
            ShortcutRecorder(value: stringBinding).frame(width: 150, height: 28)
        default:
            TextField("", text: stringBinding)
                .textFieldStyle(.roundedBorder)
                .frame(width: 190)
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

    private var numberLabel: String {
        let value = model.value(for: field).numberValue
        let number = field.type == "integer" ? String(Int(value)) : String(format: "%.2f", value)
        return field.unit.isEmpty ? number : "\(number) \(field.unit)"
    }

    private func optionLabel(_ option: String) -> String {
        let labels = [
            "compact": "紧凑", "expanded": "展开", "pass_through": "输入数字",
            "select_prediction": "选择预测", "accept_top_prediction": "接受第一项",
            "rime_default": "Rime 默认", "disabled": "关闭", "sichuan-mild": "四川轻度",
            "none": "关闭", "replace_selection": "替换选区", "insert_after_selection": "选区后插入",
            "show_only": "仅显示"
        ]
        return labels[option] ?? option
    }
}
