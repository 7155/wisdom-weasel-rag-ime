import Foundation
import WebKit

struct NativeNavigationPolicy {
    func allowsExternalBrowserOpen(_ url: URL?) -> Bool {
        guard let url,
              url.scheme == "https",
              url.host == "auth.openai.com",
              url.path == "/codex/device",
              url.port == nil,
              url.user == nil,
              url.password == nil,
              url.query == nil,
              url.fragment == nil else {
            return false
        }
        return true
    }

    func decision(for url: URL?, isMainFrame: Bool) -> WKNavigationActionPolicy {
        guard let url else { return .cancel }
        if url.scheme == ControlCenterAssetSchemeHandler.scheme, url.host == "app" {
            return .allow
        }
        if url.absoluteString == "about:blank", isMainFrame {
            return .allow
        }
        return .cancel
    }
}
