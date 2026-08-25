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
        "frame-src 'self' blob:",
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
              requestURL.host == "app" else {
            fail(urlSchemeTask, code: 400, message: "Invalid control-center asset path")
            return
        }

        if requestURL.path == "/__paw_html_preview", requestURL.query == nil {
            serveIsolatedHTMLPreview(urlSchemeTask, requestURL: requestURL)
            return
        }

        guard let fileURL = resolvedFileURL(for: requestURL) else {
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

    private func serveIsolatedHTMLPreview(
        _ task: WKURLSchemeTask,
        requestURL: URL
    ) {
        let document = """
        <!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <title>PAW HTML Preview</title></head><body>
        <noscript>This preview requires JavaScript.</noscript><script>
        (() => {
          try {
            const encoded = location.hash.slice(1).replace(/-/g, '+').replace(/_/g, '/');
            if (!encoded) throw new Error('preview source is missing');
            const padded = encoded + '='.repeat((4 - encoded.length % 4) % 4);
            const binary = atob(padded);
            const bytes = Uint8Array.from(binary, character => character.charCodeAt(0));
            const source = new TextDecoder().decode(bytes);
            document.open(); document.write(source); document.close();
          } catch (error) {
            document.body.textContent = `HTML preview failed: ${String(error)}`;
          }
        })();
        </script></body></html>
        """
        let data = Data(document.utf8)
        let previewCSP = [
            "default-src 'none'",
            "script-src 'unsafe-inline' https: http: blob: data:",
            "style-src 'unsafe-inline' https: http:",
            "img-src data: blob: https: http:",
            "font-src data: blob: https: http:",
            "media-src data: blob: https: http:",
            "connect-src https: http: ws: wss:",
            "worker-src blob: data:",
            "child-src blob: data: https: http:",
            "object-src 'none'",
            "base-uri 'none'",
            "form-action https: http:",
            "sandbox allow-downloads allow-forms allow-modals allow-pointer-lock allow-popups allow-scripts",
        ].joined(separator: "; ")
        let headers = [
            "Content-Type": "text/html; charset=utf-8",
            "Content-Length": String(data.count),
            "Content-Security-Policy": previewCSP,
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        ]
        guard let response = HTTPURLResponse(
            url: requestURL,
            statusCode: 200,
            httpVersion: "HTTP/1.1",
            headerFields: headers
        ) else {
            fail(task, code: 500, message: "Unable to create preview response")
            return
        }
        task.didReceive(response)
        task.didReceive(data)
        task.didFinish()
    }

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
