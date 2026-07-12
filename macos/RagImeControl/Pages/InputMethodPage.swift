import SwiftUI

struct InputMethodPage: View {
    @EnvironmentObject private var model: AppModel
    @State private var confirmingLexiconApply = false

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(title: "输入法", subtitle: "管理提交后预测、快捷键、候选界面与模糊音")
                Spacer()
            }
            .padding(20)
            PendingApplyBanner()
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    lexiconReview
                    Divider()
                    ForEach(model.sections(ids: ["interaction", "display", "activeRag", "pinyin"])) { section in
                        SchemaSectionView(section: section)
                        Divider()
                    }
                }
                .padding(24)
                .frame(maxWidth: 760, alignment: .leading)
            }
        }
    }

    private var lexiconReview: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("词库建议", systemImage: "character.book.closed")
                    .font(.system(size: 16, weight: .semibold))
                Spacer()
                Text(model.rimeLexiconStatus)
                    .font(.caption.monospacedDigit())
                    .foregroundStyle(.secondary)
                Button {
                    Task { await model.loadRimeLexiconReview() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .buttonStyle(.borderless)
                .help("刷新建议")
            }

            if let review = model.rimeLexiconReview, !review.entries.isEmpty {
                VStack(spacing: 0) {
                    ForEach(review.entries) { entry in
                        Toggle(
                            isOn: Binding(
                                get: { model.selectedRimeLexiconKeys.contains(entry.reviewKey) },
                                set: { model.setRimeLexiconSelection(entry.reviewKey, selected: $0) }
                            )
                        ) {
                            HStack(spacing: 12) {
                                Image(systemName: entry.reviewSource?.contains("dsv4") == true ? "sparkles" : "text.badge.checkmark")
                                    .foregroundStyle(entry.reviewSource?.contains("dsv4") == true ? Color.purple : Color.blue)
                                    .frame(width: 18)
                                Text(entry.text)
                                    .font(.body.weight(.medium))
                                    .frame(minWidth: 100, alignment: .leading)
                                Text(entry.pinyin)
                                    .font(.callout.monospaced())
                                    .foregroundStyle(.secondary)
                                    .lineLimit(1)
                                Spacer()
                                Text(entry.reviewSource?.contains("dsv4") == true ? "智能审阅" : "\(entry.positiveCount) 次")
                                    .font(.caption.monospacedDigit())
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .help(entry.reviewReason ?? "来自真实选词反馈")
                        .toggleStyle(.checkbox)
                        .padding(.vertical, 10)
                        if entry.id != review.entries.last?.id { Divider() }
                    }
                }

                HStack(spacing: 10) {
                    Button {
                        confirmingLexiconApply = true
                    } label: {
                        Label("应用已选", systemImage: "checkmark.circle")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.selectedRimeLexiconKeys.isEmpty || model.rimeLexiconBusy)

                    if !model.rimeLexiconRollbackId.isEmpty {
                        Button {
                            Task { await model.rollbackRimeLexiconReview() }
                        } label: {
                            Label("回滚", systemImage: "arrow.uturn.backward")
                        }
                        .disabled(model.rimeLexiconBusy)
                    }
                    Spacer()
                    Text("已选 \(model.selectedRimeLexiconKeys.count) / \(review.entryCount)")
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
            } else {
                HStack(spacing: 10) {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                    Text("暂无待审建议").foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(.vertical, 10)
            }
        }
        .confirmationDialog(
            "应用已选词库建议？",
            isPresented: $confirmingLexiconApply,
            titleVisibility: .visible
        ) {
            Button("应用并重新部署 Rime") {
                Task { await model.applyRimeLexiconReview() }
            }
            Button("取消", role: .cancel) {}
        }
    }
}
