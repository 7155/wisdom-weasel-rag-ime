import SwiftUI

struct MemoryPage: View {
    @EnvironmentObject private var model: AppModel
    @State private var editingItem: [String: JSONValue] = [:]
    @State private var editorPresented = false
    @State private var pendingAction: PendingMemoryAction?
    @State private var detailSelection: MemoryDetailSelection?
    @State private var tagPresentation = "network"
    @State private var pageMode = "catalog"
    @State private var selectedGraphEntityId = ""
    @State private var selectedGraphRelationId = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            pagePicker
            Divider()
            if pageMode == "graph" {
                graphBrowser
            } else {
                kindPicker
                Divider()
                content
            }
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
        .onChange(of: pageMode) { value in
            guard value == "graph" else { return }
            Task { await model.loadMemoryGraph() }
        }
    }

    private var pagePicker: some View {
        HStack(spacing: 14) {
            Picker("记忆视图", selection: $pageMode) {
                Label("目录", systemImage: "list.bullet.rectangle").tag("catalog")
                Label("关系图", systemImage: "point.3.connected.trianglepath.dotted").tag("graph")
            }
            .pickerStyle(.segmented)
            .frame(width: 250)
            Spacer()
            if pageMode == "graph", let summary = model.memoryGraph?.summary {
                Text("\(summary.visibleEntityCount) 个实体 · \(summary.visibleRelationCount) 条关系 · \(summary.evidenceCount) 份证据")
                    .font(.callout.monospacedDigit())
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 28)
        .padding(.vertical, 12)
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

    private var graphBrowser: some View {
        VStack(spacing: 0) {
            graphToolbar
            Divider()
            if model.memoryGraphLoading, model.memoryGraph == nil {
                VStack(spacing: 12) {
                    ProgressView()
                    Text("正在读取关系图").font(.callout).foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
            } else if let graph = model.memoryGraph, !graph.entities.isEmpty {
                HSplitView {
                    MemoryEntityGraph(
                        graph: graph,
                        selectedEntityId: selectedGraphEntityId,
                        selectedRelationId: selectedGraphRelationId,
                        onSelectEntity: { entityId in
                            selectedGraphEntityId = entityId
                            selectedGraphRelationId = ""
                            model.memoryGraphSources = nil
                        }
                    )
                    .frame(minWidth: 580, maxWidth: .infinity, maxHeight: .infinity)

                    MemoryGraphInspector(
                        graph: graph,
                        selectedEntityId: selectedGraphEntityId,
                        selectedRelationId: selectedGraphRelationId,
                        sources: model.memoryGraphSources,
                        sourcesLoading: model.memoryGraphSourcesLoading,
                        sourcesRelationId: model.memoryGraphSourcesRelationId,
                        onSelectRelation: selectGraphRelation
                    )
                    .frame(minWidth: 300, idealWidth: 340, maxWidth: 390, maxHeight: .infinity)
                }
            } else {
                EmptyState(symbol: "point.3.connected.trianglepath.dotted", text: "当前筛选范围没有已确认关系")
            }
        }
    }

    private var graphToolbar: some View {
        HStack(spacing: 10) {
            TextField("搜索实体或事实", text: $model.memoryGraphQuery)
                .textFieldStyle(.roundedBorder)
                .frame(minWidth: 220, maxWidth: 340)
                .onSubmit { Task { await model.loadMemoryGraph() } }
            Button {
                Task { await model.loadMemoryGraph() }
            } label: {
                Image(systemName: "magnifyingglass")
            }
            .help("搜索")

            Picker("归属", selection: $model.memoryGraphOwnerKind) {
                Text("全部归属").tag("")
                ForEach(model.memoryGraph?.filters.ownerKinds ?? [], id: \.self) { owner in
                    Text(memoryOwnerLabel(owner)).tag(owner)
                }
            }
            .frame(width: 145)
            .onChange(of: model.memoryGraphOwnerKind) { _ in Task { await model.loadMemoryGraph() } }

            Picker("类型", selection: $model.memoryGraphEntityType) {
                Text("全部类型").tag("")
                ForEach(model.memoryGraph?.filters.entityTypes ?? []) { item in
                    Text("\(memoryEntityTypeLabel(item.value)) · \(item.count)").tag(item.value)
                }
            }
            .frame(width: 185)
            .onChange(of: model.memoryGraphEntityType) { _ in Task { await model.loadMemoryGraph() } }

            Spacer()
            if let pending = model.memoryGraph?.summary.projectionPendingCount, pending > 0 {
                Label("\(pending) 待投影", systemImage: "clock.arrow.circlepath")
                    .font(.callout)
                    .foregroundStyle(.orange)
            }
            Button {
                Task { await model.loadMemoryGraph() }
            } label: {
                Image(systemName: "arrow.clockwise")
            }
            .disabled(model.memoryGraphLoading)
            .help("刷新")
        }
        .controlSize(.large)
        .padding(.horizontal, 28)
        .padding(.vertical, 12)
    }

    private func selectGraphRelation(_ relationId: String) {
        selectedGraphRelationId = relationId
        guard let relation = model.memoryGraph?.relations.first(where: { $0.id == relationId }) else { return }
        selectedGraphEntityId = relation.sourceEntityId
        model.clearMemoryGraphSources()
        Task { await model.loadMemoryGraphSources(relationId: relationId) }
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

private struct MemoryEntityGraph: View {
    let graph: MemoryGraphResponse
    let selectedEntityId: String
    let selectedRelationId: String
    let onSelectEntity: (String) -> Void

    var body: some View {
        GeometryReader { proxy in
            let points = positions(in: proxy.size)
            ZStack {
                Canvas { context, _ in
                    for relation in visibleRelations {
                        guard let start = points[relation.sourceEntityId],
                              let end = points[relation.targetEntityId] else { continue }
                        var path = Path()
                        path.move(to: start)
                        path.addLine(to: end)
                        let selected = relation.id == selectedRelationId
                        context.stroke(
                            path,
                            with: .color(selected ? ControlDesign.brand : Color.secondary.opacity(0.24)),
                            lineWidth: selected ? 2.2 : 0.8 + relation.confidence
                        )
                    }
                }

                ForEach(visibleEntities) { entity in
                    if let point = points[entity.id] {
                        Button {
                            onSelectEntity(entity.id)
                        } label: {
                            HStack(spacing: 8) {
                                Image(systemName: memoryEntitySymbol(entity.entityType))
                                    .font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(entity.id == selectedEntityId ? Color.white : memoryOwnerColor(entity.ownerKind))
                                    .frame(width: 20)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(entity.canonicalName)
                                        .font(ControlDesign.bodyFont.weight(.semibold))
                                        .lineLimit(1)
                                    Text("\(memoryEntityTypeLabel(entity.entityType)) · \(entity.relationCount) 关系")
                                        .font(ControlDesign.metadataFont)
                                        .foregroundStyle(entity.id == selectedEntityId ? Color.white.opacity(0.84) : Color.secondary)
                                        .lineLimit(1)
                                }
                                Spacer(minLength: 0)
                            }
                            .padding(.horizontal, 10)
                            .frame(width: 156, height: 54)
                            .background(entity.id == selectedEntityId ? ControlDesign.brand : Color(nsColor: .controlBackgroundColor))
                            .clipShape(RoundedRectangle(cornerRadius: 7))
                            .overlay(
                                RoundedRectangle(cornerRadius: 7)
                                    .stroke(
                                        entity.id == selectedEntityId
                                            ? ControlDesign.brand
                                            : memoryOwnerColor(entity.ownerKind).opacity(0.34),
                                        lineWidth: entity.id == selectedEntityId ? 1.5 : 0.8
                                    )
                            )
                        }
                        .buttonStyle(.plain)
                        .position(point)
                        .help(entity.canonicalName)
                    }
                }
            }
        }
        .frame(minHeight: 560)
        .background(Color(nsColor: .textBackgroundColor).opacity(0.28))
        .overlay(Rectangle().fill(ControlDesign.hairline).frame(width: 1), alignment: .trailing)
    }

    private var visibleEntities: [MemoryGraphEntity] {
        Array(
            graph.entities
                .sorted {
                    if $0.relationCount == $1.relationCount { return $0.confidence > $1.confidence }
                    return $0.relationCount > $1.relationCount
                }
                .prefix(18)
        )
    }

    private var visibleRelations: [MemoryGraphRelation] {
        let ids = Set(visibleEntities.map(\.id))
        return graph.relations.filter {
            ids.contains($0.sourceEntityId) && ids.contains($0.targetEntityId)
        }
    }

    private func positions(in size: CGSize) -> [String: CGPoint] {
        guard !visibleEntities.isEmpty else { return [:] }
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        var result: [String: CGPoint] = [visibleEntities[0].id: center]
        let firstRing = Array(visibleEntities.dropFirst().prefix(6))
        let secondRing = Array(visibleEntities.dropFirst(7))
        let horizontalBound = max(0, size.width / 2 - 90)
        let verticalBound = max(0, size.height / 2 - 36)
        let innerX = min(min(175, max(112, size.width * 0.23)), horizontalBound)
        let innerY = min(min(132, max(88, size.height * 0.21)), verticalBound)
        let outerX = min(min(330, max(184, size.width * 0.39)), horizontalBound)
        let outerY = min(min(236, max(150, size.height * 0.36)), verticalBound)
        for (index, entity) in firstRing.enumerated() {
            let angle = (Double(index) / Double(max(1, firstRing.count))) * Double.pi * 2 - Double.pi / 2
            result[entity.id] = CGPoint(
                x: center.x + cos(angle) * innerX,
                y: center.y + sin(angle) * innerY
            )
        }
        for (index, entity) in secondRing.enumerated() {
            let angle = (Double(index) / Double(max(1, secondRing.count))) * Double.pi * 2 - Double.pi / 2
            result[entity.id] = CGPoint(
                x: center.x + cos(angle) * outerX,
                y: center.y + sin(angle) * outerY
            )
        }
        return result
    }
}

private struct MemoryGraphInspector: View {
    let graph: MemoryGraphResponse
    let selectedEntityId: String
    let selectedRelationId: String
    let sources: MemoryGraphSourcesResponse?
    let sourcesLoading: Bool
    let sourcesRelationId: String
    let onSelectRelation: (String) -> Void

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                if let relation = selectedRelation {
                    relationDetail(relation)
                } else if let entity = selectedEntity {
                    entityDetail(entity)
                } else {
                    graphSummary
                }
            }
            .padding(20)
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .background(Color(nsColor: .windowBackgroundColor))
    }

    private var selectedEntity: MemoryGraphEntity? {
        graph.entities.first(where: { $0.id == selectedEntityId })
    }

    private var selectedRelation: MemoryGraphRelation? {
        graph.relations.first(where: { $0.id == selectedRelationId })
    }

    private var connectedRelations: [MemoryGraphRelation] {
        guard let entity = selectedEntity else { return [] }
        return graph.relations
            .filter { $0.sourceEntityId == entity.id || $0.targetEntityId == entity.id }
            .sorted { $0.confidence > $1.confidence }
    }

    private var graphSummary: some View {
        VStack(alignment: .leading, spacing: 12) {
            Label("关系概览", systemImage: "point.3.connected.trianglepath.dotted")
                .font(.title3.weight(.semibold))
            inspectorMetric("实体", value: graph.summary.visibleEntityCount)
            inspectorMetric("关系", value: graph.summary.visibleRelationCount)
            inspectorMetric("证据", value: graph.summary.evidenceCount)
            if graph.summary.projectionPendingCount > 0 {
                inspectorMetric("待投影", value: graph.summary.projectionPendingCount, tint: .orange)
            }
            Text(Date(timeIntervalSince1970: Double(graph.asOfMs) / 1_000).formatted(date: .abbreviated, time: .shortened))
                .font(.callout)
                .foregroundStyle(.secondary)
        }
    }

    private func entityDetail(_ entity: MemoryGraphEntity) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: memoryEntitySymbol(entity.entityType))
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundStyle(memoryOwnerColor(entity.ownerKind))
                    .frame(width: 32, height: 32)
                VStack(alignment: .leading, spacing: 3) {
                    Text(entity.canonicalName).font(.title3.weight(.semibold)).textSelection(.enabled)
                    Text("\(memoryEntityTypeLabel(entity.entityType)) · \(memoryOwnerLabel(entity.ownerKind))")
                        .font(.callout)
                        .foregroundStyle(.secondary)
                }
            }
            if !entity.description.isEmpty {
                Text(entity.description)
                    .font(.body)
                    .lineSpacing(3)
                    .textSelection(.enabled)
            }
            if !entity.aliases.isEmpty {
                labeledValue("别名", entity.aliases.joined(separator: "、"))
            }
            labeledValue("可信度", "\(Int(entity.confidence * 100))%")
            labeledValue("来源", "\(entity.sources.count) 份")

            Divider()
            Text("相关事实").font(.headline)
            if connectedRelations.isEmpty {
                Text("暂无关系").font(.callout).foregroundStyle(.secondary)
            } else {
                ForEach(connectedRelations.prefix(16)) { relation in
                    Button {
                        onSelectRelation(relation.id)
                    } label: {
                        HStack(alignment: .top, spacing: 9) {
                            Image(systemName: "arrow.left.and.right")
                                .foregroundStyle(ControlDesign.brand)
                                .frame(width: 18)
                            VStack(alignment: .leading, spacing: 3) {
                                Text(relation.fact).font(.callout.weight(.medium)).lineLimit(3)
                                Text("\(relation.sourceName) → \(relation.targetName)")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer(minLength: 0)
                            Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
                        }
                        .contentShape(Rectangle())
                    }
                    .buttonStyle(.plain)
                    Divider()
                }
            }
        }
    }

    private func relationDetail(_ relation: MemoryGraphRelation) -> some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Label("关系事实", systemImage: "arrow.triangle.branch")
                    .font(.title3.weight(.semibold))
                Spacer()
                Text("\(Int(relation.confidence * 100))%")
                    .font(.callout.monospacedDigit().weight(.semibold))
                    .foregroundStyle(ControlDesign.brand)
            }
            Text(relation.fact)
                .font(.body.weight(.medium))
                .lineSpacing(4)
                .textSelection(.enabled)
            HStack(spacing: 8) {
                Text(relation.sourceName).lineLimit(1)
                Image(systemName: "arrow.right").foregroundStyle(ControlDesign.brand)
                Text(relation.targetName).lineLimit(1)
            }
            .font(.callout.weight(.semibold))
            labeledValue("关系类型", relation.relationType)
            labeledValue("归属", memoryOwnerLabel(relation.ownerKind))
            labeledValue("生效时间", graphDate(relation.validFromMs))
            if let validTo = relation.validToMs {
                labeledValue("失效时间", graphDate(validTo))
            }

            Divider()
            HStack {
                Text("证据").font(.headline)
                Spacer()
                Text("\(relation.sourceCount) 份").font(.callout.monospacedDigit()).foregroundStyle(.secondary)
            }
            if sourcesLoading, sourcesRelationId == relation.id {
                HStack(spacing: 8) {
                    ProgressView().controlSize(.small)
                    Text("正在读取证据").font(ControlDesign.metadataFont).foregroundStyle(.secondary)
                }
            } else if sourcesRelationId == relation.id,
                      let sources,
                      !sourcesForSelectedRelation(sources, relationId: relation.id).isEmpty {
                ForEach(sourcesForSelectedRelation(sources, relationId: relation.id)) { source in
                    VStack(alignment: .leading, spacing: 5) {
                        HStack {
                            Label(memorySourceTypeLabel(source.sourceType), systemImage: memorySourceSymbol(source.sourceType))
                                .font(.callout.weight(.semibold))
                            Spacer()
                            Text(graphDate(source.createdAtMs)).font(.caption).foregroundStyle(.secondary)
                        }
                        Text(source.text)
                            .font(.callout)
                            .foregroundStyle(.secondary)
                            .lineLimit(8)
                            .textSelection(.enabled)
                        let scope = [source.app, source.project].filter { !$0.isEmpty }.joined(separator: " · ")
                        if !scope.isEmpty {
                            Text(scope).font(.caption).foregroundStyle(.tertiary)
                        }
                    }
                    Divider()
                }
            } else if sourcesRelationId == relation.id {
                Text("证据已被隐私规则过滤或当前不可展示")
                    .font(ControlDesign.metadataFont)
                    .foregroundStyle(.secondary)
            } else {
                Text("选择关系后读取证据")
                    .font(ControlDesign.metadataFont)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func sourcesForSelectedRelation(
        _ payload: MemoryGraphSourcesResponse,
        relationId: String
    ) -> [MemoryGraphEvidence] {
        payload.sources.filter { $0.relationIds.contains(relationId) }
    }

    private func labeledValue(_ label: String, _ value: String) -> some View {
        HStack(alignment: .firstTextBaseline, spacing: 10) {
            Text(label).foregroundStyle(.secondary).frame(width: 72, alignment: .leading)
            Text(value).textSelection(.enabled)
            Spacer(minLength: 0)
        }
        .font(.callout)
    }

    private func inspectorMetric(_ label: String, value: Int, tint: Color = ControlDesign.brand) -> some View {
        HStack {
            Text(label).font(.callout).foregroundStyle(.secondary)
            Spacer()
            Text("\(value)").font(.title3.monospacedDigit().weight(.semibold)).foregroundStyle(tint)
        }
        .padding(.vertical, 3)
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

private func graphDate(_ milliseconds: Int) -> String {
    guard milliseconds > 0 else { return "未知" }
    return Date(timeIntervalSince1970: Double(milliseconds) / 1_000)
        .formatted(date: .abbreviated, time: .shortened)
}

private func memoryOwnerLabel(_ owner: String) -> String {
    switch owner {
    case "user": return "用户"
    case "shared": return "共享"
    case "agent": return "Agent"
    case "session": return "会话"
    case "room": return "群聊"
    default: return owner.isEmpty ? "未知" : owner
    }
}

private func memoryOwnerColor(_ owner: String) -> Color {
    switch owner {
    case "user": return .teal
    case "shared": return .blue
    case "agent": return .purple
    case "session": return .orange
    case "room": return .pink
    default: return .secondary
    }
}

private func memoryEntityTypeLabel(_ type: String) -> String {
    switch type {
    case "person": return "人物"
    case "agent": return "Agent"
    case "project": return "项目"
    case "app", "application": return "应用"
    case "topic", "concept": return "主题"
    case "task": return "任务"
    case "event": return "事件"
    case "place": return "地点"
    case "organization": return "组织"
    case "preference": return "偏好"
    case "skill": return "技能"
    case "document", "book": return "文档"
    default: return type.isEmpty ? "实体" : type
    }
}

private func memoryEntitySymbol(_ type: String) -> String {
    switch type {
    case "person": return "person"
    case "agent": return "brain.head.profile"
    case "project": return "folder"
    case "app", "application": return "app"
    case "task": return "checklist"
    case "event": return "calendar"
    case "place": return "mappin.and.ellipse"
    case "organization": return "building.2"
    case "preference": return "slider.horizontal.3"
    case "skill": return "hammer"
    case "document", "book": return "doc.text"
    default: return "circle.hexagongrid"
    }
}

private func memorySourceTypeLabel(_ type: String) -> String {
    switch type {
    case "input_event": return "输入记录"
    case "agent_memory_source": return "Agent 经历"
    case "atom": return "记忆原子"
    case "book": return "主题书"
    case "phrase", "item": return "短语记忆"
    default: return type.isEmpty ? "证据" : type
    }
}

private func memorySourceSymbol(_ type: String) -> String {
    switch type {
    case "input_event": return "keyboard"
    case "agent_memory_source": return "brain.head.profile"
    case "atom": return "circle.hexagongrid"
    case "book": return "book.closed"
    case "phrase", "item": return "text.quote"
    default: return "doc.text.magnifyingglass"
    }
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
