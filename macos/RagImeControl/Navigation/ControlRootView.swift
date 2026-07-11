import SwiftUI

struct ControlRootView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        NavigationSplitView {
            List(ControlDestination.allCases, selection: $model.destination) { item in
                Label(item.title, systemImage: item.symbol).tag(item)
            }
            .navigationSplitViewColumnWidth(min: 184, ideal: 188, max: 196)
            .listStyle(.sidebar)
            .safeAreaInset(edge: .bottom) {
                connectionFooter
            }
        } detail: {
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
            .background(Color(nsColor: .textBackgroundColor))
        }
        .navigationSplitViewStyle(.balanced)
        .alert("操作失败", isPresented: $model.showingError) {
            Button("好") { model.errorMessage = "" }
        } message: {
            Text(model.errorMessage)
        }
        .alert("外部监督器已完成", isPresented: $model.showingRuntimeActionReport) {
            Button("好") { }
        } message: {
            Text(model.lastRuntimeActionReport)
        }
    }

    private var connectionFooter: some View {
        HStack(spacing: 7) {
            Circle()
                .fill(model.connected ? Color.green : Color.gray)
                .frame(width: 7, height: 7)
            Text(model.connected ? "本地服务已连接" : "等待本地服务")
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer()
        }
        .padding(12)
    }
}
