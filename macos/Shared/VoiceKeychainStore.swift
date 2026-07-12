import Foundation
import Security

enum VoiceASRProvider: String, Codable, CaseIterable, Identifiable {
    case nativeStreaming = "native_streaming"
    case realtimeWebSocket = "realtime_websocket"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .nativeStreaming: return "默认流式服务"
        case .realtimeWebSocket: return "Realtime WebSocket 兼容服务"
        }
    }

    var supportsHotwords: Bool { self == .nativeStreaming }
}

struct VoiceASRCredentials: Codable, Equatable {
    let provider: VoiceASRProvider
    let appID: String
    let accessToken: String
    let resourceID: String
    let endpoint: String
    let model: String

    init(
        provider: VoiceASRProvider = .nativeStreaming,
        appID: String,
        accessToken: String,
        resourceID: String,
        endpoint: String = "",
        model: String = ""
    ) {
        self.provider = provider
        self.appID = appID
        self.accessToken = accessToken
        self.resourceID = resourceID
        self.endpoint = endpoint
        self.model = model
    }

    var isComplete: Bool {
        let tokenReady = !accessToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        switch provider {
        case .nativeStreaming:
            return tokenReady
                && !appID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                && !resourceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        case .realtimeWebSocket:
            guard tokenReady,
                  let url = URL(string: endpoint),
                  ["wss", "ws"].contains(url.scheme?.lowercased() ?? "") else { return false }
            return !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }
}

enum VoiceProviderConfigStore {
    private struct Payload: Codable {
        static let schemaVersion = "rag-ime.voice-provider.v1"
        let schemaVersion: String
        let provider: VoiceASRProvider
    }

    static var configURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
            .appendingPathComponent("voice-provider.json")
    }

    static func read() -> VoiceASRProvider {
        guard let data = try? Data(contentsOf: configURL),
              let payload = try? JSONDecoder().decode(Payload.self, from: data),
              payload.schemaVersion == Payload.schemaVersion else { return .nativeStreaming }
        return payload.provider
    }

    static func write(_ provider: VoiceASRProvider) throws {
        let directory = configURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = try JSONEncoder().encode(Payload(schemaVersion: Payload.schemaVersion, provider: provider))
        try data.write(to: configURL, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: configURL.path)
    }
}

enum VoiceKeychainStore {
    // Keep the original service identifier so existing locally stored credentials continue to work.
    static let service = "com.rag-ime.voice.volcengine"
    static let defaultResourceID = "volc.seedasr.sauc.duration"
    static let defaultRealtimeEndpoint = "wss://api.openai.com/v1/realtime?intent=transcription"
    static let defaultRealtimeModel = "gpt-4o-mini-transcribe"

    private enum Account: String {
        case appID = "app-id"
        case accessToken = "access-token"
        case resourceID = "resource-id"
        case endpoint
        case model
    }

    static func loadCredentials() -> VoiceASRCredentials? {
        loadCredentials(provider: VoiceProviderConfigStore.read())
    }

    static func loadCredentials(provider: VoiceASRProvider) -> VoiceASRCredentials? {
        if let local = VoiceCredentialFileStore.loadCredentials(provider: provider) { return local }
        guard let accessToken = read(.accessToken, provider: provider) else { return nil }
        let credentials = VoiceASRCredentials(
            provider: provider,
            appID: read(.appID, provider: provider) ?? "",
            accessToken: accessToken,
            resourceID: read(.resourceID, provider: provider) ?? defaultResourceID,
            endpoint: read(.endpoint, provider: provider) ?? defaultRealtimeEndpoint,
            model: read(.model, provider: provider) ?? defaultRealtimeModel
        )
        return credentials.isComplete ? credentials : nil
    }

    static func save(appID: String, accessToken: String?, resourceID: String) throws {
        try save(
            provider: .nativeStreaming,
            appID: appID,
            accessToken: accessToken,
            resourceID: resourceID,
            endpoint: "",
            model: ""
        )
    }

    static func save(
        provider: VoiceASRProvider,
        appID: String,
        accessToken: String?,
        resourceID: String,
        endpoint: String,
        model: String
    ) throws {
        let previous = loadCredentials(provider: provider)
        let token = accessToken?.trimmingCharacters(in: .whitespacesAndNewlines)
        let credentials = VoiceASRCredentials(
            provider: provider,
            appID: appID.trimmingCharacters(in: .whitespacesAndNewlines),
            accessToken: token?.isEmpty == false ? token! : (previous?.accessToken ?? ""),
            resourceID: resourceID.trimmingCharacters(in: .whitespacesAndNewlines),
            endpoint: endpoint.trimmingCharacters(in: .whitespacesAndNewlines),
            model: model.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        guard credentials.isComplete else { throw VoiceKeychainError.invalidValue }
        try write(credentials.appID, account: .appID, provider: provider)
        try write(credentials.resourceID, account: .resourceID, provider: provider)
        try write(credentials.endpoint, account: .endpoint, provider: provider)
        try write(credentials.model, account: .model, provider: provider)
        try write(credentials.accessToken, account: .accessToken, provider: provider)
        try VoiceProviderConfigStore.write(provider)
    }

    static func saveLocal(appID: String, accessToken: String?, resourceID: String) throws {
        try saveLocal(
            provider: .nativeStreaming,
            appID: appID,
            accessToken: accessToken,
            resourceID: resourceID,
            endpoint: "",
            model: ""
        )
    }

    static func saveLocal(
        provider: VoiceASRProvider,
        appID: String,
        accessToken: String?,
        resourceID: String,
        endpoint: String,
        model: String
    ) throws {
        let previous = VoiceCredentialFileStore.loadCredentials(provider: provider)
        let token = accessToken?.trimmingCharacters(in: .whitespacesAndNewlines)
        let credentials = VoiceASRCredentials(
            provider: provider,
            appID: appID.trimmingCharacters(in: .whitespacesAndNewlines),
            accessToken: token?.isEmpty == false ? token! : (previous?.accessToken ?? ""),
            resourceID: resourceID.trimmingCharacters(in: .whitespacesAndNewlines),
            endpoint: endpoint.trimmingCharacters(in: .whitespacesAndNewlines),
            model: model.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        guard credentials.isComplete else { throw VoiceKeychainError.invalidValue }
        try VoiceCredentialFileStore.save(credentials)
        try VoiceProviderConfigStore.write(provider)
    }

    static var hasAccessToken: Bool { hasAccessToken(provider: VoiceProviderConfigStore.read()) }

    static func hasAccessToken(provider: VoiceASRProvider) -> Bool {
        if VoiceCredentialFileStore.loadCredentials(provider: provider)?.isComplete == true { return true }
        return !(read(.accessToken, provider: provider) ?? "").isEmpty
    }

    private static func service(for provider: VoiceASRProvider) -> String {
        provider == .nativeStreaming ? service : "com.rag-ime.voice.\(provider.rawValue)"
    }

    private static func read(_ account: Account, provider: VoiceASRProvider) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: provider),
            kSecAttrAccount as String: account.rawValue,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func write(_ value: String, account: Account, provider: VoiceASRProvider) throws {
        let identity: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: provider),
            kSecAttrAccount as String: account.rawValue,
        ]
        let attributes: [String: Any] = [
            kSecValueData as String: Data(value.utf8),
            kSecAttrAccessible as String: kSecAttrAccessibleAfterFirstUnlock,
        ]
        let status = SecItemUpdate(identity as CFDictionary, attributes as CFDictionary)
        if status == errSecItemNotFound {
            var item = identity
            attributes.forEach { item[$0.key] = $0.value }
            let addStatus = SecItemAdd(item as CFDictionary, nil)
            guard addStatus == errSecSuccess else { throw VoiceKeychainError.osStatus(addStatus) }
            return
        }
        guard status == errSecSuccess else { throw VoiceKeychainError.osStatus(status) }
    }
}

enum VoiceCredentialFileStore {
    private struct Payload: Codable {
        static let schemaVersion = "rag-ime.voice-credentials.v2"
        let schemaVersion: String
        let provider: VoiceASRProvider?
        let appID: String
        let accessToken: String
        let resourceID: String
        let endpoint: String?
        let model: String?
    }

    static var configURL: URL { configURL(provider: .nativeStreaming) }

    static func configURL(provider: VoiceASRProvider) -> URL {
        let name = provider == .nativeStreaming ? "voice-credentials.json" : "voice-credentials-\(provider.rawValue).json"
        return FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
            .appendingPathComponent(name)
    }

    static func loadCredentials() -> VoiceASRCredentials? {
        loadCredentials(provider: VoiceProviderConfigStore.read())
    }

    static func loadCredentials(provider: VoiceASRProvider) -> VoiceASRCredentials? {
        guard let data = try? Data(contentsOf: configURL(provider: provider)),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        let storedProvider = VoiceASRProvider(rawValue: object["provider"] as? String ?? "") ?? provider
        guard storedProvider == provider else { return nil }
        let credentials = VoiceASRCredentials(
            provider: provider,
            appID: object["appID"] as? String ?? "",
            accessToken: object["accessToken"] as? String ?? "",
            resourceID: object["resourceID"] as? String ?? VoiceKeychainStore.defaultResourceID,
            endpoint: object["endpoint"] as? String ?? VoiceKeychainStore.defaultRealtimeEndpoint,
            model: object["model"] as? String ?? VoiceKeychainStore.defaultRealtimeModel
        )
        return credentials.isComplete ? credentials : nil
    }

    static func save(_ credentials: VoiceASRCredentials) throws {
        guard credentials.isComplete else { throw VoiceKeychainError.invalidValue }
        let url = configURL(provider: credentials.provider)
        let directory = url.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let payload = Payload(
            schemaVersion: Payload.schemaVersion,
            provider: credentials.provider,
            appID: credentials.appID,
            accessToken: credentials.accessToken,
            resourceID: credentials.resourceID,
            endpoint: credentials.endpoint,
            model: credentials.model
        )
        let data = try JSONEncoder().encode(payload)
        try data.write(to: url, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }
}

enum VoiceKeychainError: LocalizedError {
    case invalidValue
    case osStatus(OSStatus)

    var errorDescription: String? {
        switch self {
        case .invalidValue: return "请完整填写当前语音服务需要的凭据与端点"
        case .osStatus(let status): return "Keychain 写入失败（\(status)）"
        }
    }
}
