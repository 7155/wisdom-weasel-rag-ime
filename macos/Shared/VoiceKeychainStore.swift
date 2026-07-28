import Foundation
import Security

enum VoiceASRProvider: String, Codable, CaseIterable, Identifiable {
    case nativeStreaming = "native_streaming"
    case realtimeWebSocket = "realtime_websocket"
    case httpTranscription = "http_transcription"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .nativeStreaming: return "流式 ASR"
        case .realtimeWebSocket: return "Realtime 兼容 API"
        case .httpTranscription: return "HTTP 转写 API"
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
    let headersJSON: String

    init(
        provider: VoiceASRProvider = .nativeStreaming,
        appID: String,
        accessToken: String,
        resourceID: String,
        endpoint: String = "",
        model: String = "",
        headersJSON: String = ""
    ) {
        self.provider = provider
        self.appID = appID
        self.accessToken = accessToken
        self.resourceID = resourceID
        self.endpoint = endpoint
        self.model = model
        self.headersJSON = headersJSON
    }

    var isComplete: Bool {
        let tokenReady = !accessToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        guard headersAreValid else { return false }
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
        case .httpTranscription:
            guard tokenReady,
                  let url = URL(string: endpoint),
                  ["https", "http"].contains(url.scheme?.lowercased() ?? "") else { return false }
            return !model.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
        }
    }

    var extraHeaders: [String: String] {
        guard let data = headersJSON.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return [:] }
        return object.reduce(into: [:]) { result, item in
            let key = item.key.trimmingCharacters(in: .whitespacesAndNewlines)
            let value = String(describing: item.value).trimmingCharacters(in: .whitespacesAndNewlines)
            if !key.isEmpty, !value.isEmpty { result[key] = value }
        }
    }

    private var headersAreValid: Bool {
        let raw = headersJSON.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return true }
        guard let data = raw.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) else { return false }
        return object is [String: Any]
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

enum VoiceCredentialMetadataStore {
    private struct Payload: Codable {
        static let schemaVersion = "rag-ime.voice-credential-metadata.v1"
        let schemaVersion: String
        let configuredProviders: [VoiceASRProvider]
    }

    static var configURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
            .appendingPathComponent("voice-credential-status.json")
    }

    static func isConfigured(_ provider: VoiceASRProvider) -> Bool {
        configuredProviders().contains(provider)
    }

    static func markConfigured(_ provider: VoiceASRProvider) throws {
        var providers = configuredProviders()
        providers.insert(provider)
        let directory = configURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let payload = Payload(
            schemaVersion: Payload.schemaVersion,
            configuredProviders: providers.sorted { $0.rawValue < $1.rawValue }
        )
        let data = try JSONEncoder().encode(payload)
        try data.write(to: configURL, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: configURL.path)
    }

    private static func configuredProviders() -> Set<VoiceASRProvider> {
        guard let data = try? Data(contentsOf: configURL),
              let payload = try? JSONDecoder().decode(Payload.self, from: data),
              payload.schemaVersion == Payload.schemaVersion else { return [] }
        return Set(payload.configuredProviders)
    }
}

enum VoiceKeychainStore {
    // Keep the original service identifier so existing locally stored credentials continue to work.
    static let service = "com.rag-ime.voice.volcengine"
    static let defaultResourceID = "volc.seedasr.sauc.duration"
    static let defaultRealtimeEndpoint = "wss://api.openai.com/v1/realtime?intent=transcription"
    static let defaultRealtimeModel = "gpt-4o-mini-transcribe"
    static let defaultHTTPEndpoint = "https://api.openai.com/v1/audio/transcriptions"

    private enum Account: String {
        case credentialBundle = "credentials-v1"
        case appID = "app-id"
        case accessToken = "access-token"
        case resourceID = "resource-id"
        case endpoint
        case model
        case headersJSON = "headers-json"
    }

    static func loadCredentials(allowLegacyFallback: Bool = false) -> VoiceASRCredentials? {
        loadCredentials(
            provider: VoiceProviderConfigStore.read(),
            allowLegacyFallback: allowLegacyFallback
        )
    }

    static func loadCredentials(
        provider: VoiceASRProvider,
        allowLegacyFallback: Bool = false
    ) -> VoiceASRCredentials? {
        if let local = VoiceCredentialFileStore.loadCredentials(provider: provider) {
            try? VoiceCredentialMetadataStore.markConfigured(provider)
            return local
        }
        if let bundled = readCredentialBundle(provider: provider), bundled.isComplete {
            try? VoiceCredentialMetadataStore.markConfigured(provider)
            return bundled
        }
        // The old layout stored six independent Keychain items and can trigger
        // one authorization prompt per item after a development rebuild. Only
        // an explicitly opted-in runtime migration may inspect that layout.
        guard allowLegacyFallback,
              let credentials = readLegacyCredentials(provider: provider) else { return nil }
        // Collapse a successfully authorized legacy read into the one-item
        // bundle so every subsequent runtime access has one Keychain boundary.
        try? writeCredentialBundle(credentials)
        try? VoiceCredentialMetadataStore.markConfigured(provider)
        return credentials
    }

    private static func readLegacyCredentials(provider: VoiceASRProvider) -> VoiceASRCredentials? {
        guard let accessToken = read(.accessToken, provider: provider) else { return nil }
        let credentials = VoiceASRCredentials(
            provider: provider,
            appID: read(.appID, provider: provider) ?? "",
            accessToken: accessToken,
            resourceID: read(.resourceID, provider: provider) ?? defaultResourceID,
            endpoint: read(.endpoint, provider: provider) ?? defaultRealtimeEndpoint,
            model: read(.model, provider: provider) ?? defaultRealtimeModel,
            headersJSON: read(.headersJSON, provider: provider) ?? ""
        )
        guard credentials.isComplete else { return nil }
        return credentials
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
        model: String,
        headersJSON: String = ""
    ) throws {
        let token = accessToken?.trimmingCharacters(in: .whitespacesAndNewlines)
        // Supplying a new token must not read old Keychain items first. This
        // keeps an explicit save to a single Keychain authorization boundary.
        // An empty token may reuse the current one-item bundle, but saving never
        // scans legacy items. Users with only the old layout re-enter the token
        // once, after which all fields live in a single Keychain record.
        let previous = token?.isEmpty == false
            ? nil
            : loadCredentials(provider: provider, allowLegacyFallback: false)
        let credentials = VoiceASRCredentials(
            provider: provider,
            appID: appID.trimmingCharacters(in: .whitespacesAndNewlines),
            accessToken: token?.isEmpty == false ? token! : (previous?.accessToken ?? ""),
            resourceID: resourceID.trimmingCharacters(in: .whitespacesAndNewlines),
            endpoint: endpoint.trimmingCharacters(in: .whitespacesAndNewlines),
            model: model.trimmingCharacters(in: .whitespacesAndNewlines),
            headersJSON: headersJSON.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        guard credentials.isComplete else { throw VoiceKeychainError.invalidValue }
        try writeCredentialBundle(credentials)
        try VoiceProviderConfigStore.write(provider)
        try VoiceCredentialMetadataStore.markConfigured(provider)
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
        model: String,
        headersJSON: String = ""
    ) throws {
        let previous = VoiceCredentialFileStore.loadCredentials(provider: provider)
        let token = accessToken?.trimmingCharacters(in: .whitespacesAndNewlines)
        let credentials = VoiceASRCredentials(
            provider: provider,
            appID: appID.trimmingCharacters(in: .whitespacesAndNewlines),
            accessToken: token?.isEmpty == false ? token! : (previous?.accessToken ?? ""),
            resourceID: resourceID.trimmingCharacters(in: .whitespacesAndNewlines),
            endpoint: endpoint.trimmingCharacters(in: .whitespacesAndNewlines),
            model: model.trimmingCharacters(in: .whitespacesAndNewlines),
            headersJSON: headersJSON.trimmingCharacters(in: .whitespacesAndNewlines)
        )
        guard credentials.isComplete else { throw VoiceKeychainError.invalidValue }
        try VoiceCredentialFileStore.save(credentials)
        try VoiceProviderConfigStore.write(provider)
        try VoiceCredentialMetadataStore.markConfigured(provider)
    }

    static var hasAccessToken: Bool { hasAccessToken(provider: VoiceProviderConfigStore.read()) }

    static func hasAccessToken(provider: VoiceASRProvider) -> Bool {
        if VoiceCredentialFileStore.loadCredentials(provider: provider)?.isComplete == true { return true }
        return readCredentialBundle(provider: provider)?.isComplete == true
    }

    static func hasKeychainAccessToken(provider: VoiceASRProvider) -> Bool {
        readCredentialBundle(provider: provider)?.isComplete == true
    }

    static func hasConfiguredCredentialMetadata(provider: VoiceASRProvider) -> Bool {
        // Ordinary control-center rendering must never touch Keychain. macOS can
        // ask for one password per legacy item after a development rebuild, so a
        // non-secret 0600 receipt records only whether an explicit save or a real
        // voice-runtime load completed successfully.
        return VoiceCredentialFileStore.loadCredentials(provider: provider)?.isComplete == true
            || VoiceCredentialMetadataStore.isConfigured(provider)
    }

    private static func service(for provider: VoiceASRProvider) -> String {
        provider == .nativeStreaming ? service : "com.rag-ime.voice.\(provider.rawValue)"
    }

    private static func read(_ account: Account, provider: VoiceASRProvider) -> String? {
        guard let data = readData(account, provider: provider) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func readData(_ account: Account, provider: VoiceASRProvider) -> Data? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: provider),
            kSecAttrAccount as String: account.rawValue,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess else { return nil }
        return result as? Data
    }

    private static func writeData(_ data: Data, account: Account, provider: VoiceASRProvider) throws {
        let identity: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service(for: provider),
            kSecAttrAccount as String: account.rawValue,
        ]
        let attributes: [String: Any] = [
            kSecValueData as String: data,
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

    private static func readCredentialBundle(provider: VoiceASRProvider) -> VoiceASRCredentials? {
        guard let data = readData(.credentialBundle, provider: provider),
              let credentials = try? JSONDecoder().decode(VoiceASRCredentials.self, from: data),
              credentials.provider == provider else { return nil }
        return credentials
    }

    private static func writeCredentialBundle(_ credentials: VoiceASRCredentials) throws {
        try writeData(try JSONEncoder().encode(credentials), account: .credentialBundle, provider: credentials.provider)
    }
}

enum VoiceCredentialFileStore {
    private struct Payload: Codable {
        static let schemaVersion = "rag-ime.voice-credentials.v3"
        let schemaVersion: String
        let provider: VoiceASRProvider?
        let appID: String
        let accessToken: String
        let resourceID: String
        let endpoint: String?
        let model: String?
        let headersJSON: String?
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
            model: object["model"] as? String ?? VoiceKeychainStore.defaultRealtimeModel,
            headersJSON: object["headersJSON"] as? String ?? ""
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
            model: credentials.model,
            headersJSON: credentials.headersJSON
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
