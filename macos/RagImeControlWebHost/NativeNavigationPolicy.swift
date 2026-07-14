import Foundation
import WebKit

struct NativeNavigationPolicy {
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
