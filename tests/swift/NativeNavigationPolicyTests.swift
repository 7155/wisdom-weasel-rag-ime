import Foundation
import WebKit

enum ControlCenterAssetSchemeHandler {
    static let scheme = "rag-ime-control"
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    guard condition() else {
        FileHandle.standardError.write(Data("FAIL: \(message)\n".utf8))
        exit(1)
    }
}

@main
struct NativeNavigationPolicyTests {
    static func main() {
        let policy = NativeNavigationPolicy()
        expect(
            policy.allowsExternalBrowserOpen(URL(string: "https://auth.openai.com/codex/device")),
            "OpenAI Codex device login URL"
        )
        for value in [
            "http://auth.openai.com/codex/device",
            "https://evil.invalid/codex/device",
            "https://auth.openai.com/codex/device?token=secret",
            "https://auth.openai.com/other",
            "file:///tmp/auth.json",
        ] {
            expect(!policy.allowsExternalBrowserOpen(URL(string: value)), "reject \(value)")
        }
        expect(
            policy.decision(
                for: URL(string: "rag-ime-control://app/index.html"),
                isMainFrame: true
            ) == .allow,
            "bundled app navigation"
        )
        expect(
            policy.decision(
                for: URL(string: "https://auth.openai.com/codex/device"),
                isMainFrame: true
            ) == .cancel,
            "external URLs never load inside the WebView"
        )
        expect(
            policy.decision(
                for: URL(string: "rag-ime-control://app/__paw_html_preview#fixture"),
                isMainFrame: false
            ) == .allow,
            "isolated loopback previews load in child frames"
        )
        expect(
            policy.decision(
                for: URL(string: "rag-ime-control://app/__paw_html_preview#fixture"),
                isMainFrame: true
            ) == .cancel,
            "loopback previews cannot replace the main document"
        )
        expect(
            policy.decision(
                for: URL(string: "http://127.0.0.1:8766/__paw_html_preview"),
                isMainFrame: false
            ) == .cancel,
            "loopback preview bypasses stay blocked in the native host"
        )
        print("NativeNavigationPolicyTests: OK")
    }
}
