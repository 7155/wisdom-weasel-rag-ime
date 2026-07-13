import SwiftUI

struct ControlRootView: View {
    @EnvironmentObject private var model: AppModel
    @Environment(\.accessibilityReduceMotion) private var reduceMotion

    var body: some View {
        NavigationSplitView {
            List(selection: $model.destination) {
                Section {
                    HStack(spacing: 11) {
                        RagImeAnimeCompanion(state: .idle, size: 48)
                        VStack(alignment: .leading, spacing: 2) {
                            Text("RAG-IME").font(.headline)
                            Text("个人输入工作台").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 9)
                    .listRowBackground(Color.clear)
                }
                Section("输入体验") {
                    destinationRow(.overview)
                    destinationRow(.inputMethod)
                    destinationRow(.voiceInput)
                }
                Section("知识与系统") {
                    destinationRow(.memory)
                    destinationRow(.ragAndModels)
                    destinationRow(.history)
                    destinationRow(.diagnostics)
                }
            }
            .navigationSplitViewColumnWidth(min: 220, ideal: 232, max: 252)
            .listStyle(.sidebar)
            .safeAreaInset(edge: .bottom) {
                connectionFooter
            }
        } detail: {
            VStack(spacing: 0) {
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
                }
                if model.showingRuntimeActionReport {
                    ControlNoticeBanner(
                        kind: .report,
                        title: "运行组件已更新",
                        detail: model.lastRuntimeActionReport,
                        onDismiss: { model.showingRuntimeActionReport = false }
                    )
                    .transition(.move(edge: .top).combined(with: .opacity))
                }
                Group {
                    switch model.destination {
                    case .overview: OverviewPage()
                    case .inputMethod: InputMethodPage()
                    case .voiceInput: VoiceInputPage()
                    case .memory: MemoryPage()
                    case .ragAndModels: RagAndModelsPage()
                    case .history: HistoryPage()
                    case .diagnostics: DiagnosticsPage()
                    }
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .background(Color(nsColor: .windowBackgroundColor))
            }
            .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: model.showingError)
            .animation(reduceMotion ? nil : .easeOut(duration: 0.18), value: model.showingRuntimeActionReport)
        }
        .navigationSplitViewStyle(.prominentDetail)
    }

    private func destinationRow(_ item: ControlDestination) -> some View {
        Label(item.title, systemImage: item.symbol)
            .font(.system(size: 14, weight: .medium))
            .padding(.vertical, 5)
            .tag(item)
    }

    private var connectionFooter: some View {
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
