import Foundation
import WebKit

final class ControlCenterAssetSchemeHandler: NSObject, WKURLSchemeHandler {
    static let scheme = "rag-ime-control"

    private let assetRoot: URL
    private let contentSecurityPolicy = [
        "default-src 'none'",
        "script-src 'self'",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob: http://127.0.0.1:8766",
        "font-src 'self'",
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "connect-src 'self'",
        "object-src 'none'",
        "frame-src blob:",
        "base-uri 'none'",
        "form-action 'none'",
    ].joined(separator: "; ")

    init(assetRoot: URL) {
        self.assetRoot = assetRoot.standardizedFileURL
        super.init()
    }

    func webView(_ webView: WKWebView, start urlSchemeTask: WKURLSchemeTask) {
        guard let requestURL = urlSchemeTask.request.url,
              requestURL.scheme == Self.scheme,
              requestURL.host == "app",
              let fileURL = resolvedFileURL(for: requestURL) else {
            fail(urlSchemeTask, code: 400, message: "Invalid control-center asset path")
            return
        }

        do {
            let data = try Data(contentsOf: fileURL, options: .mappedIfSafe)
            let headers = [
                "Content-Type": mimeType(for: fileURL.pathExtension),
                "Content-Length": String(data.count),
                "Content-Security-Policy": contentSecurityPolicy,
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Referrer-Policy": "no-referrer",
            ]
            guard let response = HTTPURLResponse(
                url: requestURL,
                statusCode: 200,
                httpVersion: "HTTP/1.1",
                headerFields: headers
            ) else {
                fail(urlSchemeTask, code: 500, message: "Unable to create asset response")
                return
            }
            urlSchemeTask.didReceive(response)
            urlSchemeTask.didReceive(data)
            urlSchemeTask.didFinish()
        } catch {
            fail(urlSchemeTask, code: 404, message: "Control-center asset not found")
        }
    }

    func webView(_ webView: WKWebView, stop urlSchemeTask: WKURLSchemeTask) {}

    private func resolvedFileURL(for requestURL: URL) -> URL? {
        var relativePath = requestURL.path
        if relativePath.isEmpty || relativePath == "/" {
            relativePath = "/index.html"
        }
        guard let decoded = relativePath.removingPercentEncoding else { return nil }
        let pathComponents = decoded.split(separator: "/", omittingEmptySubsequences: true)
        guard !pathComponents.isEmpty,
              !pathComponents.contains(".."),
              !pathComponents.contains("."),
              !decoded.contains("\\"),
              !decoded.contains("\0") else {
            return nil
        }

        let relative = pathComponents.map(String.init).joined(separator: "/")
        let candidate = assetRoot.appendingPathComponent(relative, isDirectory: false).standardizedFileURL
        let rootPrefix = assetRoot.path.hasSuffix("/") ? assetRoot.path : assetRoot.path + "/"
        guard candidate.path.hasPrefix(rootPrefix), candidate.isFileURL else { return nil }
        return candidate
    }

    private func mimeType(for pathExtension: String) -> String {
        switch pathExtension.lowercased() {
        case "html": return "text/html; charset=utf-8"
        case "js", "mjs": return "text/javascript; charset=utf-8"
        case "css": return "text/css; charset=utf-8"
        case "json", "webmanifest": return "application/json; charset=utf-8"
        case "svg": return "image/svg+xml"
        case "png": return "image/png"
        case "jpg", "jpeg": return "image/jpeg"
        case "webp": return "image/webp"
        case "gif": return "image/gif"
        case "woff": return "font/woff"
        case "woff2": return "font/woff2"
        case "mp3": return "audio/mpeg"
        case "wav": return "audio/wav"
        default: return "application/octet-stream"
        }
    }

    private func fail(_ task: WKURLSchemeTask, code: Int, message: String) {
        task.didFailWithError(NSError(
            domain: "RagImeControlAssetLoader",
            code: code,
            userInfo: [NSLocalizedDescriptionKey: message]
        ))
    }
}
