import AppKit
import WebKit

final class WebHostViewController: NSViewController, WKNavigationDelegate, WKUIDelegate {
    private let routePolicy = NativeRoutePolicy()
    private let navigationPolicy = NativeNavigationPolicy()
    private lazy var nativeBridge = NativeBridge(routePolicy: routePolicy)
    private var webView: WKWebView?
    private var isReady = false
    private var pendingAgentSessionId: String?

    override func loadView() {
        let configuration = WKWebViewConfiguration()
        configuration.websiteDataStore = .nonPersistent()
        configuration.preferences.javaScriptCanOpenWindowsAutomatically = false
        configuration.defaultWebpagePreferences.allowsContentJavaScript = true
        configuration.suppressesIncrementalRendering = false

        let assetRoot = Bundle.main.resourceURL!
            .appendingPathComponent("control-center-web", isDirectory: true)
        configuration.setURLSchemeHandler(
            ControlCenterAssetSchemeHandler(assetRoot: assetRoot),
            forURLScheme: ControlCenterAssetSchemeHandler.scheme
        )
        configuration.userContentController.add(nativeBridge, name: NativeBridge.handlerName)
        configuration.userContentController.addUserScript(WKUserScript(
            source: """
            Object.defineProperty(window, '__RAG_IME_NATIVE_HOST__', {
              value: Object.freeze({ version: 1, transport: 'native' }),
              configurable: false,
              writable: false,
            });
            """,
            injectionTime: .atDocumentStart,
            forMainFrameOnly: true
        ))

        let webView = WKWebView(frame: .zero, configuration: configuration)
        webView.navigationDelegate = self
        webView.uiDelegate = self
        webView.allowsMagnification = false
        webView.setValue(false, forKey: "drawsBackground")
        if #available(macOS 13.3, *) {
            webView.isInspectable = ProcessInfo.processInfo.environment["RAG_IME_WEB_HOST_INSPECTABLE"] == "1"
        }
        nativeBridge.attach(webView: webView)
        self.webView = webView
        self.view = webView

        let entryURL = URL(string: "\(ControlCenterAssetSchemeHandler.scheme)://app/index.html")!
        webView.load(URLRequest(url: entryURL))
    }

    func shutdown() {
        guard let webView else { return }
        webView.stopLoading()
        webView.configuration.userContentController.removeScriptMessageHandler(forName: NativeBridge.handlerName)
        nativeBridge.shutdown()
        isReady = false
        pendingAgentSessionId = nil
        self.webView = nil
    }

    func openAgent(sessionId: String) {
        guard sessionId.isEmpty || sessionId.range(
            of: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$",
            options: .regularExpression
        ) != nil else { return }
        pendingAgentSessionId = sessionId
        navigateToPendingAgentIfReady()
    }

    private func navigateToPendingAgentIfReady() {
        guard isReady, let webView, let sessionId = pendingAgentSessionId else { return }
        let route: String
        if sessionId.isEmpty {
            route = "#/agent"
        } else {
            var components = URLComponents()
            components.queryItems = [URLQueryItem(name: "session", value: sessionId)]
            route = "#/agent?\(components.percentEncodedQuery ?? "")"
        }
        guard let routeData = try? JSONSerialization.data(withJSONObject: route, options: .fragmentsAllowed),
              let routeLiteral = String(data: routeData, encoding: .utf8) else { return }
        pendingAgentSessionId = nil
        webView.evaluateJavaScript("window.location.hash = \(routeLiteral)")
    }

    deinit {
        shutdown()
    }

    func webView(
        _ webView: WKWebView,
        decidePolicyFor navigationAction: WKNavigationAction,
        decisionHandler: @escaping (WKNavigationActionPolicy) -> Void
    ) {
        if navigationAction.navigationType == .linkActivated,
           navigationPolicy.allowsExternalBrowserOpen(navigationAction.request.url),
           let url = navigationAction.request.url {
            _ = NSWorkspace.shared.open(url)
            decisionHandler(.cancel)
            return
        }
        decisionHandler(navigationPolicy.decision(
            for: navigationAction.request.url,
            isMainFrame: navigationAction.targetFrame?.isMainFrame ?? false
        ))
    }

    func webView(
        _ webView: WKWebView,
        createWebViewWith configuration: WKWebViewConfiguration,
        for navigationAction: WKNavigationAction,
        windowFeatures: WKWindowFeatures
    ) -> WKWebView? {
        nil
    }

    func webViewWebContentProcessDidTerminate(_ webView: WKWebView) {
        isReady = false
        let entryURL = URL(string: "\(ControlCenterAssetSchemeHandler.scheme)://app/index.html")!
        webView.load(URLRequest(url: entryURL))
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        isReady = true
        navigateToPendingAgentIfReady()
    }
}
