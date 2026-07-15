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
            .padding(.horizontal, ControlDesign.pageHorizontalPadding)
            .padding(.vertical, 20)

            PendingApplyBanner()
            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: ControlDesign.sectionSpacing) {
                    lexiconReview
                    ForEach(model.sections(ids: ["interaction", "display", "activeRag", "pinyin"])) { section in
                        ControlSettingsSection(section: section)
                    }
                }
                .padding(.horizontal, ControlDesign.pageHorizontalPadding)
                .padding(.vertical, ControlDesign.pageVerticalPadding)
                .frame(maxWidth: 920, alignment: .leading)
                .frame(maxWidth: .infinity)
            }
        }
    }

    private var lexiconReview: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack(spacing: 12) {
                ControlSectionHeader(
                    title: "词库建议",
                    trailing: model.rimeLexiconStatus
                )
                if model.rimeLexiconBusy {
                    ProgressView().controlSize(.small)
                }
                Button {
                    Task { await model.loadRimeLexiconReview() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                        .frame(width: ControlDesign.iconButtonSize, height: ControlDesign.iconButtonSize)
                }
                .buttonStyle(.plain)
                .help("刷新建议")
                .disabled(model.rimeLexiconBusy)
            }

            ControlSurface {
                if let review = model.rimeLexiconReview, !review.entries.isEmpty {
                    VStack(spacing: 0) {
                        lexiconColumnHeader
                        Divider()
                        ForEach(review.entries) { entry in
                            lexiconRow(entry)
                            if entry.id != review.entries.last?.id {
                                Divider().padding(.leading, 44)
                            }
                        }
                        Divider()
                        lexiconActions(review)
                    }
                } else {
                    HStack(spacing: 10) {
                        Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                        Text("暂无待审建议")
                            .font(ControlDesign.bodyFont)
                            .foregroundStyle(.secondary)
                        Spacer()
                    }
                    .padding(.horizontal, 16)
                    .frame(minHeight: 58)
                }
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

    private var lexiconColumnHeader: some View {
        HStack(spacing: 14) {
            Color.clear.frame(width: 20, height: 1)
            Color.clear.frame(width: 20, height: 1)
            Text("词条")
                .frame(maxWidth: .infinity, alignment: .leading)
            Text("拼音")
                .frame(width: 210, alignment: .leading)
            Text("依据")
                .frame(width: 108, alignment: .trailing)
        }
        .font(ControlDesign.metadataFont.weight(.medium))
        .foregroundStyle(.secondary)
        .padding(.horizontal, 16)
        .frame(height: 36)
    }

    private func lexiconRow(_ entry: RimeLexiconReviewEntry) -> some View {
        HStack(spacing: 14) {
            Toggle(
                "",
                isOn: Binding(
                get: { model.selectedRimeLexiconKeys.contains(entry.reviewKey) },
                set: { model.setRimeLexiconSelection(entry.reviewKey, selected: $0) }
                )
            )
            .labelsHidden()
            .toggleStyle(.checkbox)
            .frame(width: 20)

            Image(systemName: entry.reviewSource?.contains("dsv4") == true ? "sparkles" : "text.badge.checkmark")
                .foregroundStyle(entry.reviewSource?.contains("dsv4") == true ? Color.purple : Color.blue)
                .frame(width: 20)
            Text(entry.text)
                .font(ControlDesign.bodyFont.weight(.medium))
                .frame(maxWidth: .infinity, alignment: .leading)
                .lineLimit(1)
            Text(entry.pinyin)
                .font(ControlDesign.detailFont.monospaced())
                .foregroundStyle(.secondary)
                .frame(width: 210, alignment: .leading)
                .lineLimit(1)
            Text(entry.reviewSource?.contains("dsv4") == true ? "智能审阅" : "\(entry.positiveCount) 次")
                .font(ControlDesign.metadataFont.monospacedDigit())
                .foregroundStyle(.secondary)
                .frame(width: 108, alignment: .trailing)
        }
        .help(entry.reviewReason ?? "来自真实选词反馈")
        .padding(.horizontal, 16)
        .frame(minHeight: 48)
    }

    private func lexiconActions(_ review: RimeLexiconReviewResponse) -> some View {
        HStack(spacing: 10) {
            Button {
                confirmingLexiconApply = true
            } label: {
                Label("应用已选", systemImage: "checkmark.circle")
                    .frame(minWidth: 80)
            }
            .buttonStyle(.borderedProminent)
            .controlSize(.regular)
            .disabled(model.selectedRimeLexiconKeys.isEmpty || model.rimeLexiconBusy)

            if !model.rimeLexiconRollbackId.isEmpty {
                Button {
                    Task { await model.rollbackRimeLexiconReview() }
                } label: {
                    Label("回滚", systemImage: "arrow.uturn.backward")
                        .frame(minWidth: 64)
                }
                .controlSize(.regular)
                .disabled(model.rimeLexiconBusy)
            }

            Spacer()
            Text("已选 \(model.selectedRimeLexiconKeys.count) / \(review.entryCount)")
                .font(ControlDesign.metadataFont.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 16)
        .frame(minHeight: 54)
    }
}
