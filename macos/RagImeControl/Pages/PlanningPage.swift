import Foundation
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
    @State private var taskGoalSeed = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let dashboard = model.planning {
                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        assistantBand(dashboard)
                        completionSuggestions(dashboard)
                        ViewThatFits(in: .horizontal) {
                            HStack(alignment: .top, spacing: 0) {
                                dailyColumn(dashboard)
                                    .frame(maxWidth: .infinity, alignment: .topLeading)
                                    .padding(.trailing, 28)
                                Divider()
                                goalColumn(dashboard)
                                    .frame(width: 370, alignment: .topLeading)
                                    .padding(.leading, 28)
                            }
                            .frame(minWidth: 980, alignment: .topLeading)

                            VStack(alignment: .leading, spacing: 28) {
                                dailyColumn(dashboard)
                                Divider()
                                goalColumn(dashboard)
                            }
                        }
                        assistantConversation(dashboard)
                    }
                    .padding(.horizontal, ControlDesign.pageHorizontalPadding)
                    .padding(.vertical, 24)
                    .frame(maxWidth: 1360)
                    .frame(maxWidth: .infinity)
                }
            } else {
                EmptyState(symbol: "checklist", text: "正在读取今天的规划")
            }
        }
        .task { await model.loadPlanning() }
        .onChange(of: model.planning?.plan.updatedAtMsFallback) { _ in syncDrafts() }
        .sheet(isPresented: $newTaskPresented, onDismiss: { taskGoalSeed = "" }) {
            PlanningTaskEditor(
                item: nil,
                goals: model.planning?.goals ?? [],
                initialGoalId: taskGoalSeed
            ) { draft in
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
        HStack(spacing: 18) {
            PageHeader(title: "规划与任务", subtitle: "今天的方向、可完成任务与长期目标")
            Spacer()
            if model.planningLoading || model.planningBusy {
                ProgressView()
                    .controlSize(.small)
                    .help(model.planningLoading ? "正在切换日期" : "正在保存")
            }
            HStack(spacing: 6) {
                Button { Task { await model.changePlanningDay(by: -1) } } label: {
                    Image(systemName: "chevron.left")
                        .frame(width: 18, height: 20)
                }
                .help("前一天")
                DatePicker("日期", selection: planningDateBinding, displayedComponents: .date)
                    .labelsHidden()
                    .datePickerStyle(.field)
                    .frame(width: 132)
                    .help("选择日期")
                Button { Task { await model.changePlanningDay(by: 1) } } label: {
                    Image(systemName: "chevron.right")
                        .frame(width: 18, height: 20)
                }
                .help("后一天")
                Button("今天") { Task { await model.loadTodayPlanning() } }
                    .help("回到今天")
                    .disabled(isShowingToday)
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(model.planningLoading || model.planningBusy)
            if let summary = model.planning?.summary {
                VStack(alignment: .trailing, spacing: 5) {
                    HStack(spacing: 6) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(summary.taskCount > 0 && summary.openTaskCount == 0 ? Color.green : ControlDesign.brand)
                        Text("\(summary.completedTaskCount) / \(summary.taskCount) 已完成")
                            .font(.caption.weight(.semibold))
                            .monospacedDigit()
                    }
                    ProgressView(value: summary.progress)
                        .tint(summary.taskCount > 0 && summary.openTaskCount == 0 ? .green : ControlDesign.brand)
                        .frame(width: 128)
                }
            }
        }
        .padding(.horizontal, ControlDesign.pageHorizontalPadding)
        .padding(.vertical, 20)
    }

    private func assistantBand(_ dashboard: PlanningDashboardResponse) -> some View {
        HStack(spacing: 16) {
            RagImeAnimeCompanion(
                state: model.planningBusy ? .thinking : (dashboard.assistant.tone == "celebrate" ? .done : .idle),
                size: 66
            )
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 8) {
                    Text(isShowingToday ? "今日助手" : "当日回顾")
                        .font(.headline)
                    Text(dashboard.date)
                        .font(.caption.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                Text(dashboard.assistant.message)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 18)
            HStack(spacing: 8) {
                PlanningMetricBadge(
                    value: "\(dashboard.summary.openTaskCount)",
                    label: "待办",
                    symbol: "circle.dashed",
                    tint: .orange
                )
                PlanningMetricBadge(
                    value: "\(dashboard.summary.completedTaskCount)",
                    label: "完成",
                    symbol: "checkmark.circle.fill",
                    tint: .green
                )
                PlanningMetricBadge(
                    value: "\(dashboard.summary.goalCount)",
                    label: "目标",
                    symbol: "scope",
                    tint: ControlDesign.brand
                )
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 14)
        .frame(minHeight: 98)
        .background(ControlDesign.brand.opacity(0.075))
        .overlay(alignment: .leading) { Rectangle().fill(ControlDesign.brand).frame(width: 4) }
        .overlay(alignment: .bottom) { Rectangle().fill(ControlDesign.brand.opacity(0.18)).frame(height: 1) }
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
                .buttonStyle(.bordered)
                .disabled(model.planningBusy)
            }
            .padding(.horizontal, 16)
            .frame(minHeight: 52)
            .background(Color.green.opacity(0.07))
            .overlay(alignment: .leading) { Rectangle().fill(Color.green).frame(width: 3) }
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
                            .buttonStyle(.borderedProminent)
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
            .padding(16)
            .background(Color.orange.opacity(0.07))
            .overlay(alignment: .leading) { Rectangle().fill(Color.orange).frame(width: 3) }
        }
    }

    private func dailyColumn(_ dashboard: PlanningDashboardResponse) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                PlanningSectionTitle(
                    title: "今日计划",
                    subtitle: hasUnsavedPlanChanges ? "有未保存的更改" : "内容已保存",
                    symbol: "sun.max.fill",
                    tint: .orange
                )
                Spacer()
                Button {
                    Task { _ = await model.saveDailyPlan(intention: intention, notes: notes, reflection: reflection) }
                } label: {
                    Label("保存计划", systemImage: "square.and.arrow.down")
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.planningBusy || !hasUnsavedPlanChanges)
            }

            VStack(alignment: .leading, spacing: 8) {
                Label("最重要的一件事", systemImage: "flag.fill")
                    .font(.callout.weight(.semibold))
                    .foregroundStyle(ControlDesign.brand)
                HStack(spacing: 10) {
                    Image(systemName: "target")
                        .foregroundStyle(ControlDesign.brand)
                    TextField("今天最值得完成的结果", text: $intention)
                        .textFieldStyle(.plain)
                        .font(.body.weight(.medium))
                }
                .padding(.horizontal, 12)
                .frame(minHeight: 42)
                .background(ControlDesign.brand.opacity(0.055))
                .overlay(
                    RoundedRectangle(cornerRadius: 7)
                        .stroke(ControlDesign.brand.opacity(0.28), lineWidth: 0.8)
                )
            }

            HStack(alignment: .top, spacing: 14) {
                PlanningTextArea(
                    title: "日间笔记",
                    symbol: "note.text",
                    placeholder: "记录过程、阻塞和临时想法",
                    text: $notes,
                    minHeight: 112
                )
                PlanningTextArea(
                    title: "复盘",
                    symbol: "arrow.triangle.2.circlepath",
                    placeholder: "完成了什么，下一步是什么",
                    text: $reflection,
                    minHeight: 112
                )
            }

            Divider()
            HStack {
                PlanningSectionTitle(
                    title: "任务",
                    subtitle: dashboard.tasks.isEmpty ? "今天还没有任务" : "\(dashboard.summary.openTaskCount) 项待完成",
                    symbol: "checklist",
                    tint: .indigo
                )
                Spacer()
                Button {
                    taskGoalSeed = ""
                    newTaskPresented = true
                } label: {
                    Label("新建任务", systemImage: "plus")
                }
                .buttonStyle(.bordered)
                .disabled(model.planningBusy)
            }
            if dashboard.tasks.isEmpty {
                PlanningEmptyAction(
                    symbol: "checklist",
                    title: "添加今天的第一个任务",
                    detail: "把重点拆成一个可以完成的动作"
                ) {
                    taskGoalSeed = ""
                    newTaskPresented = true
                }
            } else {
                VStack(spacing: 10) {
                    ForEach(dashboard.tasks) { task in
                        PlanningTaskRow(item: task, busy: model.planningBusy) {
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
        VStack(alignment: .leading, spacing: 16) {
            HStack {
                PlanningSectionTitle(
                    title: "长期目标",
                    subtitle: dashboard.goals.isEmpty ? "先建立一个长期方向" : "\(dashboard.goals.count) 个进行中",
                    symbol: "scope",
                    tint: ControlDesign.brand
                )
                Spacer()
                Button { newGoalPresented = true } label: {
                    Label("新建目标", systemImage: "plus")
                }
                .buttonStyle(.bordered)
                .disabled(model.planningBusy)
            }
            if dashboard.goals.isEmpty {
                PlanningEmptyAction(
                    symbol: "scope",
                    title: "建立长期目标",
                    detail: "目标可以持续数周，并逐步拆成每日任务"
                ) {
                    newGoalPresented = true
                }
            } else {
                ForEach(dashboard.goals) { goal in
                    PlanningGoalRow(
                        item: goal,
                        busy: model.planningBusy,
                        edit: { goalEditor = goal },
                        makeTask: {
                            taskGoalSeed = goal.id
                            newTaskPresented = true
                        },
                        complete: { updateGoal(goal, status: "completed") },
                        archive: { updateGoal(goal, status: "archived") }
                    )
                }
            }
        }
    }

    private func assistantConversation(_ dashboard: PlanningDashboardResponse) -> some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack {
                PlanningSectionTitle(
                    title: "规划助手",
                    subtitle: "围绕当前日期的计划、任务和目标",
                    symbol: "bubble.left.and.bubble.right.fill",
                    tint: .blue
                )
                Spacer()
                if model.planningBusy {
                    Label("正在整理", systemImage: "sparkles")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            if dashboard.conversation.isEmpty {
                HStack(spacing: 8) {
                    quickPrompt("梳理今天的重点", symbol: "wand.and.stars")
                    quickPrompt("检查未完成任务", symbol: "checklist")
                    quickPrompt("从目标拆一个任务", symbol: "arrow.turn.down.right")
                    Spacer()
                }
            } else {
                VStack(spacing: 10) {
                    ForEach(dashboard.conversation.suffix(8)) { message in
                        PlanningConversationBubble(message: message)
                    }
                }
            }

            HStack(spacing: 10) {
                TextField("询问今天的任务、进度或长期目标", text: $model.planningAssistantDraft)
                    .textFieldStyle(.plain)
                    .padding(.horizontal, 12)
                    .frame(height: 40)
                    .background(Color(nsColor: .textBackgroundColor))
                    .overlay(
                        RoundedRectangle(cornerRadius: 7)
                            .stroke(ControlDesign.hairline, lineWidth: 0.8)
                    )
                    .onSubmit { Task { await model.sendPlanningAssistantMessage() } }
                Button { Task { await model.sendPlanningAssistantMessage() } } label: {
                    Label("发送", systemImage: "arrow.up")
                        .frame(minWidth: 62)
                }
                .buttonStyle(.borderedProminent)
                .help("发送")
                .disabled(
                    model.planningBusy ||
                    model.planningAssistantDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
            }
        }
        .padding(.vertical, 20)
        .padding(.horizontal, 18)
        .background(Color.blue.opacity(0.035))
        .overlay(alignment: .top) { Rectangle().fill(Color.blue.opacity(0.15)).frame(height: 1) }
    }

    private func syncDrafts() {
        guard let plan = model.planning?.plan else { return }
        intention = plan.intention
        notes = plan.notes
        reflection = plan.reflection
    }

    private var hasUnsavedPlanChanges: Bool {
        guard let plan = model.planning?.plan else { return false }
        return intention != plan.intention || notes != plan.notes || reflection != plan.reflection
    }

    private var planningDateBinding: Binding<Date> {
        Binding(
            get: { PlanningDateCodec.date(from: model.planningDate) ?? Date() },
            set: { date in
                let value = PlanningDateCodec.string(from: date)
                guard value != model.planningDate else { return }
                Task { await model.loadPlanning(date: value) }
            }
        )
    }

    private var isShowingToday: Bool {
        model.planningDate == PlanningDateCodec.string(from: Date())
    }

    private func quickPrompt(_ title: String, symbol: String) -> some View {
        Button {
            Task { await model.sendPlanningAssistantMessage(title) }
        } label: {
            Label(title, systemImage: symbol)
        }
        .buttonStyle(.bordered)
        .controlSize(.small)
        .disabled(model.planningBusy)
    }

    private func updateGoal(_ goal: PlanningGoalItem, status: String) {
        Task {
            _ = await model.savePlanningGoal(
                id: goal.id,
                title: goal.title,
                detail: goal.detail,
                priority: goal.priority,
                targetDate: goal.targetDate,
                status: status
            )
        }
    }
}

private struct PlanningTaskRow: View {
    let item: PlanningTaskItem
    let busy: Bool
    let toggle: () -> Void
    let edit: () -> Void
    let start: () -> Void

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Button(action: toggle) {
                Image(systemName: statusSymbol)
                    .font(.system(size: 19, weight: .medium))
                    .foregroundStyle(statusColor)
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.plain)
            .help(item.status == "done" ? "重新打开" : "标记完成")
            .disabled(busy || item.status == "cancelled")

            VStack(alignment: .leading, spacing: 5) {
                Text(item.title)
                    .font(.headline)
                    .strikethrough(item.status == "done")
                    .foregroundStyle(item.status == "cancelled" ? .secondary : .primary)
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
                    } else if item.status == "cancelled" {
                        Text("已取消").font(.caption).foregroundStyle(.secondary)
                    }
                }
            }
            Spacer()

            if item.status == "todo" {
                Button(action: start) {
                    Label("开始", systemImage: "play.fill")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(busy)
            }
            Button(action: edit) {
                Image(systemName: "pencil")
                    .frame(width: 28, height: 28)
            }
            .buttonStyle(.plain)
            .help("编辑任务")
            .disabled(busy)
            Menu {
                if item.status == "todo" { Button("开始", action: start) }
                Button("编辑", action: edit)
                Button(item.status == "done" ? "重新打开" : "完成", action: toggle)
            } label: {
                Image(systemName: "ellipsis")
                    .frame(width: 28, height: 28)
            }
            .menuStyle(.borderlessButton)
            .frame(width: 30)
            .disabled(busy)
        }
        .padding(13)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(ControlDesign.hairline, lineWidth: 0.7)
        )
    }

    private var statusSymbol: String {
        switch item.status {
        case "done": return "checkmark.circle.fill"
        case "in_progress": return "circle.lefthalf.filled"
        case "cancelled": return "xmark.circle"
        default: return "circle"
        }
    }

    private var statusColor: Color {
        switch item.status {
        case "done": return .green
        case "in_progress": return ControlDesign.brand
        case "cancelled": return .secondary
        default: return .secondary
        }
    }
}

private struct PlanningGoalRow: View {
    let item: PlanningGoalItem
    let busy: Bool
    let edit: () -> Void
    let makeTask: () -> Void
    let complete: () -> Void
    let archive: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 11) {
            HStack(alignment: .top, spacing: 10) {
                Image(systemName: "scope")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(ControlDesign.brand)
                    .frame(width: 30, height: 30)
                    .background(ControlDesign.brand.opacity(0.09))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
                Text(item.title)
                    .font(.headline)
                    .lineLimit(3)
                Spacer(minLength: 6)
                Button(action: edit) {
                    Image(systemName: "pencil")
                        .frame(width: 28, height: 28)
                }
                .buttonStyle(.plain)
                .help("编辑目标")
                .disabled(busy)
                Menu {
                    Button("标记完成", action: complete)
                    Button("归档", action: archive)
                } label: {
                    Image(systemName: "ellipsis")
                        .frame(width: 28, height: 28)
                }
                .menuStyle(.borderlessButton)
                .frame(width: 30)
                .disabled(busy)
            }

            if !item.detail.isEmpty {
                Text(item.detail)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(4)
                    .fixedSize(horizontal: false, vertical: true)
            }

            HStack(spacing: 8) {
                PlanningPriorityLabel(priority: item.priority)
                if !item.targetDate.isEmpty {
                    Label(item.targetDate, systemImage: "calendar")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button(action: makeTask) {
                    Label("拆成任务", systemImage: "arrow.turn.down.right")
                }
                .buttonStyle(.bordered)
                .controlSize(.small)
                .disabled(busy)
            }
        }
        .padding(14)
        .background(Color(nsColor: .controlBackgroundColor))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(ControlDesign.hairline, lineWidth: 0.7)
        )
    }
}

private struct PlanningSectionTitle: View {
    let title: String
    let subtitle: String
    let symbol: String
    let tint: Color

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: symbol)
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 30, height: 30)
                .background(tint.opacity(0.09))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(.system(size: 17, weight: .semibold))
                Text(subtitle).font(.caption).foregroundStyle(.secondary).lineLimit(1)
            }
        }
    }
}

private struct PlanningMetricBadge: View {
    let value: String
    let label: String
    let symbol: String
    let tint: Color

    var body: some View {
        HStack(spacing: 7) {
            Image(systemName: symbol)
                .foregroundStyle(tint)
            VStack(alignment: .leading, spacing: 0) {
                Text(value)
                    .font(.system(size: 16, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                Text(label).font(.caption2).foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 10)
        .frame(height: 46)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.72))
        .overlay(
            RoundedRectangle(cornerRadius: 7)
                .stroke(tint.opacity(0.18), lineWidth: 0.7)
        )
        .clipShape(RoundedRectangle(cornerRadius: 7))
    }
}

private struct PlanningTextArea: View {
    let title: String
    let symbol: String
    let placeholder: String
    @Binding var text: String
    let minHeight: CGFloat

    var body: some View {
        VStack(alignment: .leading, spacing: 7) {
            Label(title, systemImage: symbol)
                .font(.callout.weight(.semibold))
            ZStack(alignment: .topLeading) {
                if text.isEmpty {
                    Text(placeholder)
                        .font(.body)
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 13)
                        .padding(.vertical, 12)
                        .allowsHitTesting(false)
                }
                TextEditor(text: $text)
                    .font(.body)
                    .scrollContentBackground(.hidden)
                    .padding(7)
                    .frame(minHeight: minHeight)
            }
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(
                RoundedRectangle(cornerRadius: 7)
                    .stroke(ControlDesign.hairline, lineWidth: 0.8)
            )
        }
        .frame(maxWidth: .infinity, alignment: .topLeading)
    }
}

private struct PlanningEmptyAction: View {
    let symbol: String
    let title: String
    let detail: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 13) {
                Image(systemName: symbol)
                    .font(.system(size: 20, weight: .medium))
                    .foregroundStyle(ControlDesign.brand)
                    .frame(width: 38, height: 38)
                    .background(ControlDesign.brand.opacity(0.09))
                    .clipShape(RoundedRectangle(cornerRadius: 7))
                VStack(alignment: .leading, spacing: 3) {
                    Text(title).font(.callout.weight(.semibold))
                    Text(detail).font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Image(systemName: "plus.circle.fill")
                    .font(.system(size: 18))
                    .foregroundStyle(ControlDesign.brand)
            }
            .padding(14)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .background(ControlDesign.brand.opacity(0.035))
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(
                    ControlDesign.brand.opacity(0.28),
                    style: StrokeStyle(lineWidth: 0.8, dash: [5, 4])
                )
        )
    }
}

private struct PlanningConversationBubble: View {
    let message: PlanningConversationMessage

    var body: some View {
        HStack(alignment: .top, spacing: 10) {
            if message.role == "user" { Spacer(minLength: 90) }
            if message.role != "user" {
                Image(systemName: "sparkles")
                    .foregroundStyle(ControlDesign.brand)
                    .frame(width: 26, height: 26)
                    .background(ControlDesign.brand.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            Text(message.content)
                .font(.callout)
                .textSelection(.enabled)
                .padding(.horizontal, 12)
                .padding(.vertical, 9)
                .background(
                    message.role == "user"
                        ? Color.blue.opacity(0.11)
                        : Color(nsColor: .controlBackgroundColor)
                )
                .clipShape(RoundedRectangle(cornerRadius: 8))
                .overlay(
                    RoundedRectangle(cornerRadius: 8)
                        .stroke(ControlDesign.hairline, lineWidth: message.role == "user" ? 0 : 0.6)
                )
            if message.role != "user" { Spacer(minLength: 90) }
        }
    }
}

private enum PlanningDateCodec {
    private static let formatter: DateFormatter = {
        let formatter = DateFormatter()
        formatter.calendar = Calendar.current
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd"
        return formatter
    }()

    static func string(from date: Date) -> String {
        formatter.string(from: date)
    }

    static func date(from value: String) -> Date? {
        formatter.date(from: value)
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
    @EnvironmentObject private var model: AppModel
    let item: PlanningTaskItem?
    let goals: [PlanningGoalItem]
    let save: (PlanningTaskDraft) -> Void
    @State private var title: String
    @State private var detail: String
    @State private var priority: Int
    @State private var dueEnabled: Bool
    @State private var dueDate: Date
    @State private var goalId: String

    init(
        item: PlanningTaskItem?,
        goals: [PlanningGoalItem],
        initialGoalId: String = "",
        save: @escaping (PlanningTaskDraft) -> Void
    ) {
        self.item = item
        self.goals = goals
        self.save = save
        _title = State(initialValue: item?.title ?? "")
        _detail = State(initialValue: item?.detail ?? "")
        _priority = State(initialValue: item?.priority ?? 1)
        _dueEnabled = State(initialValue: item?.dueAtMs != nil)
        _dueDate = State(initialValue: item?.dueAtMs.map { Date(timeIntervalSince1970: Double($0) / 1000) } ?? Date())
        _goalId = State(initialValue: item?.goalId ?? initialGoalId)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 12) {
                Image(systemName: item == nil ? "plus.square.fill" : "square.and.pencil")
                    .font(.system(size: 21, weight: .semibold))
                    .foregroundStyle(.indigo)
                    .frame(width: 40, height: 40)
                    .background(Color.indigo.opacity(0.09))
                    .clipShape(RoundedRectangle(cornerRadius: 7))
                VStack(alignment: .leading, spacing: 2) {
                    Text(item == nil ? "新增任务" : "编辑任务")
                        .font(.title2.weight(.semibold))
                    Text("定义一个明确、可以完成的动作")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            VStack(alignment: .leading, spacing: 7) {
                Text("任务名称").font(.callout.weight(.semibold))
                TextField("例如：完成输入法候选面板优化", text: $title)
                    .planningFieldChrome()
            }

            PlanningTextArea(
                title: "任务说明",
                symbol: "text.alignleft",
                placeholder: "补充验收标准、上下文或阻塞项",
                text: $detail,
                minHeight: 92
            )

            VStack(alignment: .leading, spacing: 8) {
                Text("优先级").font(.callout.weight(.semibold))
                Picker("优先级", selection: $priority) {
                    Text("低").tag(0)
                    Text("普通").tag(1)
                    Text("高").tag(2)
                    Text("紧急").tag(3)
                }
                .labelsHidden()
                .pickerStyle(.segmented)
            }

            HStack(spacing: 16) {
                Toggle("设置截止时间", isOn: $dueEnabled)
                if dueEnabled {
                    DatePicker("截止", selection: $dueDate)
                        .datePickerStyle(.field)
                }
            }
            if !goals.isEmpty {
                Picker("关联目标", selection: $goalId) {
                    Text("不关联").tag("")
                    ForEach(goals) { Text($0.title).tag($0.id) }
                }
                .pickerStyle(.menu)
            }

            Divider()
            HStack {
                if model.planningBusy {
                    ProgressView().controlSize(.small)
                    Text("正在保存").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("取消") { dismiss() }
                    .disabled(model.planningBusy)
                Button(item == nil ? "添加任务" : "保存修改") {
                    save(.init(
                        title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                        detail: detail.trimmingCharacters(in: .whitespacesAndNewlines),
                        priority: priority,
                        dueAtMs: dueEnabled ? Int(dueDate.timeIntervalSince1970 * 1000) : nil,
                        goalId: goalId
                    ))
                }
                .buttonStyle(.borderedProminent)
                .disabled(
                    model.planningBusy ||
                    title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
            }
        }
        .padding(26)
        .frame(width: 520)
        .interactiveDismissDisabled(model.planningBusy)
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
    @EnvironmentObject private var model: AppModel
    let item: PlanningGoalItem?
    let save: (PlanningGoalDraft) -> Void
    @State private var title: String
    @State private var detail: String
    @State private var priority: Int
    @State private var targetDateEnabled: Bool
    @State private var targetDate: Date

    init(item: PlanningGoalItem?, save: @escaping (PlanningGoalDraft) -> Void) {
        self.item = item
        self.save = save
        _title = State(initialValue: item?.title ?? "")
        _detail = State(initialValue: item?.detail ?? "")
        _priority = State(initialValue: item?.priority ?? 1)
        let initialTarget = item?.targetDate ?? ""
        _targetDateEnabled = State(initialValue: !initialTarget.isEmpty)
        _targetDate = State(initialValue: PlanningDateCodec.date(from: initialTarget) ?? Date())
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack(spacing: 12) {
                Image(systemName: "scope")
                    .font(.system(size: 21, weight: .semibold))
                    .foregroundStyle(ControlDesign.brand)
                    .frame(width: 40, height: 40)
                    .background(ControlDesign.brand.opacity(0.09))
                    .clipShape(RoundedRectangle(cornerRadius: 7))
                VStack(alignment: .leading, spacing: 2) {
                    Text(item == nil ? "新增长期目标" : "编辑长期目标")
                        .font(.title2.weight(.semibold))
                    Text("保留方向，再逐步拆成每天能完成的任务")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            VStack(alignment: .leading, spacing: 7) {
                Text("目标名称").font(.callout.weight(.semibold))
                TextField("例如：完成 RAG-IME 稳定版", text: $title)
                    .planningFieldChrome()
            }

            PlanningTextArea(
                title: "目标说明",
                symbol: "text.alignleft",
                placeholder: "写下完成标准、范围和为什么要做",
                text: $detail,
                minHeight: 104
            )

            VStack(alignment: .leading, spacing: 8) {
                Text("优先级").font(.callout.weight(.semibold))
                Picker("优先级", selection: $priority) {
                    Text("低").tag(0)
                    Text("普通").tag(1)
                    Text("高").tag(2)
                    Text("紧急").tag(3)
                }
                .labelsHidden()
                .pickerStyle(.segmented)
            }

            HStack(spacing: 16) {
                Toggle("设置目标日期", isOn: $targetDateEnabled)
                if targetDateEnabled {
                    DatePicker("目标日期", selection: $targetDate, displayedComponents: .date)
                        .datePickerStyle(.field)
                }
            }

            Divider()
            HStack {
                if model.planningBusy {
                    ProgressView().controlSize(.small)
                    Text("正在保存").font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Button("取消") { dismiss() }
                    .disabled(model.planningBusy)
                Button(item == nil ? "添加目标" : "保存修改") {
                    save(.init(
                        title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                        detail: detail.trimmingCharacters(in: .whitespacesAndNewlines),
                        priority: priority,
                        targetDate: targetDateEnabled ? PlanningDateCodec.string(from: targetDate) : ""
                    ))
                }
                .buttonStyle(.borderedProminent)
                .disabled(
                    model.planningBusy ||
                    title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                )
            }
        }
        .padding(26)
        .frame(width: 520)
        .interactiveDismissDisabled(model.planningBusy)
    }
}

private extension View {
    func planningFieldChrome() -> some View {
        textFieldStyle(.plain)
            .padding(.horizontal, 11)
            .frame(height: 38)
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(
                RoundedRectangle(cornerRadius: 7)
                    .stroke(ControlDesign.hairline, lineWidth: 0.8)
            )
    }
}

private extension PlanningPlanItem {
    var updatedAtMsFallback: String { "\(id)|\(intention)|\(notes)|\(reflection)" }
}
