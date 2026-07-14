import AppKit
import Foundation
import UniformTypeIdentifiers
import WebKit

private enum NativeMediaImportError: LocalizedError {
    case rejected(String)

    var errorDescription: String? {
        switch self {
        case .rejected(let message): message
        }
    }
}

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
    private var requestTasks: [String: URLSessionTask] = [:]
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
                "managedAgentImageImport": true,
                "managementWorkContract": true,
                "planningWorkContract": true,
                "knowledgeDatabaseWorkContract": true,
            ],
            "native": [
                "pickFiles": true,
                "managedAgentImageImport": true,
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
        do {
            let allowedKeys: Set<String> = ["accepts", "multiple", "purpose", "sessionId", "maxFiles"]
            guard Set(payload.keys).isSubset(of: allowedKeys) else {
                throw NativeMediaImportError.rejected("File picker payload contained an unsupported field")
            }
            let purpose = try requiredString("purpose", in: payload)
            guard ["attachment", "configuration-import", "restore", "export-destination"].contains(purpose) else {
                throw NativeMediaImportError.rejected("File picker purpose is not allowlisted")
            }
            let multiple: Bool
            if let rawMultiple = payload["multiple"] {
                guard let value = rawMultiple as? Bool else {
                    throw NativeMediaImportError.rejected("File picker multiple must be a boolean")
                }
                multiple = value
            } else {
                multiple = false
            }
            let accepts: [String]
            if let rawAccepts = payload["accepts"] {
                guard let value = rawAccepts as? [String], value.count <= 32 else {
                    throw NativeMediaImportError.rejected("File picker accepts must be a bounded string array")
                }
                accepts = value
            } else {
                accepts = []
            }
            let requestedCount: Int
            if let rawCount = payload["maxFiles"] {
                guard let value = rawCount as? Int else {
                    throw NativeMediaImportError.rejected("File picker maxFiles must be an integer")
                }
                requestedCount = value
            } else {
                requestedCount = multiple ? 8 : 1
            }
            guard (1...8).contains(requestedCount) else {
                throw NativeMediaImportError.rejected("File picker maxFiles must be between 1 and 8")
            }
            if purpose == "attachment" {
                let sessionId = try requiredString("sessionId", in: payload)
                guard sessionId.range(of: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$", options: .regularExpression) != nil else {
                    throw NativeMediaImportError.rejected("Attachment sessionId is invalid")
                }
                presentAgentImagePicker(
                    id: id,
                    sessionId: sessionId,
                    maxFiles: requestedCount,
                    multiple: multiple
                )
                return
            }
            guard payload["sessionId"] == nil else {
                throw NativeMediaImportError.rejected("sessionId is only accepted for Agent attachments")
            }
            presentLocalPathPicker(
                id: id,
                purpose: purpose,
                accepts: accepts,
                maxFiles: requestedCount,
                multiple: multiple
            )
        } catch {
            replyError(id: id, code: "file_picker_rejected", message: error.localizedDescription)
        }
    }

    private func presentAgentImagePicker(
        id: String,
        sessionId: String,
        maxFiles: Int,
        multiple: Bool
    ) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = multiple && maxFiles > 1
        panel.resolvesAliases = true
        panel.prompt = "导入"
        panel.allowedContentTypes = ["image/png", "image/jpeg", "image/gif", "image/webp"].compactMap {
            UTType(mimeType: $0)
        }
        panel.begin { [weak self] response in
            guard let self else { return }
            guard response == .OK else {
                self.replySuccess(id: id, result: [])
                return
            }
            do {
                let selected = try panel.urls.prefix(maxFiles).map(self.validatedAgentImage)
                guard !selected.isEmpty else {
                    throw NativeMediaImportError.rejected("No image was selected")
                }
                self.uploadAgentImages(id: id, sessionId: sessionId, files: Array(selected))
            } catch {
                self.replyError(id: id, code: "agent_media_selection_rejected", message: error.localizedDescription)
            }
        }
    }

    private func presentLocalPathPicker(
        id: String,
        purpose: String,
        accepts: [String],
        maxFiles: Int,
        multiple: Bool
    ) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = purpose != "export-destination"
        panel.canChooseDirectories = purpose == "export-destination"
        panel.allowsMultipleSelection = multiple && maxFiles > 1
        panel.resolvesAliases = true
        panel.prompt = "选择"
        let allowedTypes = accepts.compactMap { value -> UTType? in
            if value.hasPrefix(".") {
                return UTType(filenameExtension: String(value.dropFirst()))
            }
            return UTType(mimeType: value)
        }
        if !allowedTypes.isEmpty { panel.allowedContentTypes = allowedTypes }
        panel.begin { [weak self] response in
            guard let self else { return }
            guard response == .OK else {
                self.replySuccess(id: id, result: [])
                return
            }
            let files = panel.urls.prefix(maxFiles).map { url -> [String: Any] in
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

    private struct SelectedAgentImage {
        let url: URL
        let name: String
        let mimeType: String
        let byteSize: Int
    }

    private func validatedAgentImage(_ sourceURL: URL) throws -> SelectedAgentImage {
        let url = sourceURL.standardizedFileURL
        guard url.isFileURL else {
            throw NativeMediaImportError.rejected("Agent attachments must be local files")
        }
        let values = try url.resourceValues(
            forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey, .contentTypeKey]
        )
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            throw NativeMediaImportError.rejected("Agent attachments must be regular non-symlink files")
        }
        guard let byteSize = values.fileSize, byteSize > 0, byteSize <= 20 * 1024 * 1024 else {
            throw NativeMediaImportError.rejected("Agent images must be non-empty and no larger than 20 MiB")
        }
        let mimeType = values.contentType?.preferredMIMEType?.lowercased() ?? ""
        guard ["image/png", "image/jpeg", "image/gif", "image/webp"].contains(mimeType) else {
            throw NativeMediaImportError.rejected("Only PNG, JPEG, GIF, and WebP Agent images are supported")
        }
        let name = url.lastPathComponent
        guard !name.isEmpty, name.utf8.count <= 512, !name.contains("\0") else {
            throw NativeMediaImportError.rejected("Agent image file name is invalid")
        }
        return SelectedAgentImage(url: url, name: name, mimeType: mimeType, byteSize: byteSize)
    }

    private func uploadAgentImages(
        id: String,
        sessionId: String,
        files: [SelectedAgentImage],
        index: Int = 0,
        receipts: [[String: Any]] = []
    ) {
        guard index < files.count else {
            requestTasks.removeValue(forKey: id)
            replySuccess(id: id, result: receipts)
            return
        }
        let file = files[index]
        var components = URLComponents()
        components.scheme = "http"
        components.host = "127.0.0.1"
        components.port = 8766
        components.path = "/api/agent/media/import"
        components.queryItems = [
            URLQueryItem(name: "sessionId", value: sessionId),
            URLQueryItem(name: "fileName", value: file.name),
        ]
        guard let url = components.url,
              url.scheme == "http",
              url.host == "127.0.0.1",
              url.port == 8766 else {
            replyError(id: id, code: "agent_media_import_rejected", message: "Managed media import URL could not be constructed")
            return
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(file.mimeType, forHTTPHeaderField: "Content-Type")
        request.setValue(String(file.byteSize), forHTTPHeaderField: "Content-Length")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        let task = requestSession.uploadTask(with: request, fromFile: file.url) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.requestTasks.removeValue(forKey: id)
                do {
                    let receipt = try self.validatedAgentMediaResponse(
                        data: data,
                        response: response,
                        error: error,
                        sessionId: sessionId,
                        selected: file
                    )
                    var nextReceipts = receipts
                    nextReceipts.append(receipt)
                    self.uploadAgentImages(
                        id: id,
                        sessionId: sessionId,
                        files: files,
                        index: index + 1,
                        receipts: nextReceipts
                    )
                } catch {
                    self.replyError(
                        id: id,
                        code: "agent_media_import_failed",
                        message: error.localizedDescription,
                        retryable: (error as NSError).code == NSURLErrorTimedOut
                    )
                }
            }
        }
        requestTasks[id] = task
        task.resume()
    }

    private func validatedAgentMediaResponse(
        data: Data?,
        response: URLResponse?,
        error: Error?,
        sessionId: String,
        selected: SelectedAgentImage
    ) throws -> [String: Any] {
        if let error { throw error }
        guard let http = response as? HTTPURLResponse else {
            throw NativeMediaImportError.rejected("Managed media import returned no HTTP response")
        }
        guard let data, !data.isEmpty, data.count <= 1_048_576 else {
            throw NativeMediaImportError.rejected("Managed media import returned an invalid response size")
        }
        guard let decoded = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NativeMediaImportError.rejected("Managed media import returned invalid JSON")
        }
        guard http.statusCode == 201 else {
            let message = decoded["error"] as? String ?? "Managed media import returned HTTP \(http.statusCode)"
            throw NativeMediaImportError.rejected(message)
        }
        guard decoded["schemaVersion"] as? String == "rag-ime.agent-media-import.v1",
              decoded["ok"] as? Bool == true,
              let media = decoded["media"] as? [String: Any],
              media["schemaVersion"] as? String == "rag-ime.agent-media.v1",
              let mediaId = media["mediaId"] as? String,
              mediaId.range(of: "^media_[A-Za-z0-9_-]{12,80}$", options: .regularExpression) != nil,
              media["sessionId"] as? String == sessionId,
              media["mimeType"] as? String == selected.mimeType,
              (media["byteSize"] as? NSNumber)?.intValue == selected.byteSize,
              let sha256 = media["sha256"] as? String,
              sha256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              media["origin"] as? String == "user_attachment" else {
            throw NativeMediaImportError.rejected("Managed media import returned an invalid receipt")
        }
        let name = media["fileName"] as? String ?? selected.name
        guard name.utf8.count <= 160 else {
            throw NativeMediaImportError.rejected("Managed media receipt file name is invalid")
        }
        return [
            "id": mediaId,
            "name": name,
            "mimeType": selected.mimeType,
            "byteSize": selected.byteSize,
            "sessionId": sessionId,
            "sha256": sha256,
        ]
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
