import AppKit
import WebKit

final class WebHostViewController: NSViewController, WKNavigationDelegate, WKUIDelegate {
    private let routePolicy = NativeRoutePolicy()
    private let navigationPolicy = NativeNavigationPolicy()
    private lazy var nativeBridge = NativeBridge(routePolicy: routePolicy)
    private var webView: WKWebView?

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
        self.webView = nil
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
        let entryURL = URL(string: "\(ControlCenterAssetSchemeHandler.scheme)://app/index.html")!
        webView.load(URLRequest(url: entryURL))
    }
}
