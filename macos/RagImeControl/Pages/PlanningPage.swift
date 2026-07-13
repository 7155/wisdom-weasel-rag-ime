import SwiftUI

struct PlanningPage: View {
    @EnvironmentObject private var model: AppModel
    @State private var intention = ""
    @State private var notes = ""
    @State private var reflection = ""
    @State private var taskEditor: PlanningTaskItem?
    @State private var newTaskPresented = false
    @State private var goalEditor: PlanningGoalItem?
    @State private var newGoalPresented = false

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let dashboard = model.planning {
                ScrollView {
                    VStack(alignment: .leading, spacing: 22) {
                        assistantBand(dashboard)
                        completionSuggestions(dashboard)
                        HStack(alignment: .top, spacing: 28) {
                            dailyColumn(dashboard)
                                .frame(maxWidth: .infinity, alignment: .topLeading)
                            Divider()
                            goalColumn(dashboard)
                                .frame(width: 330, alignment: .topLeading)
                        }
                        assistantConversation(dashboard)
                    }
                    .padding(.horizontal, 28)
                    .padding(.vertical, 22)
                    .frame(maxWidth: 1180)
                    .frame(maxWidth: .infinity)
                }
            } else {
                EmptyState(symbol: "checklist", text: "正在读取今天的规划")
            }
        }
        .task { await model.loadPlanning() }
        .onChange(of: model.planning?.plan.updatedAtMsFallback) { _ in syncDrafts() }
        .sheet(isPresented: $newTaskPresented) {
            PlanningTaskEditor(item: nil, goals: model.planning?.goals ?? []) { draft in
                Task {
                    if await model.savePlanningTask(
                        title: draft.title,
                        detail: draft.detail,
                        priority: draft.priority,
                        dueAtMs: draft.dueAtMs,
                        goalId: draft.goalId
                    ) { newTaskPresented = false }
                }
            }
        }
        .sheet(item: $taskEditor) { item in
            PlanningTaskEditor(item: item, goals: model.planning?.goals ?? []) { draft in
                Task {
                    if await model.savePlanningTask(
                        id: item.id,
                        title: draft.title,
                        detail: draft.detail,
                        priority: draft.priority,
                        status: item.status,
                        dueAtMs: draft.dueAtMs,
                        goalId: draft.goalId
                    ) { taskEditor = nil }
                }
            }
        }
        .sheet(isPresented: $newGoalPresented) {
            PlanningGoalEditor(item: nil) { draft in
                Task {
                    if await model.savePlanningGoal(
                        title: draft.title,
                        detail: draft.detail,
                        priority: draft.priority,
                        targetDate: draft.targetDate
                    ) { newGoalPresented = false }
                }
            }
        }
        .sheet(item: $goalEditor) { item in
            PlanningGoalEditor(item: item) { draft in
                Task {
                    if await model.savePlanningGoal(
                        id: item.id,
                        title: draft.title,
                        detail: draft.detail,
                        priority: draft.priority,
                        targetDate: draft.targetDate,
                        status: item.status
                    ) { goalEditor = nil }
                }
            }
        }
    }

    private var header: some View {
        HStack(spacing: 14) {
            PageHeader(title: "规划与任务", subtitle: "今天的方向、可完成任务与长期目标")
            Spacer()
            HStack(spacing: 4) {
                Button { Task { await model.changePlanningDay(by: -1) } } label: {
                    Image(systemName: "chevron.left")
                }
                .help("前一天")
                Button { Task { await model.loadTodayPlanning() } } label: {
                    Image(systemName: "calendar")
                }
                .help("回到今天")
                Button { Task { await model.changePlanningDay(by: 1) } } label: {
                    Image(systemName: "chevron.right")
                }
                .help("后一天")
            }
            .buttonStyle(.borderless)
            Text(model.planningDate)
                .font(.callout.monospacedDigit())
                .foregroundStyle(.secondary)
            if let summary = model.planning?.summary {
                Label("\(summary.completedTaskCount)/\(summary.taskCount)", systemImage: "checkmark.circle")
                    .font(.callout.weight(.semibold))
                ProgressView(value: summary.progress)
                    .frame(width: 110)
            }
        }
        .padding(.horizontal, 28)
        .padding(.vertical, 22)
    }

    private func assistantBand(_ dashboard: PlanningDashboardResponse) -> some View {
        HStack(spacing: 14) {
            RagImeAnimeCompanion(
                state: dashboard.assistant.tone == "celebrate" ? .done : .idle,
                size: 54
            )
            VStack(alignment: .leading, spacing: 4) {
                Text("今日助手").font(.headline)
                Text(dashboard.assistant.message)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer()
            Text(dashboard.date)
                .font(.callout.monospacedDigit())
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal, 16)
        .frame(minHeight: 78)
        .background(Color.accentColor.opacity(0.07))
        .overlay(alignment: .leading) { Rectangle().fill(Color.teal).frame(width: 3) }
    }

    @ViewBuilder
    private func completionSuggestions(_ dashboard: PlanningDashboardResponse) -> some View {
        if let completion = dashboard.recentDetectedCompletion, completion.undoAvailable {
            HStack(spacing: 12) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                Text(completion.message)
                    .font(.callout.weight(.medium))
                Spacer()
                Button("撤销") {
                    Task { await model.undoPlanningTaskEvent(id: completion.eventId) }
                }
                .disabled(model.planningBusy)
            }
            .padding(.horizontal, 14)
            .frame(minHeight: 48)
            .background(Color.green.opacity(0.07))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
        if !dashboard.pendingCompletionSuggestions.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Label("语音或输入中识别到可能完成的任务", systemImage: "checkmark.bubble")
                    .font(.headline)
                ForEach(dashboard.pendingCompletionSuggestions) { suggestion in
                    HStack(spacing: 10) {
                        ForEach(suggestion.candidateTasks) { task in
                            Button(task.title) {
                                Task { await model.resolvePlanningSuggestion(id: suggestion.id, taskId: task.id) }
                            }
                        }
                        Spacer()
                        Button("忽略") {
                            Task { await model.resolvePlanningSuggestion(id: suggestion.id, dismiss: true) }
                        }
                        .buttonStyle(.borderless)
                    }
                    .padding(.vertical, 6)
                }
            }
            .padding(14)
            .background(Color.orange.opacity(0.07))
            .clipShape(RoundedRectangle(cornerRadius: 8))
        }
    }

    private func dailyColumn(_ dashboard: PlanningDashboardResponse) -> some View {
        VStack(alignment: .leading, spacing: 18) {
            HStack {
                Label("今日计划", systemImage: "sun.max").font(.title3.weight(.semibold))
                Spacer()
                Button {
                    Task { _ = await model.saveDailyPlan(intention: intention, notes: notes, reflection: reflection) }
                } label: {
                    Label("保存", systemImage: "square.and.arrow.down")
                }
                .disabled(model.planningBusy)
            }
            VStack(alignment: .leading, spacing: 7) {
                Text("最重要的一件事").font(.callout.weight(.medium))
                TextField("今天完成什么", text: $intention)
            }
            VStack(alignment: .leading, spacing: 7) {
                Text("日间笔记").font(.callout.weight(.medium))
                TextEditor(text: $notes)
                    .font(.body)
                    .frame(minHeight: 82)
                    .padding(6)
                    .background(Color(nsColor: .textBackgroundColor))
                    .overlay(RoundedRectangle(cornerRadius: 7).stroke(Color(nsColor: .separatorColor), lineWidth: 0.6))
            }
            VStack(alignment: .leading, spacing: 7) {
                Text("复盘").font(.callout.weight(.medium))
                TextEditor(text: $reflection)
                    .font(.body)
                    .frame(minHeight: 62)
                    .padding(6)
                    .background(Color(nsColor: .textBackgroundColor))
                    .overlay(RoundedRectangle(cornerRadius: 7).stroke(Color(nsColor: .separatorColor), lineWidth: 0.6))
            }
            Divider()
            HStack {
                Label("任务", systemImage: "checklist").font(.title3.weight(.semibold))
                Spacer()
                Button { newTaskPresented = true } label: { Image(systemName: "plus") }
                    .help("新增任务")
            }
            if dashboard.tasks.isEmpty {
                Text("今天还没有任务").foregroundStyle(.secondary)
            } else {
                VStack(spacing: 8) {
                    ForEach(dashboard.tasks) { task in
                        PlanningTaskRow(item: task) {
                            Task {
                                _ = await model.performPlanningTaskAction(
                                    id: task.id,
                                    action: task.status == "done" ? "reopen" : "complete"
                                )
                            }
                        } edit: {
                            taskEditor = task
                        } start: {
                            Task { _ = await model.performPlanningTaskAction(id: task.id, action: "start") }
                        }
                    }
                }
            }
        }
    }

    private func goalColumn(_ dashboard: PlanningDashboardResponse) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                Label("长期目标", systemImage: "scope").font(.title3.weight(.semibold))
                Spacer()
                Button { newGoalPresented = true } label: { Image(systemName: "plus") }
                    .help("新增长期目标")
            }
            if dashboard.goals.isEmpty {
                Text("还没有长期目标").foregroundStyle(.secondary)
            } else {
                ForEach(dashboard.goals) { goal in
                    VStack(alignment: .leading, spacing: 6) {
                        HStack {
                            Text(goal.title).font(.headline).lineLimit(2)
                            Spacer()
                            Button { goalEditor = goal } label: { Image(systemName: "pencil") }
                                .buttonStyle(.borderless)
                                .help("编辑目标")
                        }
                        if !goal.detail.isEmpty {
                            Text(goal.detail).font(.callout).foregroundStyle(.secondary).lineLimit(4)
                        }
                        HStack {
                            PlanningPriorityLabel(priority: goal.priority)
                            if !goal.targetDate.isEmpty {
                                Text(goal.targetDate).font(.caption).foregroundStyle(.secondary)
                            }
                        }
                    }
                    .padding(.vertical, 10)
                    Divider()
                }
            }
        }
    }

    private func assistantConversation(_ dashboard: PlanningDashboardResponse) -> some View {
        VStack(alignment: .leading, spacing: 12) {
            Divider()
            Label("规划助手", systemImage: "bubble.left.and.bubble.right")
                .font(.title3.weight(.semibold))
            ForEach(dashboard.conversation.suffix(8)) { message in
                HStack {
                    if message.role == "user" { Spacer(minLength: 90) }
                    Text(message.content)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 9)
                        .background(message.role == "user" ? Color.accentColor.opacity(0.12) : Color(nsColor: .controlBackgroundColor))
                        .clipShape(RoundedRectangle(cornerRadius: 8))
                    if message.role != "user" { Spacer(minLength: 90) }
                }
            }
            HStack(spacing: 10) {
                TextField("询问今天的任务、进度或长期目标", text: $model.planningAssistantDraft)
                    .onSubmit { Task { await model.sendPlanningAssistantMessage() } }
                Button { Task { await model.sendPlanningAssistantMessage() } } label: {
                    Image(systemName: "arrow.up.circle.fill")
                }
                .buttonStyle(.borderless)
                .help("发送")
                .disabled(model.planningAssistantDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
    }

    private func syncDrafts() {
        guard let plan = model.planning?.plan else { return }
        intention = plan.intention
        notes = plan.notes
        reflection = plan.reflection
    }
}

private struct PlanningTaskRow: View {
    let item: PlanningTaskItem
    let toggle: () -> Void
    let edit: () -> Void
    let start: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 11) {
            Button(action: toggle) {
                Image(systemName: item.status == "done" ? "checkmark.circle.fill" : "circle")
                    .font(.system(size: 18))
            }
            .buttonStyle(.borderless)
            .help(item.status == "done" ? "重新打开" : "标记完成")
            VStack(alignment: .leading, spacing: 4) {
                Text(item.title)
                    .font(.headline)
                    .strikethrough(item.status == "done")
                if !item.detail.isEmpty {
                    Text(item.detail).font(.callout).foregroundStyle(.secondary).lineLimit(2)
                }
                HStack(spacing: 8) {
                    PlanningPriorityLabel(priority: item.priority)
                    if let due = item.dueAtMs {
                        Text(Date(timeIntervalSince1970: Double(due) / 1000), style: .date)
                            .font(.caption).foregroundStyle(.secondary)
                    }
                    if item.status == "in_progress" {
                        Text("进行中").font(.caption).foregroundStyle(.teal)
                    }
                }
            }
            Spacer()
            Menu {
                if item.status == "todo" { Button("开始", action: start) }
                Button("编辑", action: edit)
                Button(item.status == "done" ? "重新打开" : "完成", action: toggle)
            } label: {
                Image(systemName: "ellipsis.circle")
            }
            .menuStyle(.borderlessButton)
            .frame(width: 24)
        }
        .padding(12)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private struct PlanningPriorityLabel: View {
    let priority: Int
    var body: some View {
        Text(label)
            .font(.caption2.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .frame(height: 19)
            .background(color.opacity(0.09))
            .clipShape(RoundedRectangle(cornerRadius: 4))
    }
    private var label: String { ["低", "普通", "高", "紧急"][max(0, min(3, priority))] }
    private var color: Color { priority >= 3 ? .red : (priority == 2 ? .orange : .secondary) }
}

private struct PlanningTaskDraft {
    let title: String
    let detail: String
    let priority: Int
    let dueAtMs: Int?
    let goalId: String
}

private struct PlanningTaskEditor: View {
    @Environment(\.dismiss) private var dismiss
    let item: PlanningTaskItem?
    let goals: [PlanningGoalItem]
    let save: (PlanningTaskDraft) -> Void
    @State private var title: String
    @State private var detail: String
    @State private var priority: Int
    @State private var dueEnabled: Bool
    @State private var dueDate: Date
    @State private var goalId: String

    init(item: PlanningTaskItem?, goals: [PlanningGoalItem], save: @escaping (PlanningTaskDraft) -> Void) {
        self.item = item
        self.goals = goals
        self.save = save
        _title = State(initialValue: item?.title ?? "")
        _detail = State(initialValue: item?.detail ?? "")
        _priority = State(initialValue: item?.priority ?? 1)
        _dueEnabled = State(initialValue: item?.dueAtMs != nil)
        _dueDate = State(initialValue: item?.dueAtMs.map { Date(timeIntervalSince1970: Double($0) / 1000) } ?? Date())
        _goalId = State(initialValue: item?.goalId ?? "")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(item == nil ? "新增任务" : "编辑任务").font(.title2.weight(.semibold))
            TextField("任务名称", text: $title)
            TextEditor(text: $detail).frame(height: 88).overlay(RoundedRectangle(cornerRadius: 7).stroke(.separator))
            Picker("优先级", selection: $priority) {
                Text("低").tag(0); Text("普通").tag(1); Text("高").tag(2); Text("紧急").tag(3)
            }
            Toggle("设置截止时间", isOn: $dueEnabled)
            if dueEnabled { DatePicker("截止", selection: $dueDate) }
            if !goals.isEmpty {
                Picker("关联目标", selection: $goalId) {
                    Text("不关联").tag("")
                    ForEach(goals) { Text($0.title).tag($0.id) }
                }
            }
            HStack {
                Spacer()
                Button("取消") { dismiss() }
                Button("保存") {
                    save(.init(
                        title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                        detail: detail.trimmingCharacters(in: .whitespacesAndNewlines),
                        priority: priority,
                        dueAtMs: dueEnabled ? Int(dueDate.timeIntervalSince1970 * 1000) : nil,
                        goalId: goalId
                    ))
                }
                .buttonStyle(.borderedProminent)
                .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(24)
        .frame(width: 480)
    }
}

private struct PlanningGoalDraft {
    let title: String
    let detail: String
    let priority: Int
    let targetDate: String
}

private struct PlanningGoalEditor: View {
    @Environment(\.dismiss) private var dismiss
    let item: PlanningGoalItem?
    let save: (PlanningGoalDraft) -> Void
    @State private var title: String
    @State private var detail: String
    @State private var priority: Int
    @State private var targetDate: String

    init(item: PlanningGoalItem?, save: @escaping (PlanningGoalDraft) -> Void) {
        self.item = item
        self.save = save
        _title = State(initialValue: item?.title ?? "")
        _detail = State(initialValue: item?.detail ?? "")
        _priority = State(initialValue: item?.priority ?? 1)
        _targetDate = State(initialValue: item?.targetDate ?? "")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(item == nil ? "新增长期目标" : "编辑长期目标").font(.title2.weight(.semibold))
            TextField("目标名称", text: $title)
            TextEditor(text: $detail).frame(height: 100).overlay(RoundedRectangle(cornerRadius: 7).stroke(.separator))
            Picker("优先级", selection: $priority) {
                Text("低").tag(0); Text("普通").tag(1); Text("高").tag(2); Text("紧急").tag(3)
            }
            TextField("目标日期（YYYY-MM-DD，可留空）", text: $targetDate)
            HStack {
                Spacer()
                Button("取消") { dismiss() }
                Button("保存") {
                    save(.init(
                        title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                        detail: detail.trimmingCharacters(in: .whitespacesAndNewlines),
                        priority: priority,
                        targetDate: targetDate.trimmingCharacters(in: .whitespacesAndNewlines)
                    ))
                }
                .buttonStyle(.borderedProminent)
                .disabled(title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(24)
        .frame(width: 480)
    }
}

private extension PlanningPlanItem {
    var updatedAtMsFallback: String { "\(id)|\(intention)|\(notes)|\(reflection)" }
}
