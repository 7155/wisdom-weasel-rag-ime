import SwiftUI

struct ControlRootView: View {
    @EnvironmentObject private var model: AppModel

    var body: some View {
        NavigationSplitView {
            List(selection: $model.destination) {
                Section {
                    VStack(alignment: .leading, spacing: 4) {
                        HStack(spacing: 10) {
                            Image(systemName: "character.cursor.ibeam")
                                .font(.system(size: 18, weight: .semibold))
                                .foregroundStyle(.white)
                                .frame(width: 34, height: 34)
                                .background(Color.accentColor)
                                .clipShape(RoundedRectangle(cornerRadius: 7))
                            VStack(alignment: .leading, spacing: 1) {
                                Text("RAG-IME").font(.headline)
                                Text("个人输入工作台").font(.caption).foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 8)
                    }
                    .listRowBackground(Color.clear)
                }
                Section("工作区") {
                    ForEach(ControlDestination.allCases) { item in
                        Label(item.title, systemImage: item.symbol)
                            .font(.system(size: 14, weight: .medium))
                            .padding(.vertical, 5)
                            .tag(item)
                    }
                }
            }
            .navigationSplitViewColumnWidth(min: 220, ideal: 232, max: 252)
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
            .background(Color(nsColor: .windowBackgroundColor))
        }
        .navigationSplitViewStyle(.prominentDetail)
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
        .padding(.horizontal, 14)
        .padding(.vertical, 13)
    }
}
