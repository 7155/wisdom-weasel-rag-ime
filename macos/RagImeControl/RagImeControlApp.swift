import SwiftUI

@main
struct RagImeControlApp: App {
    @NSApplicationDelegateAdaptor(ControlAppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("RAG-IME 控制中心") {
            ControlRootView()
                .environmentObject(model)
                .frame(minWidth: 1080, minHeight: 720)
                .task { await model.start() }
                .onDisappear { model.stop() }
        }
        .defaultSize(width: 1280, height: 820)
        .commands {
            CommandGroup(replacing: .newItem) { }
        }
    }
}
