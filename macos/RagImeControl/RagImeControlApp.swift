import SwiftUI

@main
struct RagImeControlApp: App {
    @NSApplicationDelegateAdaptor(ControlAppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()
    @StateObject private var navigation = ControlNavigationModel()
    @StateObject private var agentWorkspace = AgentWorkspaceStore()
    @StateObject private var agentRoomWorkspace = AgentRoomWorkspaceStore()
    @StateObject private var agentCenterNavigation = AgentCenterNavigationModel()

    var body: some Scene {
        WindowGroup("智鼬") {
            ControlRootView(model: model)
                .environmentObject(model)
                .environmentObject(navigation)
                .environmentObject(agentWorkspace)
                .environmentObject(agentRoomWorkspace)
                .environmentObject(agentCenterNavigation)
                .frame(minWidth: 1080, minHeight: 720)
                .task { await model.start() }
                .onDisappear {
                    model.stop()
                    agentWorkspace.stop()
                    agentRoomWorkspace.stop()
                }
        }
        .defaultSize(width: 1280, height: 820)
        .commands {
            CommandGroup(replacing: .newItem) { }
        }
    }
}
