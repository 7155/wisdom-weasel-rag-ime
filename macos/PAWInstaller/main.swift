import AppKit

final class Installer: NSObject, NSApplicationDelegate, NSWindowDelegate {
    var window: NSWindow!
    var button: NSButton!
    var progress: NSProgressIndicator!
    var status: NSTextField!
    var output: NSTextView!
    var running = false
    var finished = false

    func applicationDidFinishLaunching(_ notification: Notification) {
        window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 650, height: 460),
                          styleMask: [.titled, .closable, .miniaturizable], backing: .buffered, defer: false)
        window.title = "安装 Personal Agent Workbench"
        window.delegate = self
        let view = window.contentView!
        let title = NSTextField(labelWithString: "Personal Agent Workbench")
        title.font = .systemFont(ofSize: 25, weight: .semibold)
        title.frame = NSRect(x: 28, y: 398, width: 594, height: 36)
        view.addSubview(title)
        let details = NSTextField(wrappingLabelWithString: "Apple Silicon · macOS 14+ · 未签名预览版\n安装桌面端、听写和运行环境到当前用户目录。保留已有数据，并备份旧组件。")
        details.frame = NSRect(x: 28, y: 338, width: 594, height: 52)
        details.textColor = .secondaryLabelColor
        view.addSubview(details)
        status = NSTextField(labelWithString: "安装完成后，可在 Input Studio 中设置听写服务与系统权限。")
        status.frame = NSRect(x: 28, y: 297, width: 594, height: 30)
        view.addSubview(status)
        let scroll = NSScrollView(frame: NSRect(x: 28, y: 86, width: 594, height: 204))
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        output = NSTextView(frame: scroll.bounds)
        output.isEditable = false
        output.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        output.autoresizingMask = [.width]
        scroll.documentView = output
        view.addSubview(scroll)
        progress = NSProgressIndicator(frame: NSRect(x: 28, y: 47, width: 18, height: 18))
        progress.style = .spinning
        progress.isDisplayedWhenStopped = false
        view.addSubview(progress)
        button = NSButton(title: "安装", target: self, action: #selector(clicked))
        button.bezelStyle = .rounded
        button.frame = NSRect(x: 436, y: 30, width: 186, height: 38)
        view.addSubview(button)
        window.center()
        window.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
    }

    func windowShouldClose(_ sender: NSWindow) -> Bool { !running }
    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { true }
    func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
        running ? .terminateCancel : .terminateNow
    }

    @objc func clicked() {
        if finished {
            NSWorkspace.shared.open(FileManager.default.homeDirectoryForCurrentUser.appendingPathComponent("Applications/Personal Agent Workbench.app"))
            NSApp.terminate(nil)
            return
        }
        running = true
        button.isEnabled = false
        progress.startAnimation(nil)
        status.stringValue = "正在安装，请稍候…"
        let resources = Bundle.main.resourceURL!
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/bin/bash")
        process.arguments = [resources.appendingPathComponent("install.sh").path]
        let pipe = Pipe()
        process.standardOutput = pipe
        process.standardError = pipe
        pipe.fileHandleForReading.readabilityHandler = { [weak self] handle in
            let data = handle.availableData
            if data.isEmpty { handle.readabilityHandler = nil; return }
            let text = String(decoding: data, as: UTF8.self)
            DispatchQueue.main.async {
                self?.output.textStorage?.append(NSAttributedString(string: text))
                if let output = self?.output { output.scrollToEndOfDocument(nil) }
            }
        }
        process.terminationHandler = { [weak self] task in
            DispatchQueue.main.async {
                guard let self else { return }
                self.running = false
                self.progress.stopAnimation(nil)
                self.finished = task.terminationStatus == 0
                self.status.stringValue = self.finished ? "安装完成。听写授权和服务配置在应用内完成。" : "安装未完成。请查看下方错误；日志保存在 ~/Library/Logs/PAW Installer。"
                self.button.title = self.finished ? "打开 PAW" : "重试安装"
                self.button.isEnabled = true
            }
        }
        do { try process.run() }
        catch {
            running = false
            progress.stopAnimation(nil)
            status.stringValue = error.localizedDescription
            button.isEnabled = true
        }
    }
}

let app = NSApplication.shared
let delegate = Installer()
app.delegate = delegate
app.setActivationPolicy(.regular)
app.run()
