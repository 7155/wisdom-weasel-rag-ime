import SwiftUI

struct MemoryPage: View {
    @EnvironmentObject private var model: AppModel
    @State private var editingItem: [String: JSONValue] = [:]
    @State private var editorPresented = false
    @State private var pendingAction: PendingMemoryAction?
    @State private var detailSelection: MemoryDetailSelection?
    @State private var tagPresentation = "network"

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            kindPicker
            Divider()
            content
        }
        .sheet(isPresented: $editorPresented) {
            MemoryEditorSheet(
                kind: model.memoryKind,
                item: editingItem,
                mergeCandidates: model.memoryRows,
                saving: model.memorySaving,
                onCancel: { editorPresented = false },
                onSave: { draft in
                    Task {
                        let saved = await model.editMemoryItem(
                            kind: model.memoryKind,
                            id: draft.id,
                            title: draft.title,
                            detail: draft.detail,
                            tags: draft.tags,
                            aliases: draft.aliases,
                            type: draft.type,
                            color: draft.color,
                            active: draft.active,
                            mergeIntoId: draft.mergeIntoId
                        )
                        if saved { editorPresented = false }
                    }
                }
            )
        }
        .sheet(item: $detailSelection) { selection in
            MemoryDetailSheet(kind: selection.kind, item: selection.item) {
                detailSelection = nil
            }
        }
        .alert(item: $pendingAction) { pending in
            Alert(
                title: Text(pending.title),
                message: Text(pending.message),
                primaryButton: .destructive(Text(pending.confirmLabel)) {
                    Task {
                        _ = await model.performMemoryAction(
                            id: pending.memoryId,
                            kind: pending.kind,
                            action: pending.action
                        )
                    }
                },
                secondaryButton: .cancel(Text("取消"))
            )
        }
    }

    private var header: some View {
        HStack(spacing: 14) {
            PageHeader(title: "记忆", subtitle: "个人知识、输入习惯与上下文分组")
            Spacer()
            if let summary = model.overview?.memory {
                metric(symbol: "books.vertical", value: summary.memoryBookCount, label: "主题")
                metric(symbol: "circle.hexagongrid", value: summary.memoryAtomCount, label: "记忆")
                metric(symbol: "clock.arrow.circlepath", value: summary.pendingCompileEvents, label: "待整理")
            }
        }
        .padding(.horizontal, 28)
        .padding(.vertical, 22)
    }

    private var kindPicker: some View {
        Picker("记忆类型", selection: $model.memoryKind) {
            Label("主题书", systemImage: "books.vertical").tag("books")
            Label("记忆", systemImage: "circle.hexagongrid").tag("atoms")
            Label("标签", systemImage: "tag").tag("tags")
            Label("短语", systemImage: "text.quote").tag("phrases")
            Label("分组", systemImage: "square.grid.2x2").tag("groups")
            Label("屏蔽", systemImage: "eye.slash").tag("negative")
        }
        .pickerStyle(.segmented)
        .padding(.horizontal, 28)
        .padding(.vertical, 14)
        .onChange(of: model.memoryKind) { _ in Task { await model.loadMemory() } }
    }

    @ViewBuilder
    private var content: some View {
        if model.memoryRows.isEmpty {
            EmptyState(symbol: symbolForKind, text: "当前分类没有记录")
        } else {
            ScrollView {
                Group {
                    switch model.memoryKind {
                    case "tags": tagContent
                    case "groups": groupGrid
                    default: itemList
                    }
                }
                .padding(.horizontal, 28)
                .padding(.vertical, 22)
                .frame(maxWidth: 1120, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)

                if !model.memoryNextCursor.isEmpty {
                    Button { Task { await model.loadMemory(reset: false) } } label: {
                        Label("加载更多", systemImage: "arrow.down.circle")
                    }
                    .padding(.bottom, 24)
                }
            }
        }
    }

    private var itemList: some View {
        LazyVStack(spacing: 10) {
            ForEach(Array(model.memoryRows.enumerated()), id: \.offset) { _, item in
                MemoryRecordRow(
                    kind: model.memoryKind,
                    item: item,
                    view: { openDetail(item) },
                    edit: { openEditor(item) },
                    action: { requestAction($0, for: item) }
                )
            }
        }
    }

    private var tagGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 190), spacing: 12)], spacing: 12) {
            ForEach(Array(model.memoryRows.enumerated()), id: \.offset) { _, item in
                MemoryTagTile(item: item, view: { openDetail(item) }, edit: { openEditor(item) })
            }
        }
    }

    private var tagContent: some View {
        VStack(alignment: .leading, spacing: 18) {
            Picker("标签视图", selection: $tagPresentation) {
                Label("关系图", systemImage: "point.3.connected.trianglepath.dotted").tag("network")
                Label("列表", systemImage: "list.bullet").tag("list")
            }
            .pickerStyle(.segmented)
            .frame(width: 220)
            HStack(spacing: 16) {
                Label("\(connectedTagCount) 个已联网", systemImage: "link")
                    .foregroundStyle(.teal)
                Label("\(isolatedTagCount) 个待整理", systemImage: "circle.dashed")
                    .foregroundStyle(isolatedTagCount > 0 ? .orange : .secondary)
                Spacer()
                Text("关系由审阅后的模型草案或用户编辑产生")
                    .foregroundStyle(.secondary)
            }
            .font(.caption)
            if tagPresentation == "network" {
                MemoryTagNetwork(items: model.memoryRows, view: openDetail)
            } else {
                tagGrid
            }
        }
    }

    private var connectedTagCount: Int {
        model.memoryRows.filter { Int($0["edge_count"]?.numberValue ?? 0) > 0 }.count
    }

    private var isolatedTagCount: Int {
        max(0, model.memoryRows.count - connectedTagCount)
    }

    private var groupGrid: some View {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 280), spacing: 12)], spacing: 12) {
            ForEach(Array(model.memoryRows.enumerated()), id: \.offset) { _, item in
                MemoryGroupTile(item: item, view: { openDetail(item) }, edit: { openEditor(item) })
            }
        }
    }

    private var symbolForKind: String {
        switch model.memoryKind {
        case "books": return "books.vertical"
        case "atoms": return "circle.hexagongrid"
        case "tags": return "tag"
        case "phrases": return "text.quote"
        case "groups": return "square.grid.2x2"
        default: return "eye.slash"
        }
    }

    private func openEditor(_ item: [String: JSONValue]) {
        editingItem = item
        editorPresented = true
    }

    private func openDetail(_ item: [String: JSONValue]) {
        detailSelection = MemoryDetailSelection(kind: model.memoryKind, item: item)
    }

    private func requestAction(_ action: String, for item: [String: JSONValue]) {
        let id = item["id"]?.stringValue ?? item["memoryId"]?.stringValue ?? ""
        guard !id.isEmpty else { return }
        let title = item["title"]?.stringValue
            ?? item["text"]?.stringValue
            ?? item["textPreview"]?.stringValue
            ?? "这条记忆"
        if model.memoryKind == "books", action == "restore" {
            pendingAction = PendingMemoryAction(
                memoryId: id,
                kind: model.memoryKind,
                action: "restore",
                title: "恢复这本主题书？",
                message: "恢复后会重新以正常权重参与检索。\n\(title)",
                confirmLabel: "恢复"
            )
            return
        }
        if model.memoryKind == "books", action == "archive" {
            pendingAction = PendingMemoryAction(
                memoryId: id,
                kind: model.memoryKind,
                action: "archive",
                title: "归档这本主题书？",
                message: "内容仍可查看和按时间检索，普通检索权重会降低。\n\(title)",
                confirmLabel: "归档"
            )
            return
        }
        switch action {
        case "enable":
            pendingAction = PendingMemoryAction(
                memoryId: id,
                kind: model.memoryKind,
                action: action,
                title: "恢复这条记忆？",
                message: "恢复后会重新进入检索与候选。\n\(title)",
                confirmLabel: "恢复"
            )
        case "disable":
            pendingAction = PendingMemoryAction(
                memoryId: id,
                kind: model.memoryKind,
                action: action,
                title: "标记为过期？",
                message: "内容会保留，但不再进入检索与候选。\n\(title)",
                confirmLabel: "标记过期"
            )
        default:
            pendingAction = PendingMemoryAction(
                memoryId: id,
                kind: model.memoryKind,
                action: "forget",
                title: "忘记这条内容？",
                message: "系统会写入可审计的屏蔽记录，不会直接物理删除。\n\(title)",
                confirmLabel: "忘记"
            )
        }
    }

    private func metric(symbol: String, value: Int, label: String) -> some View {
        HStack(spacing: 6) {
            Image(systemName: symbol).foregroundStyle(.blue)
            Text("\(value)").font(.system(.callout, design: .rounded).weight(.semibold))
            Text(label).font(.caption).foregroundStyle(.secondary)
        }
        .padding(.horizontal, 10)
        .frame(height: 32)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 7))
    }
}

private struct MemoryDetailSelection: Identifiable {
    let id = UUID()
    let kind: String
    let item: [String: JSONValue]
}

private struct PendingMemoryAction: Identifiable {
    let id = UUID()
    let memoryId: String
    let kind: String
    let action: String
    let title: String
    let message: String
    let confirmLabel: String
}

private struct MemoryRecordRow: View {
    let kind: String
    let item: [String: JSONValue]
    let view: () -> Void
    let edit: () -> Void
    let action: (String) -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: symbol)
                .font(.system(size: 18, weight: .medium))
                .foregroundStyle(color)
                .frame(width: 34, height: 34)
                .background(color.opacity(0.10))
                .clipShape(RoundedRectangle(cornerRadius: 7))

            VStack(alignment: .leading, spacing: 7) {
                HStack(spacing: 8) {
                    Text(title).font(.headline).lineLimit(2)
                    statusBadge
                    Spacer()
                }
                if !detail.isEmpty {
                    Text(detail)
                        .font(.callout)
                        .foregroundStyle(.secondary)
                        .lineLimit(kind == "books" ? 4 : 3)
                        .textSelection(.enabled)
                }
                if !tags.isEmpty {
                    HStack(spacing: 6) {
                        ForEach(tags.prefix(5), id: \.self) { tag in
                            Text(tag)
                                .font(.caption)
                                .foregroundStyle(.blue)
                                .padding(.horizontal, 7)
                                .frame(height: 22)
                                .background(Color.blue.opacity(0.08))
                                .clipShape(RoundedRectangle(cornerRadius: 5))
                        }
                    }
                }
                Text(metadata)
                    .font(.caption)
                    .foregroundStyle(.tertiary)
            }

            HStack(spacing: 10) {
                Button("查看详情", systemImage: "doc.text.magnifyingglass", action: view)
                    .buttonStyle(.borderless)
                Button(action: edit) { Image(systemName: "pencil") }
                    .buttonStyle(.borderless)
                    .help("编辑")
                if ["books", "atoms", "phrases"].contains(kind) {
                    Menu {
                        Button(statusIsInactive ? "恢复" : (kind == "books" ? "归档" : "标记过期")) {
                            action(statusIsInactive ? (kind == "books" ? "restore" : "enable") : (kind == "books" ? "archive" : "disable"))
                        }
                        Divider()
                        Button("忘记", role: .destructive) { action("forget") }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    .menuStyle(.borderlessButton)
                    .frame(width: 22)
                    .help("更多操作")
                }
            }
        }
        .padding(14)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor), lineWidth: 0.6))
    }

    private var symbol: String {
        switch kind {
        case "books": return "book.closed"
        case "atoms": return "circle.hexagongrid"
        case "phrases": return "quote.opening"
        default: return "eye.slash"
        }
    }

    private var color: Color {
        switch kind {
        case "books": return .blue
        case "atoms": return .teal
        case "phrases": return .green
        default: return .orange
        }
    }

    private var title: String {
        switch kind {
        case "books": return item["title"]?.stringValue ?? "未命名主题"
        case "atoms": return item["text"]?.stringValue ?? item["textPreview"]?.stringValue ?? "空记忆"
        case "phrases": return item["text"]?.stringValue ?? item["textPreview"]?.stringValue ?? "空短语"
        default: return item["value"]?.stringValue ?? "屏蔽规则"
        }
    }

    private var detail: String {
        switch kind {
        case "books": return item["summary"]?.stringValue ?? ""
        case "atoms":
            let confidence = Int((item["confidence"]?.numberValue ?? 0) * 100)
            return "来源事件 \(Int(item["sourceEventCount"]?.numberValue ?? 0)) 条 · 可信度 \(confidence)%"
        case "phrases": return "使用 \(Int(item["useCount"]?.numberValue ?? 0)) 次"
        default: return item["reason"]?.stringValue ?? ""
        }
    }

    private var tags: [String] {
        item["tags"]?.arrayValue.map(\.stringValue).filter { !$0.isEmpty } ?? []
    }

    private var metadata: String {
        let type = item["type"]?.stringValue ?? ""
        let project = item["project"]?.stringValue ?? ""
        let updated = memoryDate(item["updated_at_ms"]?.numberValue ?? item["updatedAtMs"]?.numberValue ?? 0)
        let sourceRange: String
        if kind == "books" {
            let start = memoryDate(item["sourceStartMs"]?.numberValue ?? 0)
            let end = memoryDate(item["sourceEndMs"]?.numberValue ?? 0)
            sourceRange = start.isEmpty ? "" : (start == end ? "来源 \(start)" : "来源 \(start) - \(end)")
        } else {
            sourceRange = ""
        }
        return [type, project, sourceRange, updated].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private var statusBadge: some View {
        Text(item["status"]?.stringValue ?? (item["active"]?.boolValue == false ? "停用" : "启用"))
            .font(.caption2.weight(.semibold))
            .foregroundStyle(.secondary)
            .padding(.horizontal, 6)
            .frame(height: 20)
            .background(Color.secondary.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 4))
    }

    private var statusIsInactive: Bool {
        ["archived", "disabled", "tombstoned", "expired"].contains(item["status"]?.stringValue ?? "")
    }
}

private struct MemoryTagNetwork: View {
    let items: [[String: JSONValue]]
    let view: ([String: JSONValue]) -> Void

    var body: some View {
        Group {
            if nodes.isEmpty {
                VStack(spacing: 10) {
                    Image(systemName: "point.3.connected.trianglepath.dotted")
                        .font(.system(size: 30))
                        .foregroundStyle(.secondary)
                    Text("还没有可展示的标签关系")
                        .font(.headline)
                    Text("下一次模型整理会先提出合并与关系草案，审阅应用后在这里形成网络。")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, minHeight: 300)
            } else {
                GeometryReader { proxy in
                    let points = positions(in: proxy.size)
                    ZStack {
                        Canvas { context, _ in
                            for edge in edges {
                                guard let start = points[edge.source], let end = points[edge.target] else { continue }
                                var path = Path()
                                path.move(to: start)
                                path.addLine(to: end)
                                context.stroke(
                                    path,
                                    with: .color(.teal.opacity(0.22 + min(0.30, edge.weight * 0.24))),
                                    lineWidth: 0.8 + edge.weight
                                )
                            }
                        }
                        ForEach(nodes) { node in
                            if let point = points[node.id] {
                                Button { view(node.item) } label: {
                                    VStack(spacing: 2) {
                                        Text(node.title)
                                            .font(.system(size: 12, weight: .semibold))
                                            .lineLimit(1)
                                        Text("\(node.degree) 连接 · \(node.itemCount) 记忆")
                                            .font(.system(size: 9))
                                            .foregroundStyle(.secondary)
                                    }
                                    .padding(.horizontal, 8)
                                    .frame(width: 112, height: 42)
                                    .background(.regularMaterial)
                                    .overlay(
                                        RoundedRectangle(cornerRadius: 6)
                                            .stroke(node.degree >= 3 ? Color.teal.opacity(0.72) : Color.blue.opacity(0.34), lineWidth: node.degree >= 3 ? 1.5 : 0.8)
                                    )
                                    .clipShape(RoundedRectangle(cornerRadius: 6))
                                }
                                .buttonStyle(.plain)
                                .position(point)
                                .help("查看 \(node.title) 的记忆与关系")
                            }
                        }
                    }
                }
                .frame(minHeight: 500)
                .background(Color(nsColor: .controlBackgroundColor).opacity(0.42))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor), lineWidth: 0.6))
            }
        }
    }

    private var nodes: [MemoryTagGraphNode] {
        let mapped: [MemoryTagGraphNode] = items.map { MemoryTagGraphNode($0) }
        let connected = mapped.filter { $0.degree > 0 }
        let sorted = connected.sorted { lhs, rhs in
            if lhs.degree == rhs.degree { return lhs.itemCount > rhs.itemCount }
            return lhs.degree > rhs.degree
        }
        return Array(sorted.prefix(20))
    }

    private var edges: [MemoryTagGraphEdge] {
        let visible = Set(nodes.map(\.id))
        var seen: Set<String> = []
        var result: [MemoryTagGraphEdge] = []
        for node in nodes {
            let connections = node.item["connections"]?.arrayValue.map(\.objectValue) ?? []
            for connection in connections {
                let target = connection["id"]?.stringValue ?? ""
                guard visible.contains(target), target != node.id else { continue }
                let relation = connection["type"]?.stringValue ?? "related_to"
                let endpoints = [node.id, target].sorted()
                let key = "\(endpoints[0])|\(endpoints[1])|\(relation)"
                guard seen.insert(key).inserted else { continue }
                result.append(
                    MemoryTagGraphEdge(
                        source: node.id,
                        target: target,
                        weight: connection["weight"]?.numberValue ?? 0.5
                    )
                )
            }
        }
        return result
    }

    private func positions(in size: CGSize) -> [String: CGPoint] {
        guard !nodes.isEmpty else { return [:] }
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        let maxRadiusX = max(80, size.width / 2 - 76)
        let maxRadiusY = max(80, size.height / 2 - 48)
        var result: [String: CGPoint] = [nodes[0].id: center]
        let goldenAngle = CGFloat.pi * (3 - sqrt(5.0))
        for (index, node) in nodes.dropFirst().enumerated() {
            let step = CGFloat(index + 1)
            let ratio = sqrt(step / CGFloat(max(1, nodes.count - 1)))
            let angle = step * goldenAngle
            result[node.id] = CGPoint(
                x: center.x + cos(angle) * maxRadiusX * ratio,
                y: center.y + sin(angle) * maxRadiusY * ratio
            )
        }
        return result
    }
}

private struct MemoryTagGraphNode: Identifiable {
    let item: [String: JSONValue]
    let id: String
    let title: String
    let degree: Int
    let itemCount: Int

    init(_ item: [String: JSONValue]) {
        self.item = item
        id = item["id"]?.stringValue ?? UUID().uuidString
        title = item["tag"]?.stringValue ?? "未命名"
        degree = Int(item["edge_count"]?.numberValue ?? 0)
        itemCount = Int(item["item_count"]?.numberValue ?? 0)
    }
}

private struct MemoryTagGraphEdge {
    let source: String
    let target: String
    let weight: Double
}

private struct MemoryTagTile: View {
    let item: [String: JSONValue]
    let view: () -> Void
    let edit: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "tag.fill").foregroundStyle(tagColor)
            VStack(alignment: .leading, spacing: 3) {
                Text(item["tag"]?.stringValue ?? "未命名标签").font(.headline).lineLimit(1)
                Text("关联 \(Int(item["item_count"]?.numberValue ?? 0)) · 连接 \(Int(item["edge_count"]?.numberValue ?? 0))")
                    .font(.caption).foregroundStyle(.secondary)
                if let description = item["description"]?.stringValue, !description.isEmpty {
                    Text(description)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(2)
                }
                if !aliases.isEmpty {
                    Text("别名：\(aliases.joined(separator: "、"))")
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                        .lineLimit(1)
                }
            }
            Spacer()
            Button("查看", systemImage: "doc.text.magnifyingglass", action: view).buttonStyle(.borderless)
            Button(action: edit) { Image(systemName: "pencil") }.buttonStyle(.borderless).help("编辑")
        }
        .padding(13)
        .frame(minHeight: aliases.isEmpty ? 64 : 82)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor), lineWidth: 0.6))
    }

    private var aliases: [String] {
        item["aliases"]?.arrayValue.map(\.stringValue).filter { !$0.isEmpty } ?? []
    }

    private var tagColor: Color {
        memoryColor(item["color_token"]?.stringValue ?? "blue")
    }
}

private struct MemoryGroupTile: View {
    let item: [String: JSONValue]
    let view: () -> Void
    let edit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 9) {
            HStack {
                Image(systemName: "square.grid.2x2.fill").foregroundStyle(groupColor)
                Text(displayTitle).font(.headline).lineLimit(1)
                Spacer()
                Button("查看", systemImage: "doc.text.magnifyingglass", action: view).buttonStyle(.borderless)
                Button(action: edit) { Image(systemName: "pencil") }.buttonStyle(.borderless).help("编辑")
            }
            if let note = item["note"]?.stringValue, !note.isEmpty {
                Text(note).font(.callout).foregroundStyle(.secondary).lineLimit(3)
            }
            HStack {
                Label(item["ruleDescription"]?.stringValue ?? item["level"]?.stringValue ?? "app", systemImage: "scope")
                Spacer()
                Text("\(Int(item["event_count"]?.numberValue ?? 0)) 条知识")
            }
            .font(.caption)
            .foregroundStyle(.secondary)
            let latest = memoryDate(item["latestAtMs"]?.numberValue ?? 0)
            if !latest.isEmpty {
                Text("最近命中 \(latest)").font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .padding(14)
        .frame(minHeight: 104, alignment: .top)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(groupColor.opacity(0.24), lineWidth: 1))
    }

    private var displayTitle: String {
        let title = item["title"]?.stringValue ?? ""
        if !title.isEmpty { return title }
        let project = item["project"]?.stringValue ?? ""
        let app = item["app"]?.stringValue ?? ""
        return [project, app].filter { !$0.isEmpty }.joined(separator: " · ").isEmpty ? "未命名分组" : [project, app].filter { !$0.isEmpty }.joined(separator: " · ")
    }

    private var groupColor: Color {
        memoryColor(item["color_token"]?.stringValue ?? "blue")
    }
}

private struct MemoryDetailSheet: View {
    let kind: String
    let item: [String: JSONValue]
    let close: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(detailTitle).font(.title2.weight(.semibold)).textSelection(.enabled)
                    Text(kindLabel).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("关闭", systemImage: "xmark", action: close)
                    .keyboardShortcut(.cancelAction)
            }
            .padding(22)
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 22) {
                    if !primaryText.isEmpty {
                        detailSection("完整内容") {
                            Text(primaryText)
                                .font(.body)
                                .textSelection(.enabled)
                                .frame(maxWidth: .infinity, alignment: .leading)
                        }
                    }
                    if !tags.isEmpty {
                        detailSection("标签") {
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 90), spacing: 6)], alignment: .leading, spacing: 6) {
                                ForEach(tags, id: \.self) { tag in
                                    Text(tag)
                                        .font(.caption)
                                        .foregroundStyle(.blue)
                                        .padding(.horizontal, 8)
                                        .frame(height: 24)
                                        .background(Color.blue.opacity(0.08))
                                        .clipShape(RoundedRectangle(cornerRadius: 5))
                                }
                            }
                        }
                    }
                    if !relatedConnections.isEmpty {
                        detailSection("关联标签") {
                            LazyVGrid(columns: [GridItem(.adaptive(minimum: 150), spacing: 8)], alignment: .leading, spacing: 8) {
                                ForEach(Array(relatedConnections.enumerated()), id: \.offset) { _, connection in
                                    HStack(spacing: 6) {
                                        Image(systemName: "point.3.connected.trianglepath.dotted")
                                        Text(connection["tag"]?.stringValue ?? "未命名")
                                        Spacer()
                                        Text(connection["weight"]?.stringValue ?? "")
                                            .foregroundStyle(.secondary)
                                    }
                                    .font(.caption)
                                    .padding(.horizontal, 9)
                                    .frame(height: 30)
                                    .background(Color.teal.opacity(0.08))
                                    .clipShape(RoundedRectangle(cornerRadius: 6))
                                }
                            }
                        }
                    }
                    if !includedMemories.isEmpty {
                        detailSection("包含的记忆") {
                            VStack(alignment: .leading, spacing: 10) {
                                ForEach(Array(includedMemories.enumerated()), id: \.offset) { index, memory in
                                    HStack(alignment: .top, spacing: 10) {
                                        Text("\(index + 1)")
                                            .font(.caption.weight(.semibold))
                                            .foregroundStyle(.secondary)
                                            .frame(width: 22, height: 22)
                                            .background(Color.secondary.opacity(0.08))
                                            .clipShape(RoundedRectangle(cornerRadius: 4))
                                        Text(memory["text"]?.stringValue ?? "空记忆")
                                            .textSelection(.enabled)
                                            .frame(maxWidth: .infinity, alignment: .leading)
                                    }
                                }
                            }
                        }
                    }
                    detailSection("记录信息") {
                        VStack(alignment: .leading, spacing: 10) {
                            ForEach(displayFields, id: \.0) { key, value in
                                LabeledContent(key) {
                                    Text(value)
                                        .textSelection(.enabled)
                                        .multilineTextAlignment(.trailing)
                                }
                            }
                        }
                    }
                }
                .padding(22)
            }
        }
        .frame(minWidth: 680, idealWidth: 760, minHeight: 520, idealHeight: 640)
    }

    private func detailSection<Content: View>(_ title: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.headline)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
    }

    private var detailTitle: String {
        item["title"]?.stringValue
            ?? item["text"]?.stringValue
            ?? item["textPreview"]?.stringValue
            ?? item["tag"]?.stringValue
            ?? item["value"]?.stringValue
            ?? "记忆详情"
    }

    private var primaryText: String {
        item["summary"]?.stringValue
            ?? item["text"]?.stringValue
            ?? item["textPreview"]?.stringValue
            ?? item["description"]?.stringValue
            ?? item["note"]?.stringValue
            ?? item["reason"]?.stringValue
            ?? ""
    }

    private var tags: [String] {
        let tagValues = item["tags"]?.arrayValue.map(\.stringValue) ?? []
        let aliases = item["aliases"]?.arrayValue.map(\.stringValue) ?? []
        return (tagValues + aliases).filter { !$0.isEmpty }
    }

    private var includedMemories: [[String: JSONValue]] {
        item["memories"]?.arrayValue.map(\.objectValue).filter { !$0.isEmpty } ?? []
    }

    private var relatedConnections: [[String: JSONValue]] {
        item["connections"]?.arrayValue.map(\.objectValue).filter { !$0.isEmpty } ?? []
    }

    private var displayFields: [(String, String)] {
        let hidden = Set(["title", "summary", "text", "textPreview", "description", "note", "reason", "tags", "aliases", "memories", "connections"])
        return item.keys.sorted().compactMap { key in
            guard !hidden.contains(key), let value = item[key] else { return nil }
            let rendered = memoryDetailValue(value, key: key)
            guard !rendered.isEmpty else { return nil }
            return (memoryFieldLabel(key), rendered)
        }
    }

    private var kindLabel: String {
        ["books": "主题书", "atoms": "记忆", "tags": "标签", "phrases": "短语", "groups": "分组", "negative": "屏蔽记录"][kind] ?? kind
    }
}

private func memoryFieldLabel(_ key: String) -> String {
    [
        "id": "记录 ID", "type": "类型", "project": "项目", "app": "应用",
        "status": "状态", "active": "启用", "confidence": "可信度",
        "quality_score": "质量评分", "sourceEventCount": "来源事件",
        "atomCount": "包含记忆", "item_count": "关联项目", "edge_count": "标签连接",
        "event_count": "知识数量", "useCount": "使用次数", "created_at_ms": "创建时间",
        "updated_at_ms": "更新时间", "updatedAtMs": "更新时间", "sourceStartMs": "来源开始",
        "sourceEndMs": "来源结束", "latestAtMs": "最近命中", "last_used_at_ms": "最近使用"
    ][key] ?? key
}

private func memoryDetailValue(_ value: JSONValue, key: String) -> String {
    if key.lowercased().contains("_at_ms") || key.hasSuffix("AtMs") || ["sourceStartMs", "sourceEndMs"].contains(key) {
        let date = memoryDate(value.numberValue)
        if !date.isEmpty { return date }
    }
    switch value {
    case .string(let text): return text
    case .number(let number):
        if ["confidence", "quality_score"].contains(key) { return "\(Int(number * 100))%" }
        return number.rounded() == number ? String(Int(number)) : String(format: "%.2f", number)
    case .bool(let enabled): return enabled ? "是" : "否"
    case .array(let values): return values.map { memoryDetailValue($0, key: key) }.filter { !$0.isEmpty }.joined(separator: "、")
    case .object(let object):
        return object.keys.sorted().compactMap { childKey in
            let child = memoryDetailValue(object[childKey] ?? .null, key: childKey)
            return child.isEmpty ? nil : "\(childKey): \(child)"
        }.joined(separator: "\n")
    case .null: return ""
    }
}

private struct MemoryEditorDraft {
    let id: String
    let title: String
    let detail: String
    let tags: [String]
    let aliases: [String]
    let type: String
    let color: String
    let active: Bool
    let mergeIntoId: String
}

private struct MemoryEditorSheet: View {
    let kind: String
    let item: [String: JSONValue]
    let mergeCandidates: [[String: JSONValue]]
    let saving: Bool
    let onCancel: () -> Void
    let onSave: (MemoryEditorDraft) -> Void

    @State private var title: String
    @State private var detail: String
    @State private var tagsText: String
    @State private var aliasesText: String
    @State private var type: String
    @State private var color: String
    @State private var active: Bool
    @State private var mergeIntoId: String

    init(
        kind: String,
        item: [String: JSONValue],
        mergeCandidates: [[String: JSONValue]],
        saving: Bool,
        onCancel: @escaping () -> Void,
        onSave: @escaping (MemoryEditorDraft) -> Void
    ) {
        self.kind = kind
        self.item = item
        self.mergeCandidates = mergeCandidates
        self.saving = saving
        self.onCancel = onCancel
        self.onSave = onSave
        let initialTitle: String
        let initialDetail: String
        switch kind {
        case "books":
            initialTitle = item["title"]?.stringValue ?? ""
            initialDetail = item["summary"]?.stringValue ?? ""
        case "tags":
            initialTitle = item["tag"]?.stringValue ?? ""
            initialDetail = item["description"]?.stringValue ?? ""
        case "groups":
            initialTitle = item["title"]?.stringValue ?? ""
            initialDetail = item["note"]?.stringValue ?? ""
        case "negative":
            initialTitle = item["value"]?.stringValue ?? ""
            initialDetail = item["reason"]?.stringValue ?? ""
        default:
            initialTitle = item["text"]?.stringValue ?? item["textPreview"]?.stringValue ?? ""
            initialDetail = initialTitle
        }
        _title = State(initialValue: initialTitle)
        _detail = State(initialValue: initialDetail)
        _tagsText = State(initialValue: item["tags"]?.arrayValue.map(\.stringValue).joined(separator: ", ") ?? "")
        _aliasesText = State(initialValue: item["aliases"]?.arrayValue.map(\.stringValue).joined(separator: ", ") ?? "")
        _type = State(initialValue: item["type"]?.stringValue ?? "concept")
        _color = State(initialValue: item["color_token"]?.stringValue ?? "blue")
        _active = State(initialValue: item["active"]?.boolValue ?? true)
        _mergeIntoId = State(initialValue: "")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Text(editorTitle).font(.title2.weight(.semibold))
                Spacer()
                Button(action: onCancel) { Image(systemName: "xmark") }.buttonStyle(.borderless).help("关闭")
            }

            if kind != "negative" {
                LabeledContent(titleLabel) {
                    TextField(titleLabel, text: $title).textFieldStyle(.roundedBorder).frame(width: 360)
                }
            } else {
                LabeledContent("屏蔽项") { Text(title).textSelection(.enabled) }
            }

            if ["books", "groups", "tags", "negative"].contains(kind) {
                LabeledContent(detailLabel) {
                    TextEditor(text: $detail)
                        .font(.body)
                        .frame(width: 360, height: 100)
                        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color(nsColor: .separatorColor), lineWidth: 0.6))
                }
            }

            if ["books", "atoms"].contains(kind) {
                LabeledContent("标签") {
                    TextField("以逗号分隔", text: $tagsText).textFieldStyle(.roundedBorder).frame(width: 360)
                }
            }

            if kind == "tags" {
                LabeledContent("类型") {
                    TextField("类型", text: $type).textFieldStyle(.roundedBorder).frame(width: 180)
                }
                LabeledContent("别名") {
                    TextField("以逗号分隔", text: $aliasesText).textFieldStyle(.roundedBorder).frame(width: 360)
                }
            }

            if ["groups", "tags"].contains(kind) {
                LabeledContent("颜色") {
                    Picker("颜色", selection: $color) {
                        ForEach(["blue", "teal", "green", "orange", "pink", "purple", "gray"], id: \.self) { token in
                            Text(token.capitalized).tag(token)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 180)
                }
            }

            if ["atoms", "tags", "groups"].contains(kind), !availableMergeCandidates.isEmpty {
                LabeledContent("合并到") {
                    Picker("合并到", selection: $mergeIntoId) {
                        Text("不合并").tag("")
                        ForEach(availableMergeCandidates, id: \.id) { candidate in
                            Text(candidate.title).tag(candidate.id)
                        }
                    }
                    .labelsHidden()
                    .frame(width: 360)
                }
                if !mergeIntoId.isEmpty {
                    Label("保存后当前条目会并入目标，并保留可审计的合并记录。", systemImage: "arrow.triangle.merge")
                        .font(.caption)
                        .foregroundStyle(.orange)
                }
            }

            if kind == "negative" {
                Toggle("启用屏蔽", isOn: $active)
            }

            HStack {
                Spacer()
                Button("取消", action: onCancel)
                Button {
                    onSave(
                        MemoryEditorDraft(
                            id: item["id"]?.stringValue ?? item["memoryId"]?.stringValue ?? "",
                            title: title,
                            detail: detail,
                            tags: parsedTags,
                            aliases: parsedAliases,
                            type: type,
                            color: color,
                            active: active,
                            mergeIntoId: mergeIntoId
                        )
                    )
                } label: {
                    if saving {
                        ProgressView().controlSize(.small)
                    } else {
                        Text(mergeIntoId.isEmpty ? "保存" : "合并并保存")
                    }
                }
                .buttonStyle(.borderedProminent)
                .disabled(saving || saveDisabled)
            }
        }
        .padding(24)
        .frame(width: 540)
    }

    private var editorTitle: String { "编辑\(kindTitle)" }
    private var kindTitle: String {
        switch kind {
        case "books": return "主题书"
        case "atoms": return "记忆"
        case "tags": return "标签"
        case "phrases": return "短语"
        case "groups": return "分组"
        default: return "屏蔽规则"
        }
    }
    private var titleLabel: String { kind == "tags" ? "名称" : (kind == "phrases" || kind == "atoms" ? "内容" : "标题") }
    private var detailLabel: String {
        if kind == "groups" { return "说明" }
        if kind == "tags" { return "标签含义" }
        return kind == "negative" ? "原因" : "摘要"
    }
    private var parsedTags: [String] {
        tagsText.replacingOccurrences(of: "，", with: ",").split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    }
    private var parsedAliases: [String] {
        aliasesText.replacingOccurrences(of: "，", with: ",").split(separator: ",").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
    }
    private var availableMergeCandidates: [MemoryMergeCandidate] {
        let currentId = item["id"]?.stringValue ?? item["memoryId"]?.stringValue ?? ""
        return mergeCandidates.compactMap { candidate in
            let id = candidate["id"]?.stringValue ?? candidate["memoryId"]?.stringValue ?? ""
            guard !id.isEmpty, id != currentId else { return nil }
            let title: String
            if kind == "tags" {
                title = candidate["tag"]?.stringValue ?? id
            } else if kind == "groups" {
                title = candidate["title"]?.stringValue ?? id
            } else {
                title = candidate["text"]?.stringValue ?? candidate["textPreview"]?.stringValue ?? id
            }
            return MemoryMergeCandidate(id: id, title: title)
        }
    }
    private var saveDisabled: Bool {
        if kind == "negative" { return detail.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }
        return title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

private struct MemoryMergeCandidate: Identifiable {
    let id: String
    let title: String
}

private func memoryDate(_ milliseconds: Double) -> String {
    guard milliseconds > 0 else { return "" }
    return Date(timeIntervalSince1970: milliseconds / 1000).formatted(date: .abbreviated, time: .omitted)
}

private func memoryColor(_ token: String) -> Color {
    switch token {
    case "teal": return .teal
    case "green": return .green
    case "orange": return .orange
    case "pink": return .pink
    case "purple": return .purple
    case "gray": return .gray
    default: return .blue
    }
}
