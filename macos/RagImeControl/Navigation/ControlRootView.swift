import Combine
import Foundation
import SwiftUI

struct ControlRootView: View {
    let model: AppModel

    @EnvironmentObject private var navigation: ControlNavigationModel
    @EnvironmentObject private var agentWorkspace: AgentWorkspaceStore
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        NavigationSplitView {
            List(selection: $navigation.destination) {
                Section {
                    HStack(spacing: 11) {
                        RagImeAnimeCompanion(
                            state: .idle,
                            size: 48,
                            animatesAmbientMotion: false
                        )
                        VStack(alignment: .leading, spacing: 2) {
                            Text("智鼬").font(.headline)
                            Text("个人输入工作台").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 9)
                    .listRowBackground(Color.clear)
                }
                Section("工作台") {
                    destinationRow(.overview)
                    destinationRow(.inputMethod)
                    destinationRow(.assistant)
                }
                Section("输入体验") {
                    destinationRow(.voiceInput)
                }
                Section("个人节奏") {
                    destinationRow(.planning)
                    destinationRow(.memory)
                }
                Section("知识与系统") {
                    destinationRow(.ragAndModels)
                    destinationRow(.history)
                    destinationRow(.diagnostics)
                    destinationRow(.configuration)
                }
            }
            .navigationSplitViewColumnWidth(min: 220, ideal: 232, max: 252)
            .listStyle(.sidebar)
            .safeAreaInset(edge: .bottom) {
                ControlConnectionFooter(model: model)
            }
        } detail: {
            VStack(spacing: 0) {
                ControlNoticeHost(model: model)
                ZStack {
                    ControlDetailRouter(destination: navigation.destination)
                        .id(navigation.destination)
                        .transition(
                            .opacity.combined(
                                with: .offset(x: reduceMotion ? 0 : RagImeMotion.Distance.small)
                            )
                        )
                }
                .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: navigation.destination)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(nsColor: .windowBackgroundColor))
            }
        }
        .navigationSplitViewStyle(.prominentDetail)
        .onAppear {
            model.activateDestination(navigation.destination)
        }
        .onChange(of: navigation.destination) { target in
            model.activateDestination(target)
        }
        .onReceive(
            DistributedNotificationCenter.default().publisher(
                for: Notification.Name("com.rag-ime.control.open-agent")
            )
        ) { notification in
            navigation.destination = .assistant
            let sessionId = notification.userInfo?["sessionId"] as? String ?? ""
            Task { await agentWorkspace.focusExternalSession(sessionId) }
        }
    }

    private func destinationRow(_ item: ControlDestination) -> some View {
        Label(item.title, systemImage: item.symbol)
            .font(.system(size: 14, weight: .medium))
            .padding(.vertical, 5)
            .tag(item)
    }
}

private struct ControlDetailRouter: View {
    let destination: ControlDestination

    @ViewBuilder
    var body: some View {
        switch destination {
        case .overview: OverviewPage()
        case .inputMethod: InputMethodPage()
        case .voiceInput: VoiceInputPage()
        case .planning: PlanningPage()
        case .assistant: AgentCenterPage()
        case .memory: MemoryPage()
        case .ragAndModels: RagAndModelsPage()
        case .history: HistoryPage()
        case .diagnostics: DiagnosticsPage()
        case .configuration: ConfigurationPage()
        }
    }
}

private struct ControlNoticeHost: View {
    @ObservedObject var model: AppModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    @ViewBuilder
    var body: some View {
        if model.showingError {
            ControlNoticeBanner(
                kind: .error,
                title: "操作没有完成",
                detail: model.errorMessage,
                onDismiss: {
                    model.showingError = false
                    model.errorMessage = ""
                }
            )
            .transition(.move(edge: .top).combined(with: .opacity))
            .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: model.showingError)
        } else if model.showingRuntimeActionReport {
            ControlNoticeBanner(
                kind: .report,
                title: "运行组件已更新",
                detail: model.lastRuntimeActionReport,
                onDismiss: { model.showingRuntimeActionReport = false }
            )
            .transition(.move(edge: .top).combined(with: .opacity))
            .animation(RagImeMotion.transition(reduceMotion: reduceMotion), value: model.showingRuntimeActionReport)
        }
    }
}

private struct ControlConnectionFooter: View {
    @ObservedObject var model: AppModel

    var body: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(model.connected ? Color.green : Color.gray)
                .frame(width: 7, height: 7)
            Text(model.connected ? "本地服务已连接" : "等待本地服务")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 13)
    }
}
