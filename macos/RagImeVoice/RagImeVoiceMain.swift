import AppKit

@main
enum RagImeVoiceMain {
    static func main() {
        if CommandLine.arguments.contains("--desktop-control") {
            exit(VoiceDesktopControl.run())
        }
        if let probeIndex = CommandLine.arguments.firstIndex(of: "--probe-pcm"),
           CommandLine.arguments.indices.contains(probeIndex + 1) {
            let code = VoiceASRProbe.run(pcmPath: CommandLine.arguments[probeIndex + 1])
            exit(code)
        }
        let application = NSApplication.shared
        let delegate = VoiceApplicationDelegate()
        application.delegate = delegate
        application.setActivationPolicy(.accessory)
        application.run()
        withExtendedLifetime(delegate) { }
    }
}
