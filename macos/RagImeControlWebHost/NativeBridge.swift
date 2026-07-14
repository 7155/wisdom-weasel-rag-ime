import AppKit
import Foundation
import UniformTypeIdentifiers
import WebKit

final class NativeBridge: NSObject, WKScriptMessageHandler {
    static let handlerName = "ragImeNativeBridge"

    private static let allowedMethods: Set<String> = [
        "capabilities",
        "request",
        "subscribe",
        "cancelSubscription",
        "pickFiles",
        "revealPath",
        "runApprovedExternalAction",
    ]

    private weak var webView: WKWebView?
    private let routePolicy: NativeRoutePolicy
    private let requestSession: URLSession
    private var requestTasks: [String: URLSessionDataTask] = [:]
    private var allowedRevealPaths: Set<String> = []
    private lazy var eventBridge = NativeEventBridge { [weak self] envelope in
        self?.sendToWeb(envelope)
    }

    init(routePolicy: NativeRoutePolicy) {
        self.routePolicy = routePolicy
        let configuration = URLSessionConfiguration.ephemeral
        configuration.timeoutIntervalForRequest = 30
        configuration.timeoutIntervalForResource = 120
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        self.requestSession = URLSession(configuration: configuration)
        super.init()
    }

    func attach(webView: WKWebView) {
        self.webView = webView
    }

    func shutdown() {
        requestTasks.values.forEach { $0.cancel() }
        requestTasks.removeAll()
        eventBridge.cancelAll()
        requestSession.invalidateAndCancel()
        webView = nil
    }

    func userContentController(_ userContentController: WKUserContentController, didReceive message: WKScriptMessage) {
        guard message.name == Self.handlerName,
              let envelope = message.body as? [String: Any],
              let id = envelope["id"] as? String,
              !id.isEmpty,
              id.utf8.count <= 160,
              let method = envelope["method"] as? String,
              Self.allowedMethods.contains(method),
              !requestTasks.keys.contains(id) else {
            let fallbackId = (message.body as? [String: Any])?["id"] as? String ?? "invalid"
            replyError(id: fallbackId, code: "invalid_bridge_request", message: "Native bridge request was rejected")
            return
        }

        let payload = envelope["payload"] as? [String: Any] ?? [:]
        switch method {
        case "capabilities":
            replySuccess(id: id, result: capabilities())
        case "request":
            performRequest(id: id, payload: payload)
        case "subscribe":
            subscribe(id: id, payload: payload)
        case "cancelSubscription":
            cancelSubscription(id: id, payload: payload)
        case "pickFiles":
            pickFiles(id: id, payload: payload)
        case "revealPath":
            revealPath(id: id, payload: payload)
        case "runApprovedExternalAction":
            runApprovedExternalAction(id: id, payload: payload)
        default:
            replyError(id: id, code: "unsupported_bridge_method", message: "Native bridge method is not allowlisted")
        }
    }

    private func capabilities() -> [String: Any] {
        [
            "schemaVersion": "rag-ime.control-capabilities.v1",
            "transport": "native",
            "platform": "macos",
            "nativeBridgeVersion": 1,
            "routeIds": NativeRoutePolicy.knownPathIds.sorted(),
            "features": [
                "agentStreaming": true,
                "roomStreaming": true,
                "filePicker": true,
            ],
            "native": [
                "pickFiles": true,
                "revealPath": true,
                "approvedExternalActions": true,
                "keychain": false,
                "tcc": true,
            ],
            "security": [
                "keychainValuesReadable": false,
                "arbitraryFetch": false,
                "arbitraryShell": false,
            ],
        ]
    }

    private func performRequest(id: String, payload: [String: Any]) {
        do {
            let pathId = try requiredString("pathId", in: payload)
            if pathId == "control.capabilities" {
                replySuccess(id: id, result: capabilities())
                return
            }
            if pathId == "control.bootstrap" {
                replySuccess(
                    id: id,
                    result: [
                        "schemaVersion": "rag-ime.control-bootstrap.v1",
                        "capabilities": capabilities(),
                        "connection": ["state": "bootstrapping"],
                    ]
                )
                return
            }
            let parameters = try stringDictionary(payload["params"])
            let query = try stringDictionary(payload["query"])
            let resolved = try routePolicy.resolveRequest(
                pathId: pathId,
                parameters: parameters,
                query: query,
                body: payload["body"]
            )
            let task = requestSession.dataTask(with: resolved.request) { [weak self] data, response, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.requestTasks.removeValue(forKey: id)
                    if let error = error as NSError? {
                        self.replyError(
                            id: id,
                            code: "native_request_failed",
                            message: error.localizedDescription,
                            retryable: [NSURLErrorTimedOut, NSURLErrorCannotConnectToHost, NSURLErrorNetworkConnectionLost].contains(error.code)
                        )
                        return
                    }
                    guard let http = response as? HTTPURLResponse, let data else {
                        self.replyError(id: id, code: "invalid_native_response", message: "Local service returned no HTTP response")
                        return
                    }
                    guard data.count <= 10_485_760 else {
                        self.replyError(id: id, code: "native_response_too_large", message: "Local service response exceeded 10 MiB")
                        return
                    }
                    let decoded: Any = (try? JSONSerialization.jsonObject(with: data))
                        ?? ["text": String(data: data, encoding: .utf8) ?? ""]
                    guard (200..<300).contains(http.statusCode) else {
                        let message = (decoded as? [String: Any])?["error"] as? String
                            ?? "Local service returned HTTP \(http.statusCode)"
                        self.replyError(
                            id: id,
                            code: "local_http_\(http.statusCode)",
                            message: message,
                            retryable: http.statusCode >= 500,
                            details: ["status": http.statusCode]
                        )
                        return
                    }
                    self.replySuccess(id: id, result: decoded)
                }
            }
            requestTasks[id] = task
            task.resume()
        } catch {
            replyError(id: id, code: "route_policy_rejected", message: error.localizedDescription)
        }
    }

    private func subscribe(id: String, payload: [String: Any]) {
        do {
            guard let request = payload["request"] as? [String: Any] else {
                throw NativeRoutePolicyError.invalidParameter("request")
            }
            let pathId = try requiredString("pathId", in: request)
            let subscriptionId = try requiredString("subscriptionId", in: payload)
            let lastEventId = (request["lastEventId"] as? String) ?? ""
            let resolved = try routePolicy.resolveSubscription(
                pathId: pathId,
                parameters: try stringDictionary(request["params"]),
                query: try stringDictionary(request["query"]),
                lastEventId: lastEventId
            )
            try eventBridge.subscribe(
                subscriptionId: subscriptionId,
                request: resolved.request,
                lastEventId: lastEventId
            )
            replySuccess(id: id, result: ["subscriptionId": subscriptionId])
        } catch {
            replyError(id: id, code: "subscription_rejected", message: error.localizedDescription)
        }
    }

    private func cancelSubscription(id: String, payload: [String: Any]) {
        do {
            let subscriptionId = try requiredString("subscriptionId", in: payload)
            replySuccess(
                id: id,
                result: [
                    "subscriptionId": subscriptionId,
                    "cancelled": eventBridge.cancel(subscriptionId: subscriptionId),
                ]
            )
        } catch {
            replyError(id: id, code: "invalid_subscription", message: error.localizedDescription)
        }
    }

    private func pickFiles(id: String, payload: [String: Any]) {
        let panel = NSOpenPanel()
        let purpose = payload["purpose"] as? String ?? "attachment"
        panel.canChooseFiles = purpose != "export-destination"
        panel.canChooseDirectories = purpose == "export-destination"
        panel.allowsMultipleSelection = payload["multiple"] as? Bool ?? false
        panel.resolvesAliases = true
        panel.prompt = "选择"
        if let accepts = payload["accepts"] as? [String] {
            let allowedTypes = accepts.compactMap { value -> UTType? in
                if value.hasPrefix(".") {
                    return UTType(filenameExtension: String(value.dropFirst()))
                }
                return UTType(mimeType: value)
            }
            if !allowedTypes.isEmpty { panel.allowedContentTypes = allowedTypes }
        }
        panel.begin { [weak self] response in
            guard let self else { return }
            guard response == .OK else {
                self.replySuccess(id: id, result: [])
                return
            }
            let files = panel.urls.prefix(20).map { url -> [String: Any] in
                let values = try? url.resourceValues(forKeys: [.fileSizeKey, .isDirectoryKey])
                self.allowedRevealPaths.insert(url.standardizedFileURL.path)
                let contentTypeValues = try? url.resourceValues(forKeys: [.contentTypeKey])
                return [
                    "id": UUID().uuidString,
                    "path": url.path,
                    "name": url.lastPathComponent,
                    "mimeType": contentTypeValues?.contentType?.preferredMIMEType ?? "application/octet-stream",
                    "byteSize": values?.fileSize ?? 0,
                ]
            }
            self.replySuccess(id: id, result: Array(files))
        }
    }

    private func revealPath(id: String, payload: [String: Any]) {
        do {
            let path = try requiredString("path", in: payload)
            let standardized = URL(fileURLWithPath: path).standardizedFileURL.path
            guard allowedRevealPaths.contains(standardized) else {
                replyError(id: id, code: "path_not_user_selected", message: "Only paths selected in this app session may be revealed")
                return
            }
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: standardized)])
            replySuccess(id: id, result: ["revealed": true])
        } catch {
            replyError(id: id, code: "invalid_path", message: error.localizedDescription)
        }
    }

    private func runApprovedExternalAction(id: String, payload: [String: Any]) {
        do {
            let action = try requiredString("action", in: payload)
            let receiptId = try requiredString("receiptId", in: payload)
            let payloadHash = try requiredString("payloadSha256", in: payload)
            let commandHash = try requiredString("commandSha256", in: payload)
            guard payloadHash.range(of: "^[a-fA-F0-9]{64}$", options: .regularExpression) != nil,
                  commandHash.range(of: "^[a-fA-F0-9]{64}$", options: .regularExpression) != nil else {
                replyError(id: id, code: "approval_required", message: "External action requires approved payload and command hashes")
                return
            }
            guard action == "open_accessibility_settings",
                  let settingsURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") else {
                replyError(id: id, code: "external_action_not_allowed", message: "External action is not allowlisted")
                return
            }
            let opened = NSWorkspace.shared.open(settingsURL)
            replySuccess(
                id: id,
                result: [
                    "receiptId": receiptId,
                    "action": action,
                    "accepted": opened,
                    "completed": opened,
                    "exitCode": opened ? 0 : 1,
                ]
            )
        } catch {
            replyError(id: id, code: "invalid_external_action", message: error.localizedDescription)
        }
    }

    private func requiredString(_ key: String, in payload: [String: Any]) throws -> String {
        guard let value = payload[key] as? String,
              !value.isEmpty,
              value.utf8.count <= 512,
              !value.contains("\0") else {
            throw NativeRoutePolicyError.invalidParameter(key)
        }
        return value
    }

    private func stringDictionary(_ value: Any?) throws -> [String: String] {
        guard let value else { return [:] }
        guard let dictionary = value as? [String: Any], dictionary.count <= 32 else {
            throw NativeRoutePolicyError.invalidParameter("dictionary")
        }
        var result: [String: String] = [:]
        for (key, value) in dictionary {
            guard let stringValue = value as? String else {
                throw NativeRoutePolicyError.invalidParameter(key)
            }
            result[key] = stringValue
        }
        return result
    }

    private func replySuccess(id: String, result: Any) {
        sendToWeb(["id": id, "ok": true, "result": result])
    }

    private func replyError(
        id: String,
        code: String,
        message: String,
        retryable: Bool = false,
        details: [String: Any]? = nil
    ) {
        var error: [String: Any] = [
            "code": code,
            "message": message,
            "retryable": retryable,
        ]
        if let details { error["details"] = details }
        sendToWeb(["id": id, "ok": false, "error": error])
    }

    private func sendToWeb(_ envelope: [String: Any]) {
        DispatchQueue.main.async { [weak self] in
            guard let self,
                  let webView = self.webView,
                  JSONSerialization.isValidJSONObject(envelope),
                  let data = try? JSONSerialization.data(withJSONObject: envelope) else {
                return
            }
            let encoded = data.base64EncodedString()
            let script = """
            (() => {
              const bytes = Uint8Array.from(atob('\(encoded)'), c => c.charCodeAt(0));
              const envelope = JSON.parse(new TextDecoder().decode(bytes));
              window.__RAG_IME_NATIVE_BRIDGE__?.receive(envelope);
            })();
            """
            webView.evaluateJavaScript(script, completionHandler: nil)
        }
    }
}
