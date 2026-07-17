import AppKit
import ApplicationServices
import Darwin
import Foundation

@main
enum RagImeDesktopBridgeMain {
    static func main() {
        if CommandLine.arguments.contains("--request-accessibility-only") {
            exit(requestAccessibility(prompt: true) ? 0 : 2)
        }
        if CommandLine.arguments.contains("--headless") {
            runHeadless()
            return
        }
        let application = NSApplication.shared
        let delegate = DesktopBridgeApplicationDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        application.run()
        withExtendedLifetime(delegate) { }
    }

    private static func runHeadless() {
        if CommandLine.arguments.contains("--request-accessibility") {
            _ = requestAccessibility(prompt: true)
        }
        do {
            let service = DesktopAccessibilityService()
            let server = DesktopBridgeSocketServer(service: service)
            try server.start()
            let terminationSources = [SIGINT, SIGTERM].map { signalNumber in
                signal(signalNumber, SIG_IGN)
                let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
                source.setEventHandler {
                    server.stop()
                    CFRunLoopStop(CFRunLoopGetMain())
                }
                source.resume()
                return source
            }
            RunLoop.main.run()
            server.stop()
            withExtendedLifetime((service, server, terminationSources)) { }
        } catch {
            FileHandle.standardError.write(
                Data("RagImeDesktopBridge failed to start: \(error)\n".utf8)
            )
            exit(1)
        }
    }

    private static func requestAccessibility(prompt: Bool) -> Bool {
        let options = [
            kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: prompt
        ] as CFDictionary
        return AXIsProcessTrustedWithOptions(options)
    }
}

@MainActor
final class DesktopBridgeApplicationDelegate: NSObject, NSApplicationDelegate {
    private var server: DesktopBridgeSocketServer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        if CommandLine.arguments.contains("--request-accessibility") {
            let options = [
                kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String: true
            ] as CFDictionary
            _ = AXIsProcessTrustedWithOptions(options)
        }

        do {
            let service = DesktopAccessibilityService()
            let server = DesktopBridgeSocketServer(service: service)
            try server.start()
            self.server = server
        } catch {
            FileHandle.standardError.write(
                Data("RagImeDesktopBridge failed to start: \(error)\n".utf8)
            )
            NSApplication.shared.terminate(nil)
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        server?.stop()
        server = nil
    }
}
