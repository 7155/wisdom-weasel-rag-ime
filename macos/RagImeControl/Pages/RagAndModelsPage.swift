import SwiftUI

struct RagAndModelsPage: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(title: "RAG 与模型", subtitle: "控制召回通道、模型预算并解释一次测试查询")
                Spacer()
                Toggle("专家模式", isOn: $model.expertMode).toggleStyle(.switch)
            }
            .padding(20)
            PendingApplyBanner()
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    ForEach(model.sections(ids: ["rag", "models", "memory"])) { section in
                        SchemaSectionView(section: section)
                        Divider()
                    }
                    queryLab
                }
                .padding(24)
                .frame(maxWidth: 780, alignment: .leading)
            }
        }
    }

    private var queryLab: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("查询实验室").font(.headline)
            TextEditor(text: $model.queryLabText)
                .font(.body)
                .frame(height: 88)
                .padding(6)
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color(nsColor: .separatorColor)))
            HStack {
                Button {
                    Task { await model.runQueryLab() }
                } label: {
                    Label("运行本地预览", systemImage: "play.fill")
                }
                Spacer()
                Text("不会修改真实前台事务").font(.caption).foregroundStyle(.secondary)
            }
            if let result = model.queryLabResult {
                VStack(alignment: .leading, spacing: 6) {
                    LabeledContent("最终候选", value: "\(result.candidates?.count ?? 0)")
                    LabeledContent("被过滤", value: "\(result.blocked?.count ?? 0)")
                    if let error = result.error { Text(error).foregroundStyle(.red) }
                }
                .padding(12)
                .background(Color(nsColor: .controlBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 8))
            }
        }
    }
}
