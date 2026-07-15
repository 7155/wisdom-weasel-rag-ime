import Foundation
import SwiftUI

struct PlanningPage: View {
    @EnvironmentObject private var model: AppModel
    @State private var dailyPlanEditorPresented = false
    @State private var taskEditor: PlanningTaskItem?
    @State private var newTaskPresented = false
    @State private var taskDetail: PlanningTaskItem?
    @State private var goalEditor: PlanningGoalItem?
    @State private var newGoalPresented = false
    @State private var goalDetail: PlanningGoalItem?
    @State private var assistantPresented = false
    @State private var completionReviewPresented = false
    @State private var taskGoalSeed = ""

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()

            if let dashboard = model.planning {
                ScrollView {
                    VStack(alignment: .leading, spacing: 20) {
                        assistantBand(dashboard)
                        completionBanners(dashboard)
                        planningColumns(dashboard)
                    }
                    .padding(.horizontal, ControlDesign.pageHorizontalPadding)
                    .padding(.vertical, 22)
                    .frame(maxWidth: 1280)
                    .frame(maxWidth: .infinity)
                }
            } else {
                EmptyState(symbol: "checklist", text: "正在读取今天的规划")
            }
        }
        .task { await model.loadPlanning() }
        .sheet(isPresented: $dailyPlanEditorPresented) {
            if let plan = model.planning?.plan {
                PlanningDailyPlanEditor(plan: plan) { draft in
                    Task {
                        if await model.saveDailyPlan(
                            intention: draft.intention,
                            notes: draft.notes,
                            reflection: draft.reflection
                        ) {
                            dailyPlanEditorPresented = false
                        }
                    }
                }
            }
        }
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
                    ) {
                        newTaskPresented = false
                    }
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
                    ) {
                        taskEditor = nil
                    }
                }
            }
        }
        .sheet(item: $taskDetail) { item in
            PlanningTaskDetailSheet(
                item: item,
                busy: model.planningBusy,
                action: { action in
                    Task {
                        if await model.performPlanningTaskAction(id: item.id, action: action) {
                            taskDetail = nil
                        }
                    }
                },
                edit: {
                    taskDetail = nil
                    DispatchQueue.main.async { taskEditor = item }
                }
            )
        }
        .sheet(isPresented: $newGoalPresented) {
            PlanningGoalEditor(item: nil) { draft in
                Task {
                    if await model.savePlanningGoal(
                        title: draft.title,
                        detail: draft.detail,
                        priority: draft.priority,
                        targetDate: draft.targetDate
                    ) {
                        newGoalPresented = false
                    }
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
                    ) {
                        goalEditor = nil
                    }
                }
            }
        }
        .sheet(item: $goalDetail) { item in
            PlanningGoalDetailSheet(
                item: item,
                busy: model.planningBusy,
                edit: {
                    goalDetail = nil
                    DispatchQueue.main.async { goalEditor = item }
                },
                makeTask: {
                    goalDetail = nil
                    taskGoalSeed = item.id
                    DispatchQueue.main.async { newTaskPresented = true }
                },
                updateStatus: { status in
                    updateGoal(item, status: status)
                    goalDetail = nil
                }
            )
        }
        .sheet(isPresented: $assistantPresented) {
            PlanningAssistantSheet()
        }
        .sheet(isPresented: $completionReviewPresented) {
            PlanningCompletionReviewSheet()
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

                Button { Task { await model.loadPlanning() } } label: {
                    Image(systemName: "arrow.clockwise")
                        .frame(width: 18, height: 20)
                }
                .help("刷新规划")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(model.planningLoading || model.planningBusy)

            if let summary = model.planning?.summary {
                VStack(alignment: .trailing, spacing: 5) {
                    Text("\(summary.completedTaskCount) / \(summary.taskCount) 已完成")
                        .font(ControlDesign.metadataFont.weight(.semibold).monospacedDigit())
                    ProgressView(value: summary.progress)
                        .tint(summary.taskCount > 0 && summary.openTaskCount == 0 ? .green : ControlDesign.brand)
                        .frame(width: 124)
                }
            }
        }
        .padding(.horizontal, ControlDesign.pageHorizontalPadding)
        .padding(.vertical, 18)
    }

    private func planningColumns(_ dashboard: PlanningDashboardResponse) -> some View {
        ViewThatFits(in: .horizontal) {
            HStack(alignment: .top, spacing: 0) {
                dailyColumn(dashboard)
                    .frame(maxWidth: .infinity, alignment: .topLeading)
                    .padding(.trailing, 28)
                Divider()
                goalColumn(dashboard)
                    .frame(width: 390, alignment: .topLeading)
                    .padding(.leading, 28)
            }
            .frame(minWidth: 980, alignment: .topLeading)

            VStack(alignment: .leading, spacing: 28) {
                dailyColumn(dashboard)
                Divider()
                goalColumn(dashboard)
            }
        }
    }

    private func assistantBand(_ dashboard: PlanningDashboardResponse) -> some View {
        HStack(spacing: 14) {
            RagImeAnimeCompanion(
                state: model.planningBusy ? .thinking : (dashboard.assistant.tone == "celebrate" ? .done : .idle),
                size: 56
            )
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 8) {
                    Text(isShowingToday ? "今日助手" : "当日回顾")
                        .font(ControlDesign.sectionTitleFont)
                    Text(dashboard.date)
                        .font(ControlDesign.metadataFont.monospacedDigit())
                        .foregroundStyle(.secondary)
                }
                Text(dashboard.assistant.message)
                    .font(ControlDesign.bodyFont)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .fixedSize(horizontal: false, vertical: true)
            }
            Spacer(minLength: 14)
            HStack(spacing: 8) {
                PlanningMetricBadge(value: "\(dashboard.summary.openTaskCount)", label: "待办", symbol: "circle.dashed", tint: .orange)
                PlanningMetricBadge(value: "\(dashboard.summary.completedTaskCount)", label: "完成", symbol: "checkmark.circle.fill", tint: .green)
                PlanningMetricBadge(value: "\(dashboard.summary.goalCount)", label: "目标", symbol: "scope", tint: ControlDesign.brand)
            }
        }
        .padding(.horizontal, 18)
        .padding(.vertical, 12)
        .frame(minHeight: 84)
        .background(ControlDesign.brand.opacity(0.07))
        .overlay(alignment: .leading) { Rectangle().fill(ControlDesign.brand).frame(width: 4) }
        .overlay(alignment: .bottom) { Rectangle().fill(ControlDesign.brand.opacity(0.18)).frame(height: 1) }
    }

    @ViewBuilder
    private func completionBanners(_ dashboard: PlanningDashboardResponse) -> some View {
        if let completion = dashboard.recentDetectedCompletion, completion.undoAvailable {
            HStack(spacing: 12) {
                Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                Text(completion.message)
                    .font(ControlDesign.bodyFont.weight(.medium))
                    .lineLimit(2)
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
            HStack(spacing: 12) {
                Image(systemName: "checkmark.bubble.fill").foregroundStyle(.orange)
                VStack(alignment: .leading, spacing: 2) {
                    Text("识别到可能完成的任务")
                        .font(ControlDesign.bodyFont.weight(.semibold))
                    Text("\(dashboard.pendingCompletionSuggestions.count) 条待确认")
                        .font(ControlDesign.metadataFont)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("查看并处理") { completionReviewPresented = true }
                    .buttonStyle(.bordered)
                    .disabled(model.planningBusy)
            }
            .padding(.horizontal, 16)
            .frame(minHeight: 56)
            .background(Color.orange.opacity(0.07))
            .overlay(alignment: .leading) { Rectangle().fill(Color.orange).frame(width: 3) }
        }
    }

    private func dailyColumn(_ dashboard: PlanningDashboardResponse) -> some View {
        VStack(alignment: .leading, spacing: 20) {
            HStack {
                PlanningSectionTitle(
                    title: "今日计划",
                    subtitle: dashboard.plan.intention.isEmpty ? "尚未设置今日重点" : "今日重点已记录",
                    symbol: "sun.max.fill",
                    tint: .orange
                )
                Spacer()
                Button {
                    dailyPlanEditorPresented = true
                } label: {
                    Label("编辑计划", systemImage: "square.and.pencil")
                }
                .buttonStyle(.bordered)
                .disabled(model.planningBusy)
            }

            PlanningPlanSummary(plan: dashboard.plan) {
                dailyPlanEditorPresented = true
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
                .buttonStyle(.borderedProminent)
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
                ControlSurface {
                    VStack(spacing: 0) {
                        ForEach(dashboard.tasks) { task in
                            PlanningTaskRow(
                                item: task,
                                busy: model.planningBusy,
                                toggle: {
                                    Task {
                                        _ = await model.performPlanningTaskAction(
                                            id: task.id,
                                            action: task.status == "done" ? "reopen" : "complete"
                                        )
                                    }
                                },
                                detail: { taskDetail = task },
                                edit: { taskEditor = task },
                                start: {
                                    Task { _ = await model.performPlanningTaskAction(id: task.id, action: "start") }
                                },
                                cancel: {
                                    Task { _ = await model.performPlanningTaskAction(id: task.id, action: "cancel") }
                                }
                            )
                            if task.id != dashboard.tasks.last?.id {
                                Divider().padding(.leading, 58)
                            }
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
                ControlSurface {
                    VStack(spacing: 0) {
                        ForEach(dashboard.goals) { goal in
                            PlanningGoalRow(
                                item: goal,
                                busy: model.planningBusy,
                                detail: { goalDetail = goal },
                                edit: { goalEditor = goal },
                                makeTask: {
                                    taskGoalSeed = goal.id
                                    newTaskPresented = true
                                },
                                complete: { updateGoal(goal, status: "completed") },
                                archive: { updateGoal(goal, status: "archived") }
                            )
                            if goal.id != dashboard.goals.last?.id {
                                Divider().padding(.leading, 52)
                            }
                        }
                    }
                }
            }

            Divider().padding(.vertical, 4)
            assistantLauncher(dashboard)
        }
    }

    private func assistantLauncher(_ dashboard: PlanningDashboardResponse) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            PlanningSectionTitle(
                title: "规划助手",
                subtitle: dashboard.conversation.isEmpty ? "尚无当日对话" : "\(dashboard.conversation.count) 条当日消息",
                symbol: "bubble.left.and.bubble.right.fill",
                tint: .blue
            )
            ControlSurface {
                VStack(alignment: .leading, spacing: 12) {
                    Text(dashboard.conversation.last?.content ?? dashboard.assistant.message)
                        .font(ControlDesign.bodyFont)
                        .foregroundStyle(.secondary)
                        .lineLimit(3)
                        .fixedSize(horizontal: false, vertical: true)
                    HStack {
                        Spacer()
                        Button {
                            assistantPresented = true
                        } label: {
                            Label("打开规划助手", systemImage: "bubble.left.and.text.bubble.right")
                        }
                        .buttonStyle(.borderedProminent)
                    }
                }
                .padding(14)
            }
        }
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

private struct PlanningPlanSummary: View {
    let plan: PlanningPlanItem
    let edit: () -> Void

    var body: some View {
        ControlSurface {
            VStack(spacing: 0) {
                HStack(alignment: .top, spacing: 12) {
                    Image(systemName: "target")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(ControlDesign.brand)
                        .frame(width: 32, height: 32)
                    VStack(alignment: .leading, spacing: 3) {
                        Text("最重要的一件事")
                            .font(ControlDesign.metadataFont.weight(.semibold))
                            .foregroundStyle(.secondary)
                        Text(plan.intention.isEmpty ? "未设置" : plan.intention)
                            .font(ControlDesign.bodyFont.weight(.semibold))
                            .lineLimit(2)
                    }
                    Spacer()
                    Button(action: edit) {
                        Image(systemName: "pencil")
                            .frame(width: ControlDesign.iconButtonSize, height: ControlDesign.iconButtonSize)
                    }
                    .buttonStyle(.plain)
                    .help("编辑今日计划")
                }
                .padding(14)

                Divider().padding(.leading, 58)
                PlanningPlanExcerptRow(label: "日间笔记", value: plan.notes, symbol: "note.text")
                Divider().padding(.leading, 58)
                PlanningPlanExcerptRow(label: "复盘", value: plan.reflection, symbol: "arrow.triangle.2.circlepath")
            }
        }
    }
}

private struct PlanningPlanExcerptRow: View {
    let label: String
    let value: String
    let symbol: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .foregroundStyle(.secondary)
                .frame(width: 32)
            Text(label)
                .font(ControlDesign.metadataFont.weight(.medium))
                .foregroundStyle(.secondary)
                .frame(width: 72, alignment: .leading)
            Text(value.isEmpty ? "未填写" : value)
                .font(ControlDesign.detailFont)
                .foregroundStyle(value.isEmpty ? .tertiary : .secondary)
                .lineLimit(1)
            Spacer()
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 42)
    }
}

private struct PlanningTaskRow: View {
    let item: PlanningTaskItem
    let busy: Bool
    let toggle: () -> Void
    let detail: () -> Void
    let edit: () -> Void
    let start: () -> Void
    let cancel: () -> Void

    var body: some View {
        HStack(spacing: 12) {
            Button(action: toggle) {
                Image(systemName: statusSymbol)
                    .font(.system(size: 18, weight: .medium))
                    .foregroundStyle(statusColor)
                    .frame(width: ControlDesign.iconButtonSize, height: ControlDesign.iconButtonSize)
            }
            .buttonStyle(.plain)
            .help(item.status == "done" ? "重新打开" : "标记完成")
            .disabled(busy || item.status == "cancelled")

            VStack(alignment: .leading, spacing: 4) {
                Text(item.title)
                    .font(ControlDesign.bodyFont.weight(.semibold))
                    .strikethrough(item.status == "done")
                    .foregroundStyle(item.status == "cancelled" ? .secondary : .primary)
                    .lineLimit(1)
                HStack(spacing: 8) {
                    PlanningPriorityLabel(priority: item.priority)
                    if !item.detail.isEmpty {
                        Text(item.detail)
                            .font(ControlDesign.metadataFont)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    if let due = item.dueAtMs {
                        Label(planningDateLabel(due), systemImage: "calendar")
                            .font(ControlDesign.metadataFont)
                            .foregroundStyle(.secondary)
                    }
                    PlanningStatusText(status: item.status)
                }
            }
            Spacer(minLength: 8)

            Button(action: detail) {
                Image(systemName: "doc.text.magnifyingglass")
                    .frame(width: ControlDesign.iconButtonSize, height: ControlDesign.iconButtonSize)
            }
            .buttonStyle(.plain)
            .help("查看任务详情")

            Menu {
                if item.status == "todo" { Button("开始", action: start) }
                Button("查看详情", action: detail)
                Button("编辑", action: edit)
                Button(item.status == "done" ? "重新打开" : "完成", action: toggle)
                if item.status != "cancelled" && item.status != "done" {
                    Divider()
                    Button("取消任务", action: cancel)
                }
            } label: {
                Image(systemName: "ellipsis")
                    .frame(width: ControlDesign.iconButtonSize, height: ControlDesign.iconButtonSize)
            }
            .menuStyle(.borderlessButton)
            .frame(width: ControlDesign.iconButtonSize)
            .disabled(busy)
        }
        .padding(.horizontal, 14)
        .frame(minHeight: 66)
        .contentShape(Rectangle())
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
    let detail: () -> Void
    let edit: () -> Void
    let makeTask: () -> Void
    let complete: () -> Void
    let archive: () -> Void

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "scope")
                .font(.system(size: 15, weight: .semibold))
                .foregroundStyle(ControlDesign.brand)
                .frame(width: 32, height: 32)
                .background(ControlDesign.brand.opacity(0.09))
                .clipShape(RoundedRectangle(cornerRadius: 6))

            VStack(alignment: .leading, spacing: 4) {
                Text(item.title)
                    .font(ControlDesign.bodyFont.weight(.semibold))
                    .lineLimit(1)
                HStack(spacing: 7) {
                    PlanningPriorityLabel(priority: item.priority)
                    if !item.targetDate.isEmpty {
                        Label(item.targetDate, systemImage: "calendar")
                            .font(ControlDesign.metadataFont)
                            .foregroundStyle(.secondary)
                    } else if !item.detail.isEmpty {
                        Text(item.detail)
                            .font(ControlDesign.metadataFont)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                }
            }
            Spacer(minLength: 6)

            Button(action: makeTask) {
                Label("拆成任务", systemImage: "arrow.turn.down.right")
            }
            .buttonStyle(.bordered)
            .controlSize(.small)
            .disabled(busy)

            Button(action: detail) {
                Image(systemName: "doc.text.magnifyingglass")
                    .frame(width: ControlDesign.iconButtonSize, height: ControlDesign.iconButtonSize)
            }
            .buttonStyle(.plain)
            .help("查看目标详情")

            Menu {
                Button("查看详情", action: detail)
                Button("编辑", action: edit)
                Button("标记完成", action: complete)
                Button("归档", action: archive)
            } label: {
                Image(systemName: "ellipsis")
                    .frame(width: ControlDesign.iconButtonSize, height: ControlDesign.iconButtonSize)
            }
            .menuStyle(.borderlessButton)
            .frame(width: ControlDesign.iconButtonSize)
            .disabled(busy)
        }
        .padding(.horizontal, 12)
        .frame(minHeight: 66)
        .contentShape(Rectangle())
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
                .frame(width: 32, height: 32)
                .background(tint.opacity(0.09))
                .clipShape(RoundedRectangle(cornerRadius: 6))
            VStack(alignment: .leading, spacing: 2) {
                Text(title).font(ControlDesign.sectionTitleFont)
                Text(subtitle)
                    .font(ControlDesign.metadataFont)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
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
            Image(systemName: symbol).foregroundStyle(tint)
            VStack(alignment: .leading, spacing: 0) {
                Text(value)
                    .font(.system(size: 16, weight: .semibold, design: .rounded))
                    .monospacedDigit()
                Text(label)
                    .font(ControlDesign.metadataFont)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 10)
        .frame(height: 44)
        .background(Color(nsColor: .windowBackgroundColor).opacity(0.72))
        .overlay(RoundedRectangle(cornerRadius: 7).stroke(tint.opacity(0.18), lineWidth: 0.7))
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
                .font(ControlDesign.bodyFont.weight(.semibold))
            ZStack(alignment: .topLeading) {
                if text.isEmpty {
                    Text(placeholder)
                        .font(ControlDesign.bodyFont)
                        .foregroundStyle(.tertiary)
                        .padding(.horizontal, 13)
                        .padding(.vertical, 12)
                        .allowsHitTesting(false)
                }
                TextEditor(text: $text)
                    .font(ControlDesign.bodyFont)
                    .scrollContentBackground(.hidden)
                    .padding(7)
                    .frame(minHeight: minHeight)
            }
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.8))
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
                    Text(title).font(ControlDesign.bodyFont.weight(.semibold))
                    Text(detail).font(ControlDesign.metadataFont).foregroundStyle(.secondary)
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
                .stroke(ControlDesign.brand.opacity(0.28), style: StrokeStyle(lineWidth: 0.8, dash: [5, 4]))
        )
    }
}

private struct PlanningStatusText: View {
    let status: String

    var body: some View {
        Text(label)
            .font(ControlDesign.metadataFont.weight(.medium))
            .foregroundStyle(color)
    }

    private var label: String {
        switch status {
        case "in_progress": return "进行中"
        case "done": return "已完成"
        case "cancelled": return "已取消"
        default: return "待开始"
        }
    }

    private var color: Color {
        switch status {
        case "in_progress": return ControlDesign.brand
        case "done": return .green
        case "cancelled": return .secondary
        default: return .secondary
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

    static func string(from date: Date) -> String { formatter.string(from: date) }
    static func date(from value: String) -> Date? { formatter.date(from: value) }
}

private struct PlanningPriorityLabel: View {
    let priority: Int

    var body: some View {
        Text(label)
            .font(ControlDesign.metadataFont.weight(.semibold))
            .foregroundStyle(color)
            .padding(.horizontal, 7)
            .frame(height: 21)
            .background(color.opacity(0.09))
            .clipShape(RoundedRectangle(cornerRadius: 4))
    }

    private var label: String { ["低", "普通", "高", "紧急"][max(0, min(3, priority))] }
    private var color: Color { priority >= 3 ? .red : (priority == 2 ? .orange : .secondary) }
}

private struct PlanningDailyPlanDraft {
    let intention: String
    let notes: String
    let reflection: String
}

private struct PlanningDailyPlanEditor: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var model: AppModel
    let plan: PlanningPlanItem
    let save: (PlanningDailyPlanDraft) -> Void
    @State private var intention: String
    @State private var notes: String
    @State private var reflection: String

    init(plan: PlanningPlanItem, save: @escaping (PlanningDailyPlanDraft) -> Void) {
        self.plan = plan
        self.save = save
        _intention = State(initialValue: plan.intention)
        _notes = State(initialValue: plan.notes)
        _reflection = State(initialValue: plan.reflection)
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 20) {
            PlanningSheetHeader(title: "编辑今日计划", subtitle: plan.date, symbol: "sun.max.fill", tint: .orange)

            VStack(alignment: .leading, spacing: 7) {
                Text("最重要的一件事").font(ControlDesign.bodyFont.weight(.semibold))
                TextField("今天最值得完成的结果", text: $intention)
                    .planningFieldChrome()
            }

            HStack(alignment: .top, spacing: 14) {
                PlanningTextArea(
                    title: "日间笔记",
                    symbol: "note.text",
                    placeholder: "记录过程、阻塞和临时想法",
                    text: $notes,
                    minHeight: 150
                )
                PlanningTextArea(
                    title: "复盘",
                    symbol: "arrow.triangle.2.circlepath",
                    placeholder: "完成了什么，下一步是什么",
                    text: $reflection,
                    minHeight: 150
                )
            }

            Divider()
            HStack {
                if model.planningBusy {
                    ProgressView().controlSize(.small)
                    Text("正在保存").font(ControlDesign.metadataFont).foregroundStyle(.secondary)
                }
                Spacer()
                Button("取消") { dismiss() }.disabled(model.planningBusy)
                Button {
                    save(.init(
                        intention: intention.trimmingCharacters(in: .whitespacesAndNewlines),
                        notes: notes.trimmingCharacters(in: .whitespacesAndNewlines),
                        reflection: reflection.trimmingCharacters(in: .whitespacesAndNewlines)
                    ))
                } label: {
                    Label("保存计划", systemImage: "square.and.arrow.down")
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.planningBusy || !hasChanges)
            }
        }
        .padding(26)
        .frame(width: 650)
        .interactiveDismissDisabled(model.planningBusy)
    }

    private var hasChanges: Bool {
        intention != plan.intention || notes != plan.notes || reflection != plan.reflection
    }
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
            PlanningSheetHeader(
                title: item == nil ? "新增任务" : "编辑任务",
                subtitle: "明确下一步动作",
                symbol: item == nil ? "plus.square.fill" : "square.and.pencil",
                tint: .indigo
            )

            VStack(alignment: .leading, spacing: 7) {
                Text("任务名称").font(ControlDesign.bodyFont.weight(.semibold))
                TextField("例如：完成输入法候选面板优化", text: $title)
                    .planningFieldChrome()
            }

            PlanningTextArea(
                title: "任务说明",
                symbol: "text.alignleft",
                placeholder: "补充验收标准、上下文或阻塞项",
                text: $detail,
                minHeight: 110
            )

            PlanningPriorityPicker(priority: $priority)

            ControlLabelValueRow("截止时间") {
                HStack(spacing: 10) {
                    Toggle("", isOn: $dueEnabled).labelsHidden()
                    if dueEnabled {
                        DatePicker("截止", selection: $dueDate).labelsHidden().datePickerStyle(.field)
                    }
                }
            }

            if !goals.isEmpty {
                ControlLabelValueRow("关联目标") {
                    Picker("关联目标", selection: $goalId) {
                        Text("不关联").tag("")
                        ForEach(goals) { Text($0.title).tag($0.id) }
                    }
                    .labelsHidden()
                    .pickerStyle(.menu)
                }
            }

            Divider()
            HStack {
                if model.planningBusy {
                    ProgressView().controlSize(.small)
                    Text("正在保存").font(ControlDesign.metadataFont).foregroundStyle(.secondary)
                }
                Spacer()
                Button("取消") { dismiss() }.disabled(model.planningBusy)
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
                .disabled(model.planningBusy || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(26)
        .frame(width: 560)
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
            PlanningSheetHeader(
                title: item == nil ? "新增长期目标" : "编辑长期目标",
                subtitle: "保留长期方向",
                symbol: "scope",
                tint: ControlDesign.brand
            )

            VStack(alignment: .leading, spacing: 7) {
                Text("目标名称").font(ControlDesign.bodyFont.weight(.semibold))
                TextField("例如：完成 RAG-IME 稳定版", text: $title)
                    .planningFieldChrome()
            }

            PlanningTextArea(
                title: "目标说明",
                symbol: "text.alignleft",
                placeholder: "写下完成标准和范围",
                text: $detail,
                minHeight: 120
            )

            PlanningPriorityPicker(priority: $priority)

            ControlLabelValueRow("目标日期") {
                HStack(spacing: 10) {
                    Toggle("", isOn: $targetDateEnabled).labelsHidden()
                    if targetDateEnabled {
                        DatePicker("目标日期", selection: $targetDate, displayedComponents: .date)
                            .labelsHidden()
                            .datePickerStyle(.field)
                    }
                }
            }

            Divider()
            HStack {
                if model.planningBusy {
                    ProgressView().controlSize(.small)
                    Text("正在保存").font(ControlDesign.metadataFont).foregroundStyle(.secondary)
                }
                Spacer()
                Button("取消") { dismiss() }.disabled(model.planningBusy)
                Button(item == nil ? "添加目标" : "保存修改") {
                    save(.init(
                        title: title.trimmingCharacters(in: .whitespacesAndNewlines),
                        detail: detail.trimmingCharacters(in: .whitespacesAndNewlines),
                        priority: priority,
                        targetDate: targetDateEnabled ? PlanningDateCodec.string(from: targetDate) : ""
                    ))
                }
                .buttonStyle(.borderedProminent)
                .disabled(model.planningBusy || title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
        }
        .padding(26)
        .frame(width: 560)
        .interactiveDismissDisabled(model.planningBusy)
    }
}

private struct PlanningPriorityPicker: View {
    @Binding var priority: Int

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("优先级").font(ControlDesign.bodyFont.weight(.semibold))
            Picker("优先级", selection: $priority) {
                Text("低").tag(0)
                Text("普通").tag(1)
                Text("高").tag(2)
                Text("紧急").tag(3)
            }
            .labelsHidden()
            .pickerStyle(.segmented)
        }
    }
}

private struct PlanningTaskDetailSheet: View {
    @Environment(\.dismiss) private var dismiss
    let item: PlanningTaskItem
    let busy: Bool
    let action: (String) -> Void
    let edit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PlanningSheetHeader(title: item.title, subtitle: "任务详情", symbol: "checklist", tint: .indigo)

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    detailBlock(title: "任务说明", text: item.detail)
                    ControlSurface {
                        VStack(spacing: 0) {
                            ControlDetailRow(label: "状态", value: planningStatusLabel(item.status))
                            Divider()
                            ControlDetailRow(label: "优先级", value: planningPriorityLabel(item.priority))
                            Divider()
                            ControlDetailRow(label: "计划日期", value: item.date)
                            Divider()
                            ControlDetailRow(label: "截止时间", value: item.dueAtMs.map(planningDateLabel) ?? "")
                            Divider()
                            ControlDetailRow(label: "所属项目", value: item.project)
                            Divider()
                            ControlDetailRow(label: "来源", value: item.source)
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 6)
                    }
                }
            }

            Divider()
            HStack(spacing: 10) {
                if item.status == "todo" {
                    Button("开始", systemImage: "play.fill") { action("start") }
                }
                Button(item.status == "done" ? "重新打开" : "标记完成", systemImage: "checkmark.circle") {
                    action(item.status == "done" ? "reopen" : "complete")
                }
                .buttonStyle(.borderedProminent)
                if item.status != "done" && item.status != "cancelled" {
                    Button("取消任务", systemImage: "xmark.circle") { action("cancel") }
                }
                Spacer()
                Button("编辑", systemImage: "pencil", action: edit)
                Button("关闭") { dismiss() }
            }
            .disabled(busy)
        }
        .padding(24)
        .frame(width: 600, height: 540)
        .interactiveDismissDisabled(busy)
    }
}

private struct PlanningGoalDetailSheet: View {
    @Environment(\.dismiss) private var dismiss
    let item: PlanningGoalItem
    let busy: Bool
    let edit: () -> Void
    let makeTask: () -> Void
    let updateStatus: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PlanningSheetHeader(title: item.title, subtitle: "目标详情", symbol: "scope", tint: ControlDesign.brand)

            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    detailBlock(title: "目标说明", text: item.detail)
                    ControlSurface {
                        VStack(spacing: 0) {
                            ControlDetailRow(label: "状态", value: planningGoalStatusLabel(item.status))
                            Divider()
                            ControlDetailRow(label: "优先级", value: planningPriorityLabel(item.priority))
                            Divider()
                            ControlDetailRow(label: "目标日期", value: item.targetDate)
                            Divider()
                            ControlDetailRow(label: "时间跨度", value: item.horizon)
                            Divider()
                            ControlDetailRow(label: "所属项目", value: item.project)
                        }
                        .padding(.horizontal, 14)
                        .padding(.vertical, 6)
                    }
                }
            }

            Divider()
            HStack(spacing: 10) {
                Button {
                    makeTask()
                } label: {
                    Label("拆成任务", systemImage: "arrow.turn.down.right")
                }
                .buttonStyle(.borderedProminent)
                Button("标记完成", systemImage: "checkmark.circle") { updateStatus("completed") }
                Button("归档", systemImage: "archivebox") { updateStatus("archived") }
                Spacer()
                Button("编辑", systemImage: "pencil", action: edit)
                Button("关闭") { dismiss() }
            }
            .disabled(busy)
        }
        .padding(24)
        .frame(width: 600, height: 520)
        .interactiveDismissDisabled(busy)
    }
}

private struct PlanningAssistantSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            PlanningSheetHeader(
                title: "规划助手",
                subtitle: model.planning?.date ?? "",
                symbol: "bubble.left.and.bubble.right.fill",
                tint: .blue
            )

            if let dashboard = model.planning {
                ScrollView {
                    LazyVStack(spacing: 10) {
                        if dashboard.conversation.isEmpty {
                            EmptyState(symbol: "bubble.left", text: "还没有当日对话")
                                .frame(height: 220)
                        } else {
                            ForEach(dashboard.conversation) { message in
                                PlanningConversationBubble(message: message)
                            }
                        }
                    }
                    .padding(.vertical, 4)
                }
                .frame(maxHeight: .infinity)

                HStack(spacing: 8) {
                    quickPrompt("梳理今天的重点", symbol: "wand.and.stars")
                    quickPrompt("检查未完成任务", symbol: "checklist")
                    quickPrompt("从目标拆一个任务", symbol: "arrow.turn.down.right")
                    Spacer()
                }

                HStack(spacing: 10) {
                    TextField("询问今天的任务、进度或长期目标", text: $model.planningAssistantDraft)
                        .textFieldStyle(.plain)
                        .font(ControlDesign.bodyFont)
                        .padding(.horizontal, 12)
                        .frame(height: 40)
                        .background(Color(nsColor: .textBackgroundColor))
                        .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.8))
                        .onSubmit { Task { await model.sendPlanningAssistantMessage() } }
                    Button { Task { await model.sendPlanningAssistantMessage() } } label: {
                        Label("发送", systemImage: "arrow.up").frame(minWidth: 62)
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(
                        model.planningBusy ||
                        model.planningAssistantDraft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                    )
                }
            }

            HStack {
                if model.planningBusy {
                    ProgressView().controlSize(.small)
                    Text("正在整理").font(ControlDesign.metadataFont).foregroundStyle(.secondary)
                }
                Spacer()
                Button("关闭") { dismiss() }
            }
        }
        .padding(24)
        .frame(width: 700, height: 650)
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
}

private struct PlanningCompletionReviewSheet: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var model: AppModel

    var body: some View {
        VStack(alignment: .leading, spacing: 18) {
            PlanningSheetHeader(
                title: "完成确认",
                subtitle: "识别到的任务状态变更",
                symbol: "checkmark.bubble.fill",
                tint: .orange
            )

            ScrollView {
                VStack(spacing: 12) {
                    ForEach(model.planning?.pendingCompletionSuggestions ?? []) { suggestion in
                        ControlSurface {
                            VStack(alignment: .leading, spacing: 12) {
                                Text("选择实际完成的任务")
                                    .font(ControlDesign.bodyFont.weight(.semibold))
                                ForEach(suggestion.candidateTasks) { task in
                                    Button {
                                        Task {
                                            await model.resolvePlanningSuggestion(id: suggestion.id, taskId: task.id)
                                            closeWhenFinished()
                                        }
                                    } label: {
                                        HStack {
                                            Text(task.title)
                                                .font(ControlDesign.bodyFont)
                                                .frame(maxWidth: .infinity, alignment: .leading)
                                            Image(systemName: "checkmark.circle")
                                        }
                                        .contentShape(Rectangle())
                                    }
                                    .buttonStyle(.plain)
                                    .disabled(model.planningBusy)
                                }
                                Divider()
                                HStack {
                                    Spacer()
                                    Button("忽略") {
                                        Task {
                                            await model.resolvePlanningSuggestion(id: suggestion.id, dismiss: true)
                                            closeWhenFinished()
                                        }
                                    }
                                    .disabled(model.planningBusy)
                                }
                            }
                            .padding(14)
                        }
                    }
                }
            }

            Divider()
            HStack {
                if model.planningBusy { ProgressView().controlSize(.small) }
                Spacer()
                Button("关闭") { dismiss() }
            }
        }
        .padding(24)
        .frame(width: 620, height: 520)
    }

    private func closeWhenFinished() {
        if model.planning?.pendingCompletionSuggestions.isEmpty != false {
            dismiss()
        }
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
                    .frame(width: 28, height: 28)
                    .background(ControlDesign.brand.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 6))
            }
            Text(message.content)
                .font(ControlDesign.bodyFont)
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

private struct PlanningSheetHeader: View {
    let title: String
    let subtitle: String
    let symbol: String
    let tint: Color

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: symbol)
                .font(.system(size: 20, weight: .semibold))
                .foregroundStyle(tint)
                .frame(width: 40, height: 40)
                .background(tint.opacity(0.09))
                .clipShape(RoundedRectangle(cornerRadius: 7))
            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.system(size: 21, weight: .semibold))
                    .lineLimit(2)
                Text(subtitle)
                    .font(ControlDesign.metadataFont)
                    .foregroundStyle(.secondary)
            }
        }
    }
}

@ViewBuilder
private func detailBlock(title: String, text: String) -> some View {
    VStack(alignment: .leading, spacing: 8) {
        Text(title).font(ControlDesign.bodyFont.weight(.semibold))
        Text(text.isEmpty ? "未填写" : text)
            .font(ControlDesign.bodyFont)
            .foregroundStyle(text.isEmpty ? .secondary : .primary)
            .textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.8))
    }
}

private extension View {
    func planningFieldChrome() -> some View {
        textFieldStyle(.plain)
            .font(ControlDesign.bodyFont)
            .padding(.horizontal, 11)
            .frame(height: 40)
            .background(Color(nsColor: .textBackgroundColor))
            .clipShape(RoundedRectangle(cornerRadius: 7))
            .overlay(RoundedRectangle(cornerRadius: 7).stroke(ControlDesign.hairline, lineWidth: 0.8))
    }
}

private func planningDateLabel(_ milliseconds: Int) -> String {
    DateFormatter.localizedString(
        from: Date(timeIntervalSince1970: Double(milliseconds) / 1000),
        dateStyle: .medium,
        timeStyle: .short
    )
}

private func planningStatusLabel(_ status: String) -> String {
    switch status {
    case "in_progress": return "进行中"
    case "done": return "已完成"
    case "cancelled": return "已取消"
    default: return "待开始"
    }
}

private func planningGoalStatusLabel(_ status: String) -> String {
    switch status {
    case "completed": return "已完成"
    case "archived": return "已归档"
    default: return "进行中"
    }
}

private func planningPriorityLabel(_ priority: Int) -> String {
    ["低", "普通", "高", "紧急"][max(0, min(3, priority))]
}
