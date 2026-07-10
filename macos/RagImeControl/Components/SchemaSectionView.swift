import SwiftUI

struct SchemaSectionView: View {
    @EnvironmentObject private var model: AppModel
    let section: SettingsSection

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text(title).font(.headline).padding(.bottom, 8)
            ForEach(visibleFields) { field in
                SchemaFieldView(field: field)
                if field.id != visibleFields.last?.id { Divider() }
            }
        }
        .padding(.vertical, 8)
    }

    private var visibleFields: [SettingsField] {
        section.fields.filter { model.expertMode || !$0.expert }
    }

    private var title: String {
        ["interaction": "基本行为与快捷键", "display": "候选界面", "pinyin": "拼音", "rag": "RAG", "models": "模型", "activeRag": "显式生成", "memory": "记忆"].first { $0.key == section.id }?.value ?? section.label
    }
}
