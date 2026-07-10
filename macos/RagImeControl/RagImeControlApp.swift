import SwiftUI

@main
struct RagImeControlApp: App {
    @NSApplicationDelegateAdaptor(ControlAppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        WindowGroup("RAG-IME 控制中心") {
            ControlRootView()
                .environmentObject(model)
                .frame(minWidth: 820, minHeight: 560)
                .task { await model.start() }
                .onDisappear { model.stop() }
        }
        .defaultSize(width: 920, height: 640)
        .commands {
            CommandGroup(replacing: .newItem) { }
        }
    }
}
