import SwiftUI

struct MemoryPage: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                PageHeader(title: "记忆", subtitle: "查看、纠正和治理可用于输入法的长期记忆")
                Spacer()
                if let summary = model.overview?.memory {
                    Text("\(summary.memoryBookCount) Books · \(summary.memoryAtomCount) 原子")
                        .font(.callout).foregroundStyle(.secondary)
                }
            }
            .padding(20)
            Divider()
            Picker("记忆类型", selection: $model.memoryKind) {
                Text("Memory Books").tag("books")
                Text("记忆原子").tag("atoms")
                Text("可用短语").tag("phrases")
                Text("Context Groups").tag("groups")
                Text("负向记忆").tag("negative")
            }
            .pickerStyle(.segmented)
            .padding(16)
            .onChange(of: model.memoryKind) { _ in Task { await model.loadMemory() } }

            if model.memoryRows.isEmpty {
                EmptyState(symbol: "brain", text: "当前分类没有记录")
            } else {
                PaginatedTable(columns: columnTitles, rows: tableRows)
                    .padding(.horizontal, 16)
                HStack {
                    Text("已加载 \(model.memoryRows.count) 条，原文默认脱敏").font(.caption).foregroundStyle(.secondary)
                    Spacer()
                    if !model.memoryNextCursor.isEmpty {
                        Button("加载更多") { Task { await model.loadMemory(reset: false) } }
                    }
                }
                .padding(16)
            }
        }
    }

    private var columnKeys: [String] {
        switch model.memoryKind {
        case "books": return ["title", "type", "project", "status", "quality_score"]
        case "atoms": return ["textPreview", "type", "project", "status", "confidence"]
        case "phrases": return ["textPreview", "useCount", "last_seen_ms"]
        case "groups": return ["id", "level", "project", "app", "event_count"]
        default: return ["value", "type", "reason", "created_at_ms"]
        }
    }

    private var columnTitles: [String] {
        switch model.memoryKind {
        case "books": return ["标题", "类型", "项目", "状态", "质量"]
        case "atoms": return ["内容摘要", "类型", "项目", "状态", "置信度"]
        case "phrases": return ["短语", "使用次数", "最近使用"]
        case "groups": return ["Group", "层级", "项目", "App", "事件数"]
        default: return ["屏蔽项", "类型", "原因", "创建时间"]
        }
    }

    private var tableRows: [TableRow] {
        model.memoryRows.enumerated().map { TableRow(index: $0.offset, payload: $0.element, columns: columnKeys) }
    }
}
