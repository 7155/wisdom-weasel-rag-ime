import SwiftUI

struct RagAndModelsPage: View {
    @EnvironmentObject private var model: AppModel
    @State private var confirmingDatabaseApply = false
    @State private var confirmingDatabaseRollback = false
    @State private var editingDatabaseDiff: [String: JSONValue] = [:]
    @State private var databaseEditorPresented = false

    var body: some View {
        VStack(spacing: 0) {
            header
            PendingApplyBanner()
            Divider()
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    modePicker
                    composer
                    if model.knowledgeResponse != nil {
                        resultSurface
                    }
                    if model.knowledgeMode == .organizeDatabase, !organizeDiffs.isEmpty {
                        databaseDraftSection
                    }
                    if !evidence.isEmpty {
                        evidenceSection
                    }
                    advancedSettings
                }
                .padding(.horizontal, 32)
                .padding(.vertical, 28)
                .frame(maxWidth: 1120, alignment: .leading)
                .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .task { await model.loadKnowledgeRoute() }
        .confirmationDialog(
            "应用这份数据库整理草案？",
            isPresented: $confirmingDatabaseApply,
            titleVisibility: .visible
        ) {
            Button("应用全部已审阅变更") { Task { await model.applyKnowledgeDatabasePlan() } }
            Button("取消", role: .cancel) { }
        } message: {
            Text("这会写入本地 Memory Book、Memory Atom、标签关系和短语；仍可用当前 run 回滚。")
        }
        .sheet(isPresented: $databaseEditorPresented) {
            DatabaseDraftEditorSheet(
                diff: editingDatabaseDiff,
                onCancel: { databaseEditorPresented = false },
                onSave: { payload in
                    guard let diffId = editingDatabaseDiff["diffId"]?.numberValue, diffId > 0 else { return }
                    Task {
                        let saved = await model.updateKnowledgeDatabaseDraft(
                            diffId: Int(diffId),
                            payload: payload,
                            selected: true
                        )
                        if saved { databaseEditorPresented = false }
                    }
                }
            )
        }
        .confirmationDialog(
            "回滚这份整理结果？",
            isPresented: $confirmingDatabaseRollback,
            titleVisibility: .visible
        ) {
            Button("回滚已应用变更", role: .destructive) {
                Task { await model.applyKnowledgeDatabasePlan(rollback: true) }
            }
            Button("取消", role: .cancel) { }
        }
    }

    private var header: some View {
        HStack(spacing: 12) {
            PageHeader(title: "个人知识工作台", subtitle: "本地检索、远程生成与 Notion 多源知识")
            Spacer()
            routeIndicator(
                title: "知识生成",
                ready: model.knowledgeRoute?.deepseekReady == true,
                symbol: "sparkles"
            )
            routeIndicator(
                title: "Notion",
                ready: model.knowledgeRoute?.notion.ready == true,
                symbol: "books.vertical"
            )
            Toggle("专家模式", isOn: $model.expertMode).toggleStyle(.switch)
        }
        .padding(.horizontal, 30)
        .padding(.vertical, 22)
    }

    private var modePicker: some View {
        Picker("任务", selection: $model.knowledgeMode) {
            ForEach(KnowledgeWorkbenchMode.allCases) { mode in
                Label(mode.title, systemImage: mode.symbol).tag(mode)
            }
        }
        .pickerStyle(.segmented)
    }

    private var composer: some View {
        VStack(alignment: .leading, spacing: 12) {
            if model.knowledgeMode != .organizeDatabase {
                ZStack(alignment: .topLeading) {
                    TextEditor(text: $model.knowledgeQuestion)
                        .font(.system(size: 15))
                        .scrollContentBackground(.hidden)
                        .padding(10)
                        .frame(minHeight: 112)
                    if model.knowledgeQuestion.isEmpty {
                        Text(questionPlaceholder)
                            .foregroundStyle(.tertiary)
                            .padding(.horizontal, 15)
                            .padding(.vertical, 18)
                            .allowsHitTesting(false)
                    }
                }
                .background(Color(nsColor: .controlBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor), lineWidth: 0.7))

                DisclosureGroup("附加上下文") {
                    TextEditor(text: $model.knowledgeContext)
                        .font(.callout)
                        .frame(minHeight: 72)
                        .padding(7)
                        .background(Color(nsColor: .controlBackgroundColor))
                        .clipShape(RoundedRectangle(cornerRadius: 6))
                        .padding(.top, 8)
                }
            } else {
                VStack(alignment: .leading, spacing: 10) {
                    HStack(spacing: 12) {
                        Image(systemName: "wand.and.stars")
                            .font(.system(size: 24))
                            .foregroundStyle(.blue)
                        VStack(alignment: .leading, spacing: 3) {
                            Text("告诉知识管家怎么整理").font(.headline)
                            Text("直接描述目标，系统会清洗历史、合并分组、补标签并生成词表提案。")
                                .font(.callout)
                                .foregroundStyle(.secondary)
                        }
                        Spacer()
                    }
                    ZStack(alignment: .topLeading) {
                        TextEditor(text: $model.knowledgeOrganizationInstruction)
                            .font(.system(size: 15))
                            .scrollContentBackground(.hidden)
                            .padding(10)
                            .frame(minHeight: 92)
                        if model.knowledgeOrganizationInstruction.isEmpty {
                            Text(questionPlaceholder)
                                .foregroundStyle(.tertiary)
                                .padding(.horizontal, 15)
                                .padding(.vertical, 18)
                                .allowsHitTesting(false)
                        }
                    }
                    .background(Color(nsColor: .controlBackgroundColor))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor), lineWidth: 0.7))
                    HStack {
                        Menu {
                            Button("恢复项目默认") { model.knowledgeOrganizationInstruction = model.knowledgeRoute?.defaultOrganizationInstruction ?? "" }
                            Divider()
                            Button("合并零散分组") { model.knowledgeOrganizationInstruction = "合并内容重复或过细的分组，保持少量稳定主题，并重新归类记忆。" }
                            Button("清洗语音和错别字") { model.knowledgeOrganizationInstruction = "结合上下文批量修正语音转写错字、重复口语和残句，只保留确认后的清晰表达。" }
                            Button("整理标签关系") { model.knowledgeOrganizationInstruction = "删除碎片标签，补充稳定语义标签、别名和有证据的标签关系。" }
                            Button("更新常用词表") { model.knowledgeOrganizationInstruction = "根据重复输入、接受和删除反馈，生成常用词新增、提权、降权与屏蔽提案。" }
                        } label: {
                            Label("常用整理目标", systemImage: "text.badge.checkmark")
                        }
                        Spacer()
                    }
                }
                .padding(.vertical, 10)
            }

            HStack(spacing: 12) {
                if model.knowledgeMode != .organizeDatabase {
                    Toggle("包含 Notion", isOn: $model.knowledgeIncludeNotion)
                        .toggleStyle(.switch)
                        .disabled(model.knowledgeRoute?.notion.ready != true)
                    if let notion = model.knowledgeRoute?.notion, !notion.ready {
                        Text(notion.submitConfigured ? "缺少结果通道" : "未配置 Worker")
                            .font(.caption)
                            .foregroundStyle(.orange)
                    }
                }
                Spacer()
                if model.knowledgeRunning {
                    Button {
                        Task { await model.cancelKnowledgeWorkbench() }
                    } label: {
                        Label("停止", systemImage: "stop.fill")
                    }
                }
                Button {
                    Task { await model.runKnowledgeWorkbench() }
                } label: {
                    Label(runButtonTitle, systemImage: model.knowledgeMode == .organizeDatabase ? "wand.and.stars" : "arrow.up.circle.fill")
                }
                .buttonStyle(.borderedProminent)
                .disabled(
                    model.knowledgeRunning
                    || model.knowledgeRoute?.deepseekReady != true
                    || (model.knowledgeMode != .organizeDatabase && model.knowledgeQuestion.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                )
            }
        }
    }

    private var resultSurface: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 9) {
                if model.knowledgeRunning {
                    ProgressView().controlSize(.small)
                } else {
                    Image(systemName: resultSymbol).foregroundStyle(resultColor)
                }
                Text(stageTitle).font(.headline)
                if let response = model.knowledgeResponse, !response.status.isEmpty {
                    Text(response.status.uppercased())
                        .font(.caption2.monospaced().weight(.semibold))
                        .foregroundStyle(resultColor)
                }
                Spacer()
                if let queryId = model.knowledgeResponse?.queryId, !queryId.isEmpty {
                    Text(queryId.prefix(12))
                        .font(.caption.monospaced())
                        .foregroundStyle(.tertiary)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)

            Divider()

            if let error = model.knowledgeResponse?.error, !error.isEmpty {
                Text(error)
                    .foregroundStyle(.red)
                    .padding(16)
                    .textSelection(.enabled)
            } else if let answer = model.knowledgeResponse?.answer, !answer.isEmpty {
                renderedAnswer(answer + (model.knowledgeRunning ? " ▍" : ""))
                    .font(.system(size: 14.5))
                    .lineSpacing(5)
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
                    .padding(16)
            } else {
                HStack(spacing: 10) {
                    Text(stageHint).foregroundStyle(.secondary)
                    Spacer()
                }
                .padding(16)
            }

            if let injection = contextInjection, !injection.isEmpty {
                Divider()
                HStack(spacing: 16) {
                    diagnosticValue(
                        title: "本地证据",
                        value: "\(Int(injection["localEvidenceCount"]?.numberValue ?? 0))",
                        ready: (injection["localEvidenceCount"]?.numberValue ?? 0) > 0
                    )
                    diagnosticValue(
                        title: "上下文注入",
                        value: injection["success"]?.boolValue == true ? "成功" : "等待",
                        ready: injection["success"]?.boolValue == true
                    )
                    diagnosticValue(
                        title: "Notion 合并",
                        value: notionStatusTitle,
                        ready: injection["notionIncluded"]?.boolValue == true
                    )
                    Spacer()
                    if model.knowledgeMode == .organizeDatabase,
                       let runId = organizeRunId,
                       !runId.isEmpty {
                        Text(runId).font(.caption.monospaced()).foregroundStyle(.secondary)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
            }
        }
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor), lineWidth: 0.7))
    }

    private var evidenceSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("来源").font(.headline)
                Spacer()
                Text("\(sources.count) 个可追溯来源").font(.caption).foregroundStyle(.secondary)
            }
            ForEach(Array(evidence.prefix(6).enumerated()), id: \.offset) { index, item in
                HStack(spacing: 10) {
                    Text("L\(index + 1)")
                        .font(.caption.monospaced().weight(.semibold))
                        .foregroundStyle(.blue)
                        .frame(width: 24, alignment: .leading)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(item["title"]?.stringValue.isEmpty == false ? item["title"]!.stringValue : item["sourceId"]?.stringValue ?? "本地记忆")
                            .lineLimit(1)
                        Text(item["sourceLane"]?.stringValue ?? "local")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                }
                .padding(.vertical, 5)
                if index < min(evidence.count, 6) - 1 { Divider() }
            }
            ForEach(Array(notionSources.enumerated()), id: \.offset) { _, item in
                HStack(spacing: 10) {
                    Image(systemName: "books.vertical.fill").foregroundStyle(.green)
                    Text(item["title"]?.stringValue ?? item["url"]?.stringValue ?? "Notion 页面")
                    Spacer()
                }
                .padding(.vertical, 5)
            }
        }
    }

    private var databaseDraftSection: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                VStack(alignment: .leading, spacing: 2) {
                    Text("整理草案").font(.headline)
                    Text("按内容类型审阅；取消勾选的项目不会写入正式记忆库。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Text(databaseRunStatus.uppercased())
                    .font(.caption2.monospaced().weight(.semibold))
                    .foregroundStyle(databaseRunStatus == "applied" ? .green : .orange)
                Spacer()
                Text("已选 \(organizeDiffs.filter(databaseDiffSelected).count) / \(organizeDiffs.count)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                if databaseRunStatus == "applied" || databaseRunStatus == "partial" {
                    Button {
                        confirmingDatabaseRollback = true
                    } label: {
                        Label("回滚", systemImage: "arrow.uturn.backward")
                    }
                } else if databaseRunStatus == "draft" || databaseRunStatus.isEmpty {
                    Button {
                        confirmingDatabaseApply = true
                    } label: {
                        Label("应用草案", systemImage: "checkmark.circle")
                    }
                    .buttonStyle(.borderedProminent)
                }
            }
            ForEach(databaseDraftGroups, id: \.key) { group in
                VStack(alignment: .leading, spacing: 0) {
                    HStack(spacing: 8) {
                        Image(systemName: group.symbol).foregroundStyle(group.color)
                        Text(group.title).font(.subheadline.weight(.semibold))
                        Text("\(group.items.count)")
                            .font(.caption.monospacedDigit())
                            .foregroundStyle(.secondary)
                        Spacer()
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 9)

                    Divider()
                    ForEach(Array(group.items.enumerated()), id: \.offset) { index, diff in
                        databaseDraftRow(diff)
                        if index < group.items.count - 1 { Divider().padding(.leading, 46) }
                    }
                }
                .background(Color(nsColor: .controlBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color(nsColor: .separatorColor), lineWidth: 0.7))
            }
        }
    }

    @ViewBuilder
    private func databaseDraftRow(_ diff: DatabaseDraftDiff) -> some View {
        HStack(alignment: .top, spacing: 10) {
            Button {
                Task {
                    _ = await model.updateKnowledgeDatabaseDraft(
                        diffId: diff.id,
                        selected: !diff.selected
                    )
                }
            } label: {
                Image(systemName: diff.selected ? "checkmark.square.fill" : "square")
                    .foregroundStyle(diff.selected ? Color.accentColor : Color.secondary)
                    .font(.system(size: 16))
            }
            .buttonStyle(.plain)
            .disabled(databaseRunStatus != "draft")
            .help(diff.selected ? "不应用这项" : "应用这项")

            Image(systemName: databaseDiffSymbol(diff.operation))
                .foregroundStyle(diff.tint)
                .frame(width: 18)
                .padding(.top, 2)
            VStack(alignment: .leading, spacing: 3) {
                Text(diff.title)
                    .font(.callout.weight(.medium))
                    .foregroundStyle(diff.selected ? Color.primary : Color.secondary)
                    .lineLimit(2)
                if !diff.detail.isEmpty {
                    Text(diff.detail)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                }
                if !diff.tags.isEmpty {
                    Text(diff.tags.map { "#\($0)" }.joined(separator: "  "))
                        .font(.caption2)
                        .foregroundStyle(diff.tint)
                        .lineLimit(1)
                }
            }
            Spacer(minLength: 12)
            if databaseRunStatus == "draft" {
                Button {
                    editingDatabaseDiff = diff.raw
                    databaseEditorPresented = true
                } label: {
                    Image(systemName: "pencil")
                }
                .buttonStyle(.borderless)
                .help("编辑这项草案")
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 10)
        .opacity(diff.selected ? 1 : 0.58)
    }

    private var advancedSettings: some View {
        DisclosureGroup("RAG 与模型设置") {
            VStack(alignment: .leading, spacing: 18) {
                ForEach(model.sections(ids: ["rag", "models", "memory"])) { section in
                    SchemaSectionView(section: section)
                    if section.id != "memory" { Divider() }
                }
            }
            .padding(.top, 14)
        }
    }

    private func routeIndicator(title: String, ready: Bool, symbol: String) -> some View {
        HStack(spacing: 5) {
            Image(systemName: symbol)
            Text(title)
            Circle().fill(ready ? Color.green : Color.orange).frame(width: 6, height: 6)
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    private func diagnosticValue(title: String, value: String, ready: Bool) -> some View {
        HStack(spacing: 6) {
            Circle().fill(ready ? Color.green : Color.secondary.opacity(0.4)).frame(width: 6, height: 6)
            Text(title).foregroundStyle(.secondary)
            Text(value).fontWeight(.medium)
        }
        .font(.caption)
    }

    private func renderedAnswer(_ answer: String) -> Text {
        if let attributed = try? AttributedString(
            markdown: answer,
            options: .init(interpretedSyntax: .inlineOnlyPreservingWhitespace)
        ) {
            return Text(attributed)
        }
        return Text(answer)
    }

    private var questionPlaceholder: String {
        switch model.knowledgeMode {
        case .knowledgeAnswer: return "询问项目、笔记或个人知识中的具体问题"
        case .longForm: return "描述要生成的长文、目标读者和重点"
        case .recall: return "输入想回忆的项目、时间或主题"
        case .organizeDatabase: return "例如：把输入法相关内容合并为一个组，修正语音错字，标签不要太碎，并整理常用词。"
        }
    }

    private var runButtonTitle: String {
        model.knowledgeMode == .organizeDatabase ? "整理记忆" : "开始"
    }

    private var stageTitle: String {
        guard let stage = model.knowledgeResponse?.stage else { return "准备中" }
        switch stage {
        case "queued": return "任务已排队"
        case "retrieving_local": return "正在检索本地知识"
        case "generating_local": return "正在生成本地答案"
        case "streaming_local": return "正在流式生成本地答案"
        case "notion_pending": return "本地答案已就绪，等待 Notion"
        case "merging_notion": return "正在合并多源知识"
        case "streaming_merge": return "正在流式合并多源知识"
        case "building_memory_bundle": return "正在整理数据库"
        case "review_ready": return "整理草案可审阅"
        case "complete", "complete_local_only": return "结果已就绪"
        case "failed", "validation_failed": return "任务失败"
        case "cancelled", "superseded": return "任务已停止"
        default: return stage.replacingOccurrences(of: "_", with: " ")
        }
    }

    private var stageHint: String {
        switch model.knowledgeResponse?.stage {
        case "retrieving_local": return "检索 Memory Book、TagMemo、时间线和反馈记录"
        case "generating_local": return "正在根据已召回证据生成正文"
        case "streaming_local": return "正文已开始返回，后续内容会持续追加"
        case "notion_pending": return "Notion Custom Agent 已收到异步任务"
        case "merging_notion": return "正在去重并重新组织本地与 Notion 结果"
        case "streaming_merge": return "本地与 Notion 内容正在增量合并"
        case "building_memory_bundle": return "正在脱敏、聚合并验证 Memory Book 草案"
        default: return "等待结果"
        }
    }

    private var resultColor: Color {
        switch model.knowledgeResponse?.status {
        case "ready": return .green
        case "error", "blocked": return .red
        case "cancelled": return .secondary
        default: return .blue
        }
    }

    private var resultSymbol: String {
        switch model.knowledgeResponse?.status {
        case "ready": return "checkmark.circle.fill"
        case "error", "blocked": return "exclamationmark.triangle.fill"
        case "cancelled": return "stop.circle"
        default: return "circle.dotted"
        }
    }

    private var evidence: [[String: JSONValue]] {
        model.knowledgeResponse?.evidence ?? []
    }

    private var sources: [[String: JSONValue]] {
        model.knowledgeResponse?.sources ?? []
    }

    private var notionSources: [[String: JSONValue]] {
        sources.filter { $0["kind"]?.stringValue == "notion" }
    }

    private var contextInjection: [String: JSONValue]? {
        model.knowledgeResponse?.diagnostics?.objectValue["contextInjection"]?.objectValue
    }

    private var notionStatusTitle: String {
        let status = model.knowledgeResponse?.notion?.objectValue["status"]?.stringValue ?? ""
        switch status {
        case "done": return "完成"
        case "queued", "running": return "等待"
        case "stale_dropped": return "已丢弃旧结果"
        case "not_configured": return "未配置"
        case "submit_failed", "poll_failed": return "失败"
        default: return model.knowledgeIncludeNotion ? "等待" : "未启用"
        }
    }

    private var organizeRunId: String? {
        model.knowledgeResponse?.result?.objectValue["plan"]?.objectValue["runId"]?.stringValue
    }

    private var organizeDiffs: [[String: JSONValue]] {
        let run = model.knowledgeDraftRun?.objectValue.isEmpty == false
            ? model.knowledgeDraftRun?.objectValue
            : model.knowledgeResponse?.result?.objectValue["storedRun"]?.objectValue
        return run?["diffs"]?.arrayValue.map(\.objectValue) ?? []
    }

    private var databaseRunStatus: String {
        if !model.knowledgeDatabaseActionStatus.isEmpty { return model.knowledgeDatabaseActionStatus }
        if let status = model.knowledgeDraftRun?.objectValue["status"]?.stringValue, !status.isEmpty { return status }
        return model.knowledgeResponse?.result?.objectValue["storedRun"]?.objectValue["status"]?.stringValue ?? ""
    }

    private var databaseDraftGroups: [DatabaseDraftGroup] {
        let diffs = organizeDiffs.map(DatabaseDraftDiff.init)
        let definitions: [(String, String, String, Color)] = [
            ("groups", "内容分组", "square.grid.2x2", .indigo),
            ("books", "主题书", "books.vertical", .blue),
            ("atoms", "记忆条目", "circle.hexagongrid", .teal),
            ("semanticTags", "语义标签", "tag.fill", .purple),
            ("tags", "标签关系", "point.3.connected.trianglepath.dotted", .purple),
            ("phrases", "可用短语", "text.badge.plus", .green),
            ("negative", "屏蔽与替代", "hand.raised", .orange),
        ]
        return definitions.compactMap { definition in
            let (key, title, symbol, color) = definition
            let items = diffs.filter { $0.groupKey == key }
            return items.isEmpty ? nil : DatabaseDraftGroup(key: key, title: title, symbol: symbol, color: color, items: items)
        }
    }

    private func databaseDiffSelected(_ diff: [String: JSONValue]) -> Bool {
        diff["status"]?.stringValue != "rejected"
    }

    private func databaseDiffSymbol(_ operation: String) -> String {
        switch operation {
        case "upsert_semantic_group": return "square.grid.2x2"
        case "upsert_semantic_tag": return "tag.fill"
        case "upsert_memory_book": return "book.closed"
        case "upsert_memory_atom": return "circle.hexagongrid"
        case "upsert_tag_edge": return "point.3.connected.trianglepath.dotted"
        case "add_phrase_candidate": return "text.badge.plus"
        case "add_negative_phrase": return "hand.raised"
        default: return "arrow.triangle.branch"
        }
    }
}

private struct DatabaseDraftGroup {
    let key: String
    let title: String
    let symbol: String
    let color: Color
    let items: [DatabaseDraftDiff]
}

private struct DatabaseDraftDiff: Identifiable {
    let raw: [String: JSONValue]

    var id: Int { Int(raw["diffId"]?.numberValue ?? 0) }
    var operation: String { raw["op"]?.stringValue ?? "" }
    var payload: [String: JSONValue] { raw["payload"]?.objectValue ?? [:] }
    var selected: Bool { raw["status"]?.stringValue != "rejected" }

    var groupKey: String {
        switch operation {
        case "upsert_semantic_group": return "groups"
        case "upsert_semantic_tag": return "semanticTags"
        case "upsert_memory_book": return "books"
        case "upsert_memory_atom": return "atoms"
        case "upsert_tag_edge": return "tags"
        case "add_phrase_candidate": return "phrases"
        default: return "negative"
        }
    }

    var title: String {
        switch operation {
        case "upsert_semantic_group": return value("title", fallback: "未命名分组")
        case "upsert_semantic_tag": return value("name", fallback: "未命名标签")
        case "upsert_memory_book": return value("title", fallback: "未命名主题书")
        case "upsert_memory_atom": return value("canonicalText", fallback: "未命名记忆")
        case "upsert_tag_edge": return "\(value("src", fallback: "标签")) → \(value("dst", fallback: "标签"))"
        case "add_phrase_candidate": return value("text", fallback: "未命名短语")
        case "add_negative_phrase": return value("text", fallback: "未命名屏蔽项")
        case "supersede_memory": return "用新记忆替代旧版本"
        default: return "待审阅变更"
        }
    }

    var detail: String {
        switch operation {
        case "upsert_semantic_group": return value("description")
        case "upsert_semantic_tag": return value("description")
        case "upsert_memory_book": return value("summary")
        case "upsert_memory_atom": return value("summary")
        case "upsert_tag_edge": return "关系：\(value("edgeType", fallback: "相关"))"
        case "add_phrase_candidate": return value("reason")
        case "add_negative_phrase": return value("reason")
        case "supersede_memory": return "只保留更新后的事实，旧版本可通过回滚恢复。"
        default: return ""
        }
    }

    var tags: [String] { payload["tags"]?.arrayValue.map(\.stringValue).filter { !$0.isEmpty } ?? [] }
    var tint: Color {
        switch groupKey {
        case "groups": return .indigo
        case "books": return .blue
        case "atoms": return .teal
        case "semanticTags", "tags": return .purple
        case "phrases": return .green
        default: return .orange
        }
    }

    private func value(_ key: String, fallback: String = "") -> String {
        let text = payload[key]?.stringValue.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return text.isEmpty ? fallback : text
    }
}

private struct DatabaseDraftEditorSheet: View {
    let diff: [String: JSONValue]
    let onCancel: () -> Void
    let onSave: ([String: JSONValue]) -> Void

    @State private var first: String
    @State private var second: String
    @State private var tags: String
    @State private var third: String

    private var operation: String { diff["op"]?.stringValue ?? "" }
    private var original: [String: JSONValue] { diff["payload"]?.objectValue ?? [:] }

    init(
        diff: [String: JSONValue],
        onCancel: @escaping () -> Void,
        onSave: @escaping ([String: JSONValue]) -> Void
    ) {
        self.diff = diff
        self.onCancel = onCancel
        self.onSave = onSave
        let operation = diff["op"]?.stringValue ?? ""
        let payload = diff["payload"]?.objectValue ?? [:]
        let fields = Self.fields(operation: operation, payload: payload)
        _first = State(initialValue: fields.0)
        _second = State(initialValue: fields.1)
        _tags = State(initialValue: fields.2)
        _third = State(initialValue: fields.3)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                Image(systemName: "pencil.and.list.clipboard")
                    .font(.system(size: 22))
                    .foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text(editorTitle).font(.title3.weight(.semibold))
                    Text("修改只保存在草案中，应用前仍可取消勾选。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            formFields
            HStack {
                Spacer()
                Button("取消", action: onCancel)
                Button("保存草案") { onSave(updatedPayload) }
                    .buttonStyle(.borderedProminent)
                    .disabled(first.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(22)
        .frame(width: 560)
    }

    @ViewBuilder
    private var formFields: some View {
        switch operation {
        case "upsert_semantic_group":
            labeledField("分组名称", text: $first)
            labeledEditor("分组说明", text: $second)
            labeledField("别名（逗号分隔）", text: $tags)
        case "upsert_semantic_tag":
            labeledField("标签名称", text: $first)
            labeledEditor("标签说明", text: $second)
            labeledField("别名（逗号分隔）", text: $tags)
        case "upsert_memory_book":
            labeledField("主题", text: $first)
            labeledEditor("摘要", text: $second)
            labeledField("标签（逗号分隔）", text: $tags)
        case "upsert_memory_atom":
            labeledEditor("记忆内容", text: $first)
            labeledEditor("简短说明", text: $second)
            labeledField("标签（逗号分隔）", text: $tags)
        case "upsert_tag_edge":
            labeledField("来源标签", text: $first)
            labeledField("关联标签", text: $second)
            labeledField("关系类型", text: $third)
        case "add_phrase_candidate":
            labeledField("短语", text: $first)
            labeledField("拼音", text: $second)
            labeledEditor("收录理由", text: $third)
            labeledField("标签（逗号分隔）", text: $tags)
        case "add_negative_phrase":
            labeledField("屏蔽内容", text: $first)
            labeledEditor("屏蔽原因", text: $second)
        default:
            Text("这类关系变更没有可安全编辑的正文，可取消勾选后重新生成。")
                .foregroundStyle(.secondary)
        }
    }

    private func labeledField(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            TextField(label, text: text).textFieldStyle(.roundedBorder)
        }
    }

    private func labeledEditor(_ label: String, text: Binding<String>) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            TextEditor(text: text)
                .font(.system(size: 14))
                .frame(minHeight: 74)
                .padding(6)
                .background(Color(nsColor: .controlBackgroundColor))
                .clipShape(RoundedRectangle(cornerRadius: 6))
                .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color(nsColor: .separatorColor), lineWidth: 0.7))
        }
    }

    private var editorTitle: String {
        switch operation {
        case "upsert_semantic_group": return "编辑内容分组"
        case "upsert_semantic_tag": return "编辑语义标签"
        case "upsert_memory_book": return "编辑主题书"
        case "upsert_memory_atom": return "编辑记忆条目"
        case "upsert_tag_edge": return "编辑标签关系"
        case "add_phrase_candidate": return "编辑可用短语"
        case "add_negative_phrase": return "编辑屏蔽规则"
        default: return "审阅变更"
        }
    }

    private var updatedPayload: [String: JSONValue] {
        var payload = original
        let tagValues = tags
            .split(whereSeparator: { $0 == "," || $0 == "，" || $0 == "\n" })
            .map { String($0).trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty }
        switch operation {
        case "upsert_semantic_group":
            payload["title"] = .string(first)
            payload["description"] = .string(second)
            payload["aliases"] = .array(tagValues.map(JSONValue.string))
        case "upsert_semantic_tag":
            payload["name"] = .string(first)
            payload["description"] = .string(second)
            payload["aliases"] = .array(tagValues.map(JSONValue.string))
        case "upsert_memory_book":
            payload["title"] = .string(first)
            payload["summary"] = .string(second)
            payload["tags"] = .array(tagValues.map(JSONValue.string))
        case "upsert_memory_atom":
            payload["canonicalText"] = .string(first)
            payload["summary"] = .string(second)
            payload["tags"] = .array(tagValues.map(JSONValue.string))
        case "upsert_tag_edge":
            payload["src"] = .string(first)
            payload["dst"] = .string(second)
            payload["edgeType"] = .string(third)
        case "add_phrase_candidate":
            payload["text"] = .string(first)
            payload["pinyin"] = .string(second)
            payload["reason"] = .string(third)
            payload["tags"] = .array(tagValues.map(JSONValue.string))
        case "add_negative_phrase":
            payload["text"] = .string(first)
            payload["reason"] = .string(second)
        default: break
        }
        return payload
    }

    private static func fields(
        operation: String,
        payload: [String: JSONValue]
    ) -> (String, String, String, String) {
        let tags = payload["tags"]?.arrayValue.map(\.stringValue).joined(separator: "，") ?? ""
        switch operation {
        case "upsert_semantic_group": return (payload["title"]?.stringValue ?? "", payload["description"]?.stringValue ?? "", payload["aliases"]?.arrayValue.map(\.stringValue).joined(separator: "，") ?? "", "")
        case "upsert_semantic_tag": return (payload["name"]?.stringValue ?? "", payload["description"]?.stringValue ?? "", payload["aliases"]?.arrayValue.map(\.stringValue).joined(separator: "，") ?? "", "")
        case "upsert_memory_book": return (payload["title"]?.stringValue ?? "", payload["summary"]?.stringValue ?? "", tags, "")
        case "upsert_memory_atom": return (payload["canonicalText"]?.stringValue ?? "", payload["summary"]?.stringValue ?? "", tags, "")
        case "upsert_tag_edge": return (payload["src"]?.stringValue ?? "", payload["dst"]?.stringValue ?? "", "", payload["edgeType"]?.stringValue ?? "related")
        case "add_phrase_candidate": return (payload["text"]?.stringValue ?? "", payload["pinyin"]?.stringValue ?? "", tags, payload["reason"]?.stringValue ?? "")
        case "add_negative_phrase": return (payload["text"]?.stringValue ?? "", payload["reason"]?.stringValue ?? "", "", "")
        default: return ("不可编辑", "", "", "")
        }
    }
}
