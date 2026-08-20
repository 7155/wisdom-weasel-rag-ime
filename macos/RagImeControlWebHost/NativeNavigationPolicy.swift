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
        if url.scheme == ControlCenterAssetSchemeHandler.scheme,
           url.host == "app",
           url.path == "/__paw_html_preview" {
            return !isMainFrame && url.query == nil ? .allow : .cancel
        }
        if url.scheme == ControlCenterAssetSchemeHandler.scheme, url.host == "app" {
            return .allow
        }
        // Interactive HTML previews use one exact loopback document with an
        // opaque CSP sandbox. It is a child navigation created by the trusted
        // WebView page, never an external top-level destination.
        if url.absoluteString == "about:blank", isMainFrame {
            return .allow
        }
        return .cancel
    }
}
