import SwiftUI

struct RagAndModelsPage: View {
    @EnvironmentObject private var model: AppModel
    @State private var confirmingDatabaseApply = false
    @State private var confirmingDatabaseRollback = false

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
            PageHeader(title: "个人知识工作台", subtitle: "本地 RAG、DeepSeek 与 Notion 多源知识")
            Spacer()
            routeIndicator(
                title: "DeepSeek",
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
                HStack(spacing: 12) {
                    Image(systemName: "cylinder.split.1x2")
                        .font(.system(size: 24))
                        .foregroundStyle(.blue)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("生成 Memory Book 整理草案").font(.headline)
                        Text("结果先进入 draft，验证通过后仍需人工审阅。")
                            .font(.callout)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
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
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text("整理草案").font(.headline)
                Text(databaseRunStatus.uppercased())
                    .font(.caption2.monospaced().weight(.semibold))
                    .foregroundStyle(databaseRunStatus == "applied" ? .green : .orange)
                Spacer()
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
            ForEach(Array(organizeDiffs.prefix(10).enumerated()), id: \.offset) { _, diff in
                HStack(spacing: 10) {
                    Image(systemName: databaseDiffSymbol(diff["op"]?.stringValue ?? ""))
                        .foregroundStyle(.blue)
                        .frame(width: 18)
                    Text(diff["op"]?.stringValue.replacingOccurrences(of: "_", with: " ") ?? "change")
                        .font(.callout.monospaced())
                        .frame(width: 180, alignment: .leading)
                    Text(diff["targetId"]?.stringValue ?? "")
                        .lineLimit(1)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text(diff["status"]?.stringValue ?? "pending")
                        .font(.caption.monospaced())
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
                Divider()
            }
            if organizeDiffs.count > 10 {
                Text("另有 \(organizeDiffs.count - 10) 项变更")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
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
        case .organizeDatabase: return ""
        }
    }

    private var runButtonTitle: String {
        model.knowledgeMode == .organizeDatabase ? "生成草案" : "开始"
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
        case "generating_local": return "DeepSeek 正在根据已召回证据生成正文"
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
        model.knowledgeResponse?.result?.objectValue["storedRun"]?.objectValue["diffs"]?.arrayValue.map(\.objectValue) ?? []
    }

    private var databaseRunStatus: String {
        if !model.knowledgeDatabaseActionStatus.isEmpty { return model.knowledgeDatabaseActionStatus }
        return model.knowledgeResponse?.result?.objectValue["storedRun"]?.objectValue["status"]?.stringValue ?? ""
    }

    private func databaseDiffSymbol(_ operation: String) -> String {
        switch operation {
        case "upsert_memory_book": return "book.closed"
        case "upsert_memory_atom": return "circle.hexagongrid"
        case "upsert_tag_edge": return "point.3.connected.trianglepath.dotted"
        case "add_phrase_candidate": return "text.badge.plus"
        case "add_negative_phrase": return "hand.raised"
        default: return "arrow.triangle.branch"
        }
    }
}
