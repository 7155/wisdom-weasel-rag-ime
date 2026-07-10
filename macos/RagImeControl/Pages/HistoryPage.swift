import SwiftUI

struct HistoryPage: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(title: "历史与反馈", subtitle: "理解预测为何出现、被忽略或被丢弃")
                Spacer()
                Text("默认只显示 hash、字数和脱敏摘要").font(.caption).foregroundStyle(.secondary)
            }
            .padding(20)
            Divider()
            if model.historyRows.isEmpty {
                EmptyState(symbol: "clock", text: "还没有可展示的历史")
            } else {
                PaginatedTable(
                    columns: ["时间", "App", "上下文摘要", "来源", "Group"],
                    rows: model.historyRows.enumerated().map {
                        TableRow(index: $0.offset, payload: $0.element, columns: ["createdAtMs", "app", "textPreview", "source", "groupLevel"])
                    }
                )
                .padding(16)
                HStack {
                    Text("已加载 \(model.historyRows.count) 条").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if !model.historyNextCursor.isEmpty {
                        Button("加载更多") { Task { await model.loadHistory(reset: false) } }
                    }
                }
                .padding(.horizontal, 16).padding(.bottom, 16)
            }
        }
    }
}
