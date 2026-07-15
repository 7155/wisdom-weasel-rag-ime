import AppKit
import CryptoKit
import Darwin
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

private final class NativeNoRedirectSessionDelegate: NSObject, URLSessionTaskDelegate {
    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

final class NativeBridge: NSObject, WKScriptMessageHandler {
    static let handlerName = "ragImeNativeBridge"

    private static let allowedMethods: Set<String> = [
        "capabilities",
        "request",
        "subscribe",
        "cancelSubscription",
        "cancelRequest",
        "pickFiles",
        "pasteImages",
        "readKnowledgeAsset",
        "readKnowledgeDocumentSource",
        "revealPath",
        "runApprovedExternalAction",
        "voiceCredentialStatus",
        "voiceCredentialSave",
        "voiceAction",
    ]

    private weak var webView: WKWebView?
    private let routePolicy: NativeRoutePolicy
    private let requestSession: URLSession
    private let assetSessionDelegate: NativeNoRedirectSessionDelegate
    private let assetSession: URLSession
    private var requestTasks: [String: URLSessionTask] = [:]
    private var filePanels: [String: NSOpenPanel] = [:]
    private var binaryTransferIds: [String: String] = [:]
    private var allowedRevealPaths: Set<String> = []
    private var externalActionReceiptsInFlight: Set<String> = []
    private var completedExternalActionReceipts: Set<String> = []
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
        let assetDelegate = NativeNoRedirectSessionDelegate()
        self.assetSessionDelegate = assetDelegate
        self.assetSession = URLSession(
            configuration: configuration,
            delegate: assetDelegate,
            delegateQueue: nil
        )
        super.init()
    }

    func attach(webView: WKWebView) {
        self.webView = webView
    }

    func shutdown() {
        requestTasks.values.forEach { $0.cancel() }
        requestTasks.removeAll()
        filePanels.values.forEach { $0.cancel(nil) }
        filePanels.removeAll()
        binaryTransferIds.removeAll()
        externalActionReceiptsInFlight.removeAll()
        completedExternalActionReceipts.removeAll()
        eventBridge.cancelAll()
        requestSession.invalidateAndCancel()
        assetSession.invalidateAndCancel()
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
              !requestTasks.keys.contains(id),
              !filePanels.keys.contains(id),
              !binaryTransferIds.keys.contains(id) else {
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
        case "cancelRequest":
            cancelRequest(id: id, payload: payload)
        case "pickFiles":
            pickFiles(id: id, payload: payload)
        case "pasteImages":
            pasteImages(id: id, payload: payload)
        case "readKnowledgeAsset":
            readKnowledgeAsset(id: id, payload: payload)
        case "readKnowledgeDocumentSource":
            readKnowledgeDocumentSource(id: id, payload: payload)
        case "revealPath":
            revealPath(id: id, payload: payload)
        case "runApprovedExternalAction":
            runApprovedExternalAction(id: id, payload: payload)
        case "voiceCredentialStatus":
            voiceCredentialStatus(id: id, payload: payload)
        case "voiceCredentialSave":
            voiceCredentialSave(id: id, payload: payload)
        case "voiceAction":
            voiceAction(id: id, payload: payload)
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
                "agentPersonaCreate": true,
                "piProviderCredentials": true,
                "managementWorkContract": true,
                "inputLexiconWorkContract": true,
                "planningWorkContract": true,
                "knowledgeDatabaseWorkContract": true,
                "documentKnowledgeLibrary": true,
                "knowledgeDocumentImport": true,
                "knowledgeParserStatus": true,
                "knowledgeAssetRead": true,
                "knowledgeDocumentSourceRead": true,
                "historyWorkContract": true,
                "configurationSettingsWorkContract": true,
                "memoryGraphRead": true,
                "memoryEntityRead": true,
                "memoryEdit": true,
                "memoryBookArchiveWorkContract": true,
            ],
            "native": [
                "pickFiles": true,
                "managedAgentImageImport": true,
                "knowledgeDocumentImport": true,
                "knowledgeParserStatus": true,
                "knowledgeAssetRead": true,
                "knowledgeDocumentSourceRead": true,
                "revealPath": true,
                "approvedExternalActions": true,
                "keychain": true,
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

    private func cancelRequest(id: String, payload: [String: Any]) {
        do {
            guard Set(payload.keys) == ["requestId"] else {
                throw NativeRoutePolicyError.invalidParameter("requestId")
            }
            let requestId = try requiredString("requestId", in: payload)
            let taskCancelled = requestTasks.removeValue(forKey: requestId).map { task in
                task.cancel()
                return true
            } ?? false
            let panelCancelled = filePanels.removeValue(forKey: requestId).map { panel in
                panel.cancel(nil)
                return true
            } ?? false
            let transferCancelled = cancelKnowledgeBinaryTransfer(requestId: requestId)
            replySuccess(
                id: id,
                result: [
                    "requestId": requestId,
                    "cancelled": taskCancelled || panelCancelled || transferCancelled,
                ]
            )
        } catch {
            replyError(id: id, code: "invalid_request_cancellation", message: error.localizedDescription)
        }
    }

    private func pickFiles(id: String, payload: [String: Any]) {
        do {
            let allowedKeys: Set<String> = ["accepts", "multiple", "purpose", "sessionId", "kbId", "parserProvider", "maxFiles"]
            guard Set(payload.keys).isSubset(of: allowedKeys) else {
                throw NativeMediaImportError.rejected("File picker payload contained an unsupported field")
            }
            let purpose = try requiredString("purpose", in: payload)
            guard ["attachment", "configuration-import", "restore", "export-destination", "knowledge-import"].contains(purpose) else {
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
            let maximumCount = purpose == "knowledge-import" ? 20 : 8
            guard (1...maximumCount).contains(requestedCount) else {
                throw NativeMediaImportError.rejected("File picker maxFiles is outside the allowed range")
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
            if purpose == "knowledge-import" {
                guard payload["sessionId"] == nil else {
                    throw NativeMediaImportError.rejected("sessionId is only accepted for Agent attachments")
                }
                let kbId = try requiredString("kbId", in: payload)
                guard kbId.range(of: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,127}$", options: .regularExpression) != nil else {
                    throw NativeMediaImportError.rejected("Knowledge base id is invalid")
                }
                let parserProvider = payload["parserProvider"] as? String ?? "auto"
                guard ["auto", "builtin", "mineru_local_http"].contains(parserProvider) else {
                    throw NativeMediaImportError.rejected("Knowledge parser provider is not allowlisted")
                }
                presentKnowledgeDocumentPicker(
                    id: id,
                    kbId: kbId,
                    parserProvider: parserProvider,
                    accepts: accepts,
                    maxFiles: requestedCount,
                    multiple: multiple
                )
                return
            }
            guard payload["sessionId"] == nil else {
                throw NativeMediaImportError.rejected("sessionId is only accepted for Agent attachments")
            }
            guard payload["kbId"] == nil, payload["parserProvider"] == nil else {
                throw NativeMediaImportError.rejected("Knowledge import fields require the knowledge-import purpose")
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

    private func pasteImages(id: String, payload: [String: Any]) {
        do {
            let allowedKeys: Set<String> = ["sessionId", "maxFiles"]
            guard Set(payload.keys).isSubset(of: allowedKeys) else {
                throw NativeMediaImportError.rejected("Image paste payload contained an unsupported field")
            }
            let sessionId = try requiredString("sessionId", in: payload)
            guard sessionId.range(of: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$", options: .regularExpression) != nil else {
                throw NativeMediaImportError.rejected("Attachment sessionId is invalid")
            }
            guard let number = payload["maxFiles"] as? NSNumber,
                  CFGetTypeID(number) != CFBooleanGetTypeID(),
                  number.doubleValue == Double(number.intValue),
                  (1...8).contains(number.intValue) else {
                throw NativeMediaImportError.rejected("Image paste maxFiles must be between 1 and 8")
            }
            let selected = try pastedAgentImages(maxFiles: number.intValue)
            guard !selected.isEmpty else {
                throw NativeMediaImportError.rejected("The clipboard does not contain a supported image")
            }
            uploadAgentImages(id: id, sessionId: sessionId, files: selected)
        } catch {
            replyError(id: id, code: "agent_media_paste_rejected", message: error.localizedDescription)
        }
    }

    private struct NativeKnowledgeAsset {
        let data: Data
        let mimeType: String
        let byteSize: Int
        let sha256: String
    }

    private func readKnowledgeAsset(id: String, payload: [String: Any]) {
        do {
            let allowedKeys: Set<String> = ["kbId", "fileId", "assetId"]
            guard Set(payload.keys).isSubset(of: allowedKeys) else {
                throw NativeMediaImportError.rejected("Knowledge asset payload contained an unsupported field")
            }
            let kbId = try requiredString("kbId", in: payload)
            let fileId = try requiredString("fileId", in: payload)
            let assetId = try requiredString("assetId", in: payload)
            guard kbId.range(of: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$", options: .regularExpression) != nil,
                  fileId.range(of: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$", options: .regularExpression) != nil,
                  assetId.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil else {
                throw NativeMediaImportError.rejected("Knowledge asset identifiers are invalid")
            }
            let resolved = try routePolicy.resolveBinary(
                pathId: "knowledgeBases.asset.get",
                parameters: ["kbId": kbId, "fileId": fileId, "assetId": assetId]
            )
            let expectedURL = resolved.request.url
            let task = assetSession.dataTask(with: resolved.request) { [weak self] data, response, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    do {
                        let asset = try self.validatedKnowledgeAssetResponse(
                            data: data,
                            response: response,
                            error: error,
                            expectedURL: expectedURL,
                            assetId: assetId
                        )
                        self.sendKnowledgeAssetToWeb(
                            id: id,
                            kbId: kbId,
                            fileId: fileId,
                            assetId: assetId,
                            asset: asset
                        )
                    } catch {
                        self.requestTasks.removeValue(forKey: id)
                        self.replyError(
                            id: id,
                            code: "knowledge_asset_read_failed",
                            message: error.localizedDescription,
                            retryable: (error as NSError).code == NSURLErrorTimedOut
                        )
                    }
                }
            }
            requestTasks[id] = task
            task.resume()
        } catch {
            replyError(id: id, code: "knowledge_asset_read_rejected", message: error.localizedDescription)
        }
    }

    private func readKnowledgeDocumentSource(id: String, payload: [String: Any]) {
        do {
            let allowedKeys: Set<String> = ["kbId", "fileId"]
            guard Set(payload.keys).isSubset(of: allowedKeys) else {
                throw NativeMediaImportError.rejected("Knowledge source payload contained an unsupported field")
            }
            let kbId = try requiredString("kbId", in: payload)
            let fileId = try requiredString("fileId", in: payload)
            guard kbId.range(of: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$", options: .regularExpression) != nil,
                  fileId.range(of: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$", options: .regularExpression) != nil else {
                throw NativeMediaImportError.rejected("Knowledge source identifiers are invalid")
            }
            let resolved = try routePolicy.resolveBinary(
                pathId: "knowledgeBases.document.source",
                parameters: ["kbId": kbId, "fileId": fileId]
            )
            let expectedURL = resolved.request.url
            let task = assetSession.dataTask(with: resolved.request) { [weak self] data, response, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.requestTasks.removeValue(forKey: id)
                    do {
                        let source = try self.validatedKnowledgeSourceResponse(
                            data: data,
                            response: response,
                            error: error,
                            expectedURL: expectedURL
                        )
                        self.sendKnowledgeBinaryToWeb(
                            id: id,
                            metadata: ["kbId": kbId, "fileId": fileId],
                            binary: source
                        )
                    } catch {
                        self.replyError(
                            id: id,
                            code: "knowledge_source_read_failed",
                            message: error.localizedDescription,
                            retryable: (error as NSError).code == NSURLErrorTimedOut
                        )
                    }
                }
            }
            requestTasks[id] = task
            task.resume()
        } catch {
            replyError(id: id, code: "knowledge_source_read_rejected", message: error.localizedDescription)
        }
    }

    private func validatedKnowledgeAssetResponse(
        data: Data?,
        response: URLResponse?,
        error: Error?,
        expectedURL: URL?,
        assetId: String
    ) throws -> NativeKnowledgeAsset {
        if let error { throw error }
        guard let http = response as? HTTPURLResponse,
              http.statusCode == 200,
              http.url == expectedURL else {
            throw NativeMediaImportError.rejected("Knowledge asset returned an invalid or redirected response")
        }
        guard let data, !data.isEmpty, data.count <= 25 * 1024 * 1024 else {
            throw NativeMediaImportError.rejected("Knowledge asset exceeds the 25 MiB response limit")
        }
        let mimeType = http.value(forHTTPHeaderField: "Content-Type")?
            .split(separator: ";", maxSplits: 1)
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() ?? ""
        let allowedMimeTypes: Set<String> = [
            "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
        ]
        guard allowedMimeTypes.contains(mimeType),
              http.expectedContentLength == Int64(data.count),
              http.value(forHTTPHeaderField: "X-Content-Type-Options")?.lowercased() == "nosniff",
              http.value(forHTTPHeaderField: "Content-Disposition")?.lowercased().hasPrefix("inline") == true else {
            throw NativeMediaImportError.rejected("Knowledge asset returned invalid security headers")
        }
        let entityTag = (http.value(forHTTPHeaderField: "ETag") ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "W/", with: "")
            .trimmingCharacters(in: CharacterSet(charactersIn: "\""))
            .lowercased()
        let actualSha256 = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard entityTag == assetId, actualSha256 == assetId else {
            throw NativeMediaImportError.rejected("Knowledge asset content identity did not match assetId")
        }
        return NativeKnowledgeAsset(
            data: data,
            mimeType: mimeType,
            byteSize: data.count,
            sha256: actualSha256
        )
    }

    private func validatedKnowledgeSourceResponse(
        data: Data?,
        response: URLResponse?,
        error: Error?,
        expectedURL: URL?
    ) throws -> NativeKnowledgeAsset {
        if let error { throw error }
        guard let http = response as? HTTPURLResponse,
              http.statusCode == 200,
              http.url == expectedURL else {
            throw NativeMediaImportError.rejected("Knowledge source returned an invalid or redirected response")
        }
        guard let data, !data.isEmpty, data.count <= 50 * 1024 * 1024 else {
            throw NativeMediaImportError.rejected("Knowledge source exceeds the 50 MiB preview limit")
        }
        let mimeType = http.value(forHTTPHeaderField: "Content-Type")?
            .split(separator: ";", maxSplits: 1)
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() ?? ""
        let allowedMimeTypes: Set<String> = [
            "application/pdf",
            "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp", "image/tiff",
            "text/plain", "text/markdown", "text/csv", "application/json",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ]
        guard allowedMimeTypes.contains(mimeType),
              http.expectedContentLength == Int64(data.count),
              http.value(forHTTPHeaderField: "X-Content-Type-Options")?.lowercased() == "nosniff",
              http.value(forHTTPHeaderField: "Content-Disposition")?.lowercased().hasPrefix("inline") == true else {
            throw NativeMediaImportError.rejected("Knowledge source returned invalid security headers")
        }
        let entityTag = (http.value(forHTTPHeaderField: "ETag") ?? "")
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .replacingOccurrences(of: "W/", with: "")
            .trimmingCharacters(in: CharacterSet(charactersIn: "\""))
            .lowercased()
        let actualSha256 = SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
        guard entityTag.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              actualSha256 == entityTag else {
            throw NativeMediaImportError.rejected("Knowledge source content identity did not match ETag")
        }
        return NativeKnowledgeAsset(
            data: data,
            mimeType: mimeType,
            byteSize: data.count,
            sha256: actualSha256
        )
    }

    private func sendKnowledgeAssetToWeb(
        id: String,
        kbId: String,
        fileId: String,
        assetId: String,
        asset: NativeKnowledgeAsset
    ) {
        sendKnowledgeBinaryToWeb(
            id: id,
            metadata: [
                "kbId": kbId,
                "fileId": fileId,
                "assetId": assetId,
            ],
            binary: asset
        )
    }

    private func sendKnowledgeBinaryToWeb(
        id: String,
        metadata: [String: Any],
        binary: NativeKnowledgeAsset
    ) {
        var resultMetadata = metadata
        resultMetadata["id"] = id
        resultMetadata["mimeType"] = binary.mimeType
        resultMetadata["byteSize"] = binary.byteSize
        resultMetadata["sha256"] = binary.sha256
        guard JSONSerialization.isValidJSONObject(resultMetadata),
              let metadataData = try? JSONSerialization.data(withJSONObject: resultMetadata) else {
            replyError(id: id, code: "knowledge_binary_read_failed", message: "Knowledge binary metadata was invalid")
            return
        }
        let metadataBase64 = metadataData.base64EncodedString()
        let transferId = UUID().uuidString
        let script = """
        (() => {
          const decode = value => Uint8Array.from(atob(value), c => c.charCodeAt(0));
          const metadata = JSON.parse(new TextDecoder().decode(decode('\(metadataBase64)')));
          const transfers = window.__RAG_IME_NATIVE_BINARY_TRANSFERS__ ??= new Map();
          transfers.set('\(transferId)', { metadata, parts: [], received: 0 });
        })();
        """
        guard let webView else {
            replyError(id: id, code: "knowledge_binary_read_failed", message: "Native web view is unavailable")
            return
        }
        binaryTransferIds[id] = transferId
        webView.evaluateJavaScript(script) { [weak self] _, error in
            DispatchQueue.main.async {
                guard let self else { return }
                if let error {
                    self.failKnowledgeBinaryTransfer(id: id, transferId: transferId, error: error)
                    return
                }
                self.appendKnowledgeBinaryChunk(
                    id: id,
                    transferId: transferId,
                    binary: binary,
                    ranges: NativeBinaryTransferPlan.chunkRanges(byteCount: binary.data.count),
                    index: 0
                )
            }
        }
    }

    private func appendKnowledgeBinaryChunk(
        id: String,
        transferId: String,
        binary: NativeKnowledgeAsset,
        ranges: [Range<Int>],
        index: Int
    ) {
        guard binaryTransferIds[id] == transferId else { return }
        guard index < ranges.count else {
            finishKnowledgeBinaryTransfer(id: id, transferId: transferId)
            return
        }
        guard let webView else {
            failKnowledgeBinaryTransfer(
                id: id,
                transferId: transferId,
                error: NativeMediaImportError.rejected("Native web view is unavailable")
            )
            return
        }
        let encoded = binary.data.subdata(in: ranges[index]).base64EncodedString()
        let script = """
        (() => {
          const transfer = window.__RAG_IME_NATIVE_BINARY_TRANSFERS__?.get('\(transferId)');
          if (!transfer) throw new Error('Native binary transfer was cancelled');
          const part = Uint8Array.from(atob('\(encoded)'), c => c.charCodeAt(0));
          transfer.parts.push(part);
          transfer.received += part.byteLength;
        })();
        """
        webView.evaluateJavaScript(script) { [weak self] _, error in
            DispatchQueue.main.async {
                guard let self, self.binaryTransferIds[id] == transferId else { return }
                if let error {
                    self.failKnowledgeBinaryTransfer(id: id, transferId: transferId, error: error)
                    return
                }
                self.appendKnowledgeBinaryChunk(
                    id: id,
                    transferId: transferId,
                    binary: binary,
                    ranges: ranges,
                    index: index + 1
                )
            }
        }
    }

    private func finishKnowledgeBinaryTransfer(id: String, transferId: String) {
        guard binaryTransferIds[id] == transferId else { return }
        guard let webView else {
            failKnowledgeBinaryTransfer(
                id: id,
                transferId: transferId,
                error: NativeMediaImportError.rejected("Native web view is unavailable")
            )
            return
        }
        let script = """
        (() => {
          const transfers = window.__RAG_IME_NATIVE_BINARY_TRANSFERS__;
          const transfer = transfers?.get('\(transferId)');
          if (!transfer) throw new Error('Native binary transfer was cancelled');
          transfers.delete('\(transferId)');
          if (transfer.received !== transfer.metadata.byteSize) {
            throw new Error('Native binary transfer size mismatch');
          }
          const id = transfer.metadata.id;
          const blob = new Blob(transfer.parts, { type: transfer.metadata.mimeType });
          delete transfer.metadata.id;
          window.__RAG_IME_NATIVE_BRIDGE__?.receive({
            id,
            ok: true,
            result: { ...transfer.metadata, blob },
          });
        })();
        """
        webView.evaluateJavaScript(script) { [weak self] _, error in
            DispatchQueue.main.async {
                guard let self, self.binaryTransferIds[id] == transferId else { return }
                self.binaryTransferIds.removeValue(forKey: id)
                if let error {
                    self.replyError(
                        id: id,
                        code: "knowledge_binary_transfer_failed",
                        message: error.localizedDescription
                    )
                }
            }
        }
    }

    private func failKnowledgeBinaryTransfer(id: String, transferId: String, error: Error) {
        guard binaryTransferIds[id] == transferId else { return }
        binaryTransferIds.removeValue(forKey: id)
        let cleanup = "window.__RAG_IME_NATIVE_BINARY_TRANSFERS__?.delete('\(transferId)');"
        webView?.evaluateJavaScript(cleanup, completionHandler: nil)
        replyError(id: id, code: "knowledge_binary_transfer_failed", message: error.localizedDescription)
    }

    private func cancelKnowledgeBinaryTransfer(requestId: String) -> Bool {
        guard let transferId = binaryTransferIds.removeValue(forKey: requestId) else { return false }
        let cleanup = "window.__RAG_IME_NATIVE_BINARY_TRANSFERS__?.delete('\(transferId)');"
        webView?.evaluateJavaScript(cleanup, completionHandler: nil)
        return true
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
        filePanels[id] = panel
        panel.begin { [weak self] response in
            guard let self else { return }
            self.filePanels.removeValue(forKey: id)
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
        filePanels[id] = panel
        panel.begin { [weak self] response in
            guard let self else { return }
            self.filePanels.removeValue(forKey: id)
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
        let url: URL?
        let data: Data?
        let name: String
        let mimeType: String
        let byteSize: Int
    }

    private struct SelectedKnowledgeDocument {
        let url: URL
        let name: String
        let mimeType: String
        let byteSize: Int
    }

    private func presentKnowledgeDocumentPicker(
        id: String,
        kbId: String,
        parserProvider: String,
        accepts: [String],
        maxFiles: Int,
        multiple: Bool
    ) {
        let panel = NSOpenPanel()
        panel.canChooseFiles = true
        panel.canChooseDirectories = false
        panel.allowsMultipleSelection = multiple && maxFiles > 1
        panel.resolvesAliases = false
        panel.prompt = "导入"
        let allowedTypes = accepts.compactMap { value -> UTType? in
            if value.hasPrefix(".") {
                return UTType(filenameExtension: String(value.dropFirst()))
            }
            return UTType(mimeType: value)
        }
        if !allowedTypes.isEmpty { panel.allowedContentTypes = allowedTypes }
        filePanels[id] = panel
        panel.begin { [weak self] response in
            guard let self else { return }
            self.filePanels.removeValue(forKey: id)
            guard response == .OK else {
                self.replySuccess(id: id, result: [])
                return
            }
            do {
                let selected = try panel.urls.prefix(maxFiles).map(self.validatedKnowledgeDocument)
                guard !selected.isEmpty else {
                    throw NativeMediaImportError.rejected("No knowledge document was selected")
                }
                self.uploadKnowledgeDocuments(
                    id: id,
                    kbId: kbId,
                    parserProvider: parserProvider,
                    files: Array(selected)
                )
            } catch {
                self.replyError(id: id, code: "knowledge_document_selection_rejected", message: error.localizedDescription)
            }
        }
    }

    private func validatedKnowledgeDocument(_ sourceURL: URL) throws -> SelectedKnowledgeDocument {
        let url = sourceURL.standardizedFileURL
        guard url.isFileURL else {
            throw NativeMediaImportError.rejected("Knowledge documents must be local files")
        }
        let values = try url.resourceValues(
            forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey, .contentTypeKey]
        )
        guard values.isRegularFile == true, values.isSymbolicLink != true else {
            throw NativeMediaImportError.rejected("Knowledge documents must be regular non-symlink files")
        }
        guard let byteSize = values.fileSize, byteSize > 0, byteSize <= 200 * 1024 * 1024 else {
            throw NativeMediaImportError.rejected("Knowledge documents must be non-empty and no larger than 200 MiB")
        }
        let name = url.lastPathComponent
        guard !name.isEmpty, name.utf8.count <= 512, !name.contains("\0") else {
            throw NativeMediaImportError.rejected("Knowledge document file name is invalid")
        }
        let mimeType = values.contentType?.preferredMIMEType?.lowercased() ?? "application/octet-stream"
        guard mimeType.utf8.count <= 160, !mimeType.contains("\r"), !mimeType.contains("\n") else {
            throw NativeMediaImportError.rejected("Knowledge document MIME type is invalid")
        }
        return SelectedKnowledgeDocument(url: url, name: name, mimeType: mimeType, byteSize: byteSize)
    }

    private func uploadKnowledgeDocuments(
        id: String,
        kbId: String,
        parserProvider: String,
        files: [SelectedKnowledgeDocument],
        index: Int = 0,
        receipts: [[String: Any]] = []
    ) {
        guard index < files.count else {
            requestTasks.removeValue(forKey: id)
            replySuccess(id: id, result: receipts)
            return
        }
        let file = files[index]
        guard let request = knowledgeDocumentImportRequest(
            kbId: kbId,
            parserProvider: parserProvider,
            selected: file
        ) else {
            replyError(id: id, code: "knowledge_document_import_rejected", message: "Knowledge import URL could not be constructed")
            return
        }
        let task = requestSession.uploadTask(with: request, fromFile: file.url) { [weak self] data, response, error in
            DispatchQueue.main.async {
                guard let self else { return }
                self.requestTasks.removeValue(forKey: id)
                do {
                    let receipt = try self.validatedKnowledgeDocumentResponse(
                        data: data,
                        response: response,
                        error: error,
                        kbId: kbId,
                        selected: file
                    )
                    self.uploadKnowledgeDocuments(
                        id: id,
                        kbId: kbId,
                        parserProvider: parserProvider,
                        files: files,
                        index: index + 1,
                        receipts: receipts + [receipt]
                    )
                } catch {
                    self.replyError(
                        id: id,
                        code: "knowledge_document_import_failed",
                        message: error.localizedDescription,
                        retryable: (error as NSError).code == NSURLErrorTimedOut
                    )
                }
            }
        }
        requestTasks[id] = task
        task.resume()
    }

    private func knowledgeDocumentImportRequest(
        kbId: String,
        parserProvider: String,
        selected: SelectedKnowledgeDocument
    ) -> URLRequest? {
        var components = URLComponents()
        components.scheme = "http"
        components.host = "127.0.0.1"
        components.port = 8766
        components.path = "/api/knowledge-bases/\(kbId)/documents/import"
        components.queryItems = [
            URLQueryItem(name: "fileName", value: selected.name),
            URLQueryItem(name: "mimeType", value: selected.mimeType),
            URLQueryItem(name: "parserProvider", value: parserProvider),
        ]
        guard let url = components.url,
              url.scheme == "http",
              url.host == "127.0.0.1",
              url.port == 8766 else {
            return nil
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(selected.mimeType, forHTTPHeaderField: "Content-Type")
        request.setValue(String(selected.byteSize), forHTTPHeaderField: "Content-Length")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        request.setValue(String(selected.byteSize), forHTTPHeaderField: "X-Rag-Ime-File-Size")
        return request
    }

    private func validatedKnowledgeDocumentResponse(
        data: Data?,
        response: URLResponse?,
        error: Error?,
        kbId: String,
        selected: SelectedKnowledgeDocument
    ) throws -> [String: Any] {
        if let error { throw error }
        guard let http = response as? HTTPURLResponse else {
            throw NativeMediaImportError.rejected("Knowledge document import returned no HTTP response")
        }
        guard let data, !data.isEmpty, data.count <= 1_048_576 else {
            throw NativeMediaImportError.rejected("Knowledge document import returned an invalid response size")
        }
        guard let decoded = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw NativeMediaImportError.rejected("Knowledge document import returned invalid JSON")
        }
        guard (200...299).contains(http.statusCode) else {
            let message = decoded["error"] as? String ?? "Knowledge document import returned HTTP \(http.statusCode)"
            throw NativeMediaImportError.rejected(message)
        }
        guard decoded["schemaVersion"] as? String == "rag-ime.knowledge-document-import.v1",
              decoded["ok"] as? Bool == true,
              let receipt = decoded["receipt"] as? [String: Any],
              receipt["kbId"] as? String == kbId,
              let documentId = receipt["documentId"] as? String,
              documentId.range(of: "^[A-Za-z0-9][A-Za-z0-9:._-]{0,159}$", options: .regularExpression) != nil,
              receipt["fileName"] as? String == selected.name,
              receipt["mimeType"] as? String == selected.mimeType,
              (receipt["byteSize"] as? NSNumber)?.intValue == selected.byteSize,
              let sha256 = receipt["sha256"] as? String,
              sha256.range(of: "^[a-f0-9]{64}$", options: .regularExpression) != nil,
              let status = receipt["status"] as? String,
              !status.isEmpty,
              status.utf8.count <= 64 else {
            throw NativeMediaImportError.rejected("Knowledge document import returned an invalid receipt")
        }
        return [
            "kbId": kbId,
            "documentId": documentId,
            "fileName": selected.name,
            "mimeType": selected.mimeType,
            "byteSize": selected.byteSize,
            "sha256": sha256,
            "status": status,
        ]
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
        return SelectedAgentImage(url: url, data: nil, name: name, mimeType: mimeType, byteSize: byteSize)
    }

    private func pastedAgentImages(maxFiles: Int) throws -> [SelectedAgentImage] {
        let pasteboard = NSPasteboard.general
        let fileURLs = pasteboard.readObjects(
            forClasses: [NSURL.self],
            options: [.urlReadingFileURLsOnly: true]
        ) as? [URL] ?? []
        if !fileURLs.isEmpty {
            return try fileURLs.prefix(maxFiles).map(validatedAgentImage)
        }

        var selected: [SelectedAgentImage] = []
        for (index, item) in (pasteboard.pasteboardItems ?? []).enumerated() {
            guard selected.count < maxFiles else { break }
            if let image = try pastedAgentImage(item, index: index) {
                selected.append(image)
            }
        }
        return selected
    }

    private func pastedAgentImage(_ item: NSPasteboardItem, index: Int) throws -> SelectedAgentImage? {
        let candidates = [
            (NSPasteboard.PasteboardType("public.png"), "image/png", "png"),
            (NSPasteboard.PasteboardType("public.jpeg"), "image/jpeg", "jpg"),
            (NSPasteboard.PasteboardType("com.compuserve.gif"), "image/gif", "gif"),
            (NSPasteboard.PasteboardType("org.webmproject.webp"), "image/webp", "webp"),
        ]
        for (type, mimeType, extensionName) in candidates {
            guard let data = item.data(forType: type) else { continue }
            return try validatedPastedImage(
                data: data,
                name: "pasted-image-\(index + 1).\(extensionName)",
                mimeType: mimeType
            )
        }
        guard let tiff = item.data(forType: .tiff),
              let bitmap = NSBitmapImageRep(data: tiff),
              let png = bitmap.representation(using: .png, properties: [:]) else {
            return nil
        }
        return try validatedPastedImage(
            data: png,
            name: "pasted-image-\(index + 1).png",
            mimeType: "image/png"
        )
    }

    private func validatedPastedImage(
        data: Data,
        name: String,
        mimeType: String
    ) throws -> SelectedAgentImage {
        guard !data.isEmpty, data.count <= 20 * 1024 * 1024 else {
            throw NativeMediaImportError.rejected("Pasted images must be non-empty and no larger than 20 MiB")
        }
        return SelectedAgentImage(
            url: nil,
            data: data,
            name: name,
            mimeType: mimeType,
            byteSize: data.count
        )
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
        guard let request = agentMediaImportRequest(sessionId: sessionId, selected: file) else {
            replyError(id: id, code: "agent_media_import_rejected", message: "Managed media import URL could not be constructed")
            return
        }
        let completion: (Data?, URLResponse?, Error?) -> Void = { [weak self] data, response, error in
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
        let task: URLSessionUploadTask
        if let fileURL = file.url {
            task = requestSession.uploadTask(with: request, fromFile: fileURL, completionHandler: completion)
        } else if let data = file.data {
            task = requestSession.uploadTask(with: request, from: data, completionHandler: completion)
        } else {
            replyError(id: id, code: "agent_media_import_rejected", message: "Managed media import data is unavailable")
            return
        }
        requestTasks[id] = task
        task.resume()
    }

    private func agentMediaImportRequest(
        sessionId: String,
        selected: SelectedAgentImage
    ) -> URLRequest? {
        var components = URLComponents()
        components.scheme = "http"
        components.host = "127.0.0.1"
        components.port = 8766
        components.path = "/api/agent/media/import"
        components.queryItems = [
            URLQueryItem(name: "sessionId", value: sessionId),
            URLQueryItem(name: "fileName", value: selected.name),
        ]
        guard let url = components.url,
              url.scheme == "http",
              url.host == "127.0.0.1",
              url.port == 8766 else {
            return nil
        }
        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue(selected.mimeType, forHTTPHeaderField: "Content-Type")
        request.setValue(String(selected.byteSize), forHTTPHeaderField: "Content-Length")
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        return request
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
            guard Set(payload.keys) == ["action", "receiptId", "payloadSha256", "commandSha256"] else {
                throw NativeRoutePolicyError.invalidParameter("externalAction")
            }
            let action = try requiredString("action", in: payload)
            let receiptId = try requiredString("receiptId", in: payload)
            let payloadHash = try normalizedSha256(try requiredString("payloadSha256", in: payload))
            let commandHash = try normalizedSha256(try requiredString("commandSha256", in: payload))
            guard approvedDiagnosticsExternalActions.contains(action) else {
                replyError(id: id, code: "external_action_not_allowed", message: "External action is not allowlisted")
                return
            }
            guard !externalActionReceiptsInFlight.contains(receiptId),
                  !completedExternalActionReceipts.contains(receiptId) else {
                replyError(id: id, code: "external_action_replayed", message: "External action receipt was already used")
                return
            }
            guard commandHash == expectedRuntimeActionCommandSha256(action) else {
                replyError(id: id, code: "approval_required", message: "External action requires approved payload and command hashes")
                return
            }
            let resolved = try routePolicy.resolveRequest(
                pathId: "diagnostics.action.job",
                parameters: ["jobId": receiptId],
                query: [:],
                body: nil
            )
            externalActionReceiptsInFlight.insert(receiptId)
            let task = requestSession.dataTask(with: resolved.request) { [weak self] data, response, error in
                DispatchQueue.main.async {
                    guard let self else { return }
                    self.requestTasks.removeValue(forKey: id)
                    do {
                        try self.validateApprovedExternalActionJob(
                            data: data,
                            response: response,
                            error: error,
                            action: action,
                            receiptId: receiptId,
                            payloadHash: payloadHash,
                            commandHash: commandHash
                        )
                        self.executeApprovedExternalAction(
                            id: id,
                            action: action,
                            receiptId: receiptId
                        )
                    } catch {
                        self.externalActionReceiptsInFlight.remove(receiptId)
                        self.replyError(
                            id: id,
                            code: "external_action_approval_rejected",
                            message: error.localizedDescription,
                            retryable: (error as NSError).code == NSURLErrorTimedOut
                        )
                    }
                }
            }
            requestTasks[id] = task
            task.resume()
        } catch {
            replyError(id: id, code: "invalid_external_action", message: error.localizedDescription)
        }
    }

    private var approvedDiagnosticsExternalActions: Set<String> {
        [
            "register_input_source",
            "restart_sidecar",
            "restart_predictor",
            "redeploy_rime",
            "open_accessibility_settings",
        ]
    }

    private func normalizedSha256(_ value: String) throws -> String {
        let digest = value.hasPrefix("sha256:") ? String(value.dropFirst(7)) : value
        guard digest.range(of: "^[a-fA-F0-9]{64}$", options: .regularExpression) != nil else {
            throw NativeRoutePolicyError.invalidParameter("sha256")
        }
        return digest.lowercased()
    }

    private func expectedRuntimeActionCommandSha256(_ action: String) -> String {
        SHA256.hash(data: Data("rag-ime.runtime-action.v1:\(action)".utf8))
            .map { String(format: "%02x", $0) }
            .joined()
    }

    private func validateApprovedExternalActionJob(
        data: Data?,
        response: URLResponse?,
        error: Error?,
        action: String,
        receiptId: String,
        payloadHash: String,
        commandHash: String
    ) throws {
        if let error { throw error }
        guard let http = response as? HTTPURLResponse,
              http.statusCode == 200,
              let data,
              data.count <= 1_048_576,
              let envelope = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              envelope["ok"] as? Bool == true,
              let job = envelope["job"] as? [String: Any],
              job["jobId"] as? String == receiptId,
              job["action"] as? String == action,
              job["status"] as? String == "external-supervisor-required",
              let result = job["result"] as? [String: Any],
              let external = result["externalAction"] as? [String: Any],
              external["receiptId"] as? String == receiptId,
              external["action"] as? String == action,
              let approvedPayloadHash = external["payloadSha256"] as? String,
              let approvedCommandHash = external["commandSha256"] as? String,
              try normalizedSha256(approvedPayloadHash) == payloadHash,
              try normalizedSha256(approvedCommandHash) == commandHash,
              commandHash == expectedRuntimeActionCommandSha256(action) else {
            throw NativeMediaImportError.rejected("The local service did not confirm the approved external action receipt")
        }
        let createdAtMs = (job["createdAtMs"] as? NSNumber)?.doubleValue ?? 0
        let nowMs = Date().timeIntervalSince1970 * 1_000
        guard createdAtMs > 0, createdAtMs <= nowMs + 60_000, nowMs - createdAtMs <= 600_000 else {
            throw NativeMediaImportError.rejected("The approved external action receipt has expired")
        }
    }

    private func executeApprovedExternalAction(id: String, action: String, receiptId: String) {
        if action == "open_accessibility_settings" {
            guard let settingsURL = URL(string: "x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility") else {
                finishApprovedExternalAction(
                    id: id,
                    action: action,
                    receiptId: receiptId,
                    exitCode: 1,
                    error: "Unable to open Accessibility settings"
                )
                return
            }
            let opened = NSWorkspace.shared.open(settingsURL)
            finishApprovedExternalAction(
                id: id,
                action: action,
                receiptId: receiptId,
                exitCode: opened ? 0 : 1,
                error: opened ? nil : "Unable to open Accessibility settings"
            )
            return
        }

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            guard let self else { return }
            do {
                let result = try self.runApprovedDiagnosticsProcess(action: action)
                DispatchQueue.main.async {
                    self.finishApprovedExternalAction(
                        id: id,
                        action: action,
                        receiptId: receiptId,
                        exitCode: result.exitCode,
                        error: result.error
                    )
                }
            } catch {
                DispatchQueue.main.async {
                    self.finishApprovedExternalAction(
                        id: id,
                        action: action,
                        receiptId: receiptId,
                        exitCode: 1,
                        error: error.localizedDescription
                    )
                }
            }
        }
    }

    private func finishApprovedExternalAction(
        id: String,
        action: String,
        receiptId: String,
        exitCode: Int32,
        error: String?
    ) {
        requestTasks.removeValue(forKey: id)
        externalActionReceiptsInFlight.remove(receiptId)
        if exitCode == 0 {
            completedExternalActionReceipts.insert(receiptId)
        }
        var result: [String: Any] = [
            "receiptId": receiptId,
            "action": action,
            "accepted": true,
            "completed": true,
            "exitCode": Int(exitCode),
        ]
        if let error, !error.isEmpty { result["error"] = error }
        replySuccess(id: id, result: result)
    }

    private func runApprovedDiagnosticsProcess(action: String) throws -> (exitCode: Int32, error: String?) {
        let executable: URL
        let arguments: [String]
        switch action {
        case "restart_sidecar":
            executable = URL(fileURLWithPath: "/bin/launchctl")
            arguments = ["kickstart", "-k", "gui/\(getuid())/com.rag-ime.sidecar"]
        case "restart_predictor":
            executable = URL(fileURLWithPath: "/bin/launchctl")
            arguments = ["kickstart", "-k", "gui/\(getuid())/com.rag-ime.mlx-predictor"]
        case "register_input_source":
            executable = URL(fileURLWithPath: "/bin/bash")
            arguments = [try trustedDiagnosticsHelper(named: "refresh_squirrel_input_source_registration.sh").path]
        case "redeploy_rime":
            executable = URL(fileURLWithPath: "/bin/bash")
            arguments = [try trustedDiagnosticsHelper(named: "install_squirrel_rag_config.sh").path]
        default:
            throw NativeMediaImportError.rejected("External action is not allowlisted")
        }

        let outputRoot = FileManager.default.temporaryDirectory
            .appendingPathComponent("rag-ime-diagnostics-\(UUID().uuidString)", isDirectory: true)
        try FileManager.default.createDirectory(at: outputRoot, withIntermediateDirectories: true)
        defer { try? FileManager.default.removeItem(at: outputRoot) }
        let stdoutURL = outputRoot.appendingPathComponent("stdout.log")
        let stderrURL = outputRoot.appendingPathComponent("stderr.log")
        FileManager.default.createFile(atPath: stdoutURL.path, contents: nil)
        FileManager.default.createFile(atPath: stderrURL.path, contents: nil)
        let stdoutHandle = try FileHandle(forWritingTo: stdoutURL)
        let stderrHandle = try FileHandle(forWritingTo: stderrURL)
        defer {
            try? stdoutHandle.close()
            try? stderrHandle.close()
        }

        let process = Process()
        process.executableURL = executable
        process.arguments = arguments
        process.standardOutput = stdoutHandle
        process.standardError = stderrHandle
        let completed = DispatchSemaphore(value: 0)
        process.terminationHandler = { _ in completed.signal() }
        try process.run()
        if completed.wait(timeout: .now() + 90) == .timedOut {
            process.terminate()
            _ = completed.wait(timeout: .now() + 2)
            return (124, "The approved external action timed out")
        }
        try? stdoutHandle.synchronize()
        try? stderrHandle.synchronize()
        let stderr = (try? String(contentsOf: stderrURL, encoding: .utf8)) ?? ""
        let stdout = (try? String(contentsOf: stdoutURL, encoding: .utf8)) ?? ""
        let detail = String((stderr.isEmpty ? stdout : stderr).suffix(1_000))
        return (process.terminationStatus, process.terminationStatus == 0 ? nil : (detail.isEmpty ? "External action failed" : detail))
    }

    private func trustedDiagnosticsHelper(named name: String) throws -> URL {
        let allowedNames = Set([
            "refresh_squirrel_input_source_registration.sh",
            "install_squirrel_rag_config.sh",
        ])
        guard allowedNames.contains(name) else {
            throw NativeMediaImportError.rejected("Diagnostics helper is not allowlisted")
        }
        var roots: [URL] = []
        let environment = ProcessInfo.processInfo.environment
        for key in ["RAG_IME_SOURCE_ROOT", "RAG_IME_REPO_ROOT"] {
            if let value = environment[key], !value.isEmpty {
                roots.append(URL(fileURLWithPath: value, isDirectory: true))
            }
        }
        roots.append(
            FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/Application Support/RagIme/app", isDirectory: true)
        )
        for label in ["com.rag-ime.sidecar", "com.rag-ime.mlx-predictor"] {
            let plistURL = FileManager.default.homeDirectoryForCurrentUser
                .appendingPathComponent("Library/LaunchAgents/\(label).plist")
            guard let data = try? Data(contentsOf: plistURL),
                  let plist = try? PropertyListSerialization.propertyList(from: data, format: nil),
                  let object = plist as? [String: Any],
                  let variables = object["EnvironmentVariables"] as? [String: Any],
                  let sourceRoot = variables["RAG_IME_SOURCE_ROOT"] as? String,
                  !sourceRoot.isEmpty else { continue }
            roots.append(URL(fileURLWithPath: sourceRoot, isDirectory: true))
        }

        for root in roots {
            let candidate = root.standardizedFileURL
                .appendingPathComponent("scripts", isDirectory: true)
                .appendingPathComponent(name)
            let resolved = candidate.resolvingSymlinksInPath().standardizedFileURL
            guard candidate.standardizedFileURL == resolved else { continue }
            var isDirectory: ObjCBool = false
            guard FileManager.default.fileExists(atPath: resolved.path, isDirectory: &isDirectory),
                  !isDirectory.boolValue,
                  let attributes = try? FileManager.default.attributesOfItem(atPath: resolved.path),
                  attributes[.type] as? FileAttributeType == .typeRegular else { continue }
            return resolved
        }
        throw NativeMediaImportError.rejected("The trusted diagnostics helper is not installed")
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

    private func voiceCredentialStatus(id: String, payload: [String: Any]) {
        do {
            guard Set(payload.keys) == ["provider"] else {
                throw NativeRoutePolicyError.invalidParameter("voiceCredentialStatus")
            }
            let provider = try voiceProvider(in: payload)
            replySuccess(
                id: id,
                result: [
                    "provider": provider.rawValue,
                    "configured": VoiceKeychainStore.hasCompleteKeychainCredentials(provider: provider),
                ]
            )
        } catch {
            replyError(id: id, code: "voice_credential_status_rejected", message: error.localizedDescription)
        }
    }

    private func voiceCredentialSave(id: String, payload: [String: Any]) {
        let allowedKeys: Set<String> = [
            "provider", "accessToken", "appId", "resourceId", "endpoint", "model", "headersJson",
        ]
        do {
            guard Set(payload.keys).isSubset(of: allowedKeys) else {
                throw NativeRoutePolicyError.invalidParameter("voiceCredentialSave")
            }
            let provider = try voiceProvider(in: payload)
            let accessToken = try optionalVoiceString("accessToken", in: payload, maximumBytes: 16_384)
            let appId = try optionalVoiceString("appId", in: payload, maximumBytes: 512) ?? ""
            let resourceId = try optionalVoiceString("resourceId", in: payload, maximumBytes: 512) ?? ""
            let endpoint = try optionalVoiceString("endpoint", in: payload, maximumBytes: 2_048) ?? ""
            let model = try optionalVoiceString("model", in: payload, maximumBytes: 512) ?? ""
            let headersJson = try optionalVoiceString("headersJson", in: payload, maximumBytes: 16_384) ?? ""
            try validateVoiceHeaders(headersJson)
            try VoiceKeychainStore.save(
                provider: provider,
                appID: appId,
                accessToken: accessToken?.isEmpty == false ? accessToken : nil,
                resourceID: resourceId,
                endpoint: endpoint,
                model: model,
                headersJSON: headersJson
            )
            DistributedNotificationCenter.default().post(
                name: Notification.Name("com.rag-ime.voice.configuration-changed"),
                object: nil
            )
            replySuccess(
                id: id,
                result: [
                    "provider": provider.rawValue,
                    "configured": VoiceKeychainStore.hasCompleteKeychainCredentials(provider: provider),
                ]
            )
        } catch {
            replyError(id: id, code: "voice_credential_save_failed", message: error.localizedDescription)
        }
    }

    private func voiceAction(id: String, payload: [String: Any]) {
        do {
            guard Set(payload.keys) == ["action"] else {
                throw NativeRoutePolicyError.invalidParameter("voiceAction")
            }
            let action = try requiredString("action", in: payload)
            switch action {
            case "start_agent":
                guard let url = NSWorkspace.shared.urlForApplication(withBundleIdentifier: "com.rag-ime.voice") else {
                    voiceActionReply(id: id, action: action, accepted: false, error: "语音代理尚未安装")
                    return
                }
                NSWorkspace.shared.openApplication(at: url, configuration: .init()) { [weak self] _, error in
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) {
                        self?.voiceActionReply(
                            id: id,
                            action: action,
                            accepted: error == nil,
                            error: error?.localizedDescription
                        )
                    }
                }
            case "stop_agent":
                let applications = NSRunningApplication.runningApplications(withBundleIdentifier: "com.rag-ime.voice")
                applications.forEach { _ = $0.terminate() }
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
                    self?.voiceActionReply(id: id, action: action, accepted: !applications.isEmpty)
                }
            case "reload_configuration":
                DistributedNotificationCenter.default().post(
                    name: Notification.Name("com.rag-ime.voice.configuration-changed"),
                    object: nil
                )
                voiceActionReply(id: id, action: action, accepted: true)
            case "request_microphone_permission":
                guard voiceAgentIsRunning else {
                    voiceActionReply(id: id, action: action, accepted: false, error: "请先启动语音代理")
                    return
                }
                DistributedNotificationCenter.default().post(
                    name: Notification.Name("com.rag-ime.voice.request-microphone-permission"),
                    object: nil
                )
                voiceActionReply(id: id, action: action, accepted: true)
            case "request_accessibility_permission":
                guard voiceAgentIsRunning else {
                    voiceActionReply(id: id, action: action, accepted: false, error: "请先启动语音代理")
                    return
                }
                DistributedNotificationCenter.default().post(
                    name: Notification.Name("com.rag-ime.voice.request-accessibility-permission"),
                    object: nil
                )
                let opened = openVoicePrivacySettings("Privacy_Accessibility")
                voiceActionReply(id: id, action: action, accepted: opened)
            case "open_microphone_settings":
                let opened = openVoicePrivacySettings("Privacy_Microphone")
                voiceActionReply(id: id, action: action, accepted: opened)
            case "open_accessibility_settings":
                let opened = openVoicePrivacySettings("Privacy_Accessibility")
                voiceActionReply(id: id, action: action, accepted: opened)
            default:
                replyError(id: id, code: "voice_action_not_allowed", message: "Voice action is not allowlisted")
            }
        } catch {
            replyError(id: id, code: "voice_action_rejected", message: error.localizedDescription)
        }
    }

    private func voiceProvider(in payload: [String: Any]) throws -> VoiceASRProvider {
        let rawValue = try requiredString("provider", in: payload)
        guard let provider = VoiceASRProvider(rawValue: rawValue) else {
            throw NativeRoutePolicyError.invalidParameter("provider")
        }
        return provider
    }

    private func optionalVoiceString(
        _ key: String,
        in payload: [String: Any],
        maximumBytes: Int
    ) throws -> String? {
        guard let value = payload[key] else { return nil }
        guard let string = value as? String,
              string.utf8.count <= maximumBytes,
              !string.contains("\0") else {
            throw NativeRoutePolicyError.invalidParameter(key)
        }
        return string.trimmingCharacters(in: .whitespacesAndNewlines)
    }

    private func validateVoiceHeaders(_ rawValue: String) throws {
        guard !rawValue.isEmpty else { return }
        guard let data = rawValue.data(using: .utf8),
              let value = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              value.count <= 32,
              value.allSatisfy({ item in
                  !item.key.isEmpty && item.key.utf8.count <= 256 && item.value is String
              }) else {
            throw NativeRoutePolicyError.invalidParameter("headersJson")
        }
    }

    private var voiceAgentIsRunning: Bool {
        !NSRunningApplication.runningApplications(withBundleIdentifier: "com.rag-ime.voice").isEmpty
    }

    private func voiceNativeStatus() -> [String: Any] {
        let running = voiceAgentIsRunning
        let status = running ? VoiceAgentStatusStore.read() : nil
        return [
            "running": running,
            "state": status?.state ?? (running ? "starting" : "stopped"),
            "statusText": status?.statusText ?? (running ? "语音代理正在启动" : "语音代理未运行"),
            "microphoneAuthorization": status?.microphoneAuthorization ?? "unknown",
            "accessibilityTrusted": status?.accessibilityTrusted ?? false,
            "hotkeyInstalled": status?.hotkeyInstalled ?? false,
            "hotkeyMode": status?.hotkeyMode ?? "",
            "updatedAtMs": status?.updatedAtMs ?? 0,
        ]
    }

    private func voiceActionReply(id: String, action: String, accepted: Bool, error: String? = nil) {
        var result: [String: Any] = [
            "action": action,
            "accepted": accepted,
            "status": voiceNativeStatus(),
        ]
        if let error, !error.isEmpty { result["error"] = error }
        replySuccess(id: id, result: result)
    }

    private func openVoicePrivacySettings(_ pane: String) -> Bool {
        guard Set(["Privacy_Microphone", "Privacy_Accessibility"]).contains(pane),
              let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") else {
            return false
        }
        return NSWorkspace.shared.open(url)
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
