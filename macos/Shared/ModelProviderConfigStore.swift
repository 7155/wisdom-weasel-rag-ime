import Foundation
import Security

enum InstantCompletionProvider: String, CaseIterable, Identifiable {
    case mlx
    case ollama
    case openAICompatible = "openai-compatible"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .mlx: return "内置 / MLX"
        case .ollama: return "Ollama"
        case .openAICompatible: return "兼容 API"
        }
    }
}

enum KnowledgeProviderPreset: String, CaseIterable, Identifiable {
    case defaultRemote = "deepseek"
    case openAICompatible = "openai-compatible"

    var id: String { rawValue }
    var title: String {
        switch self {
        case .defaultRemote: return "默认远程服务"
        case .openAICompatible: return "兼容 API"
        }
    }
}

struct InstantCompletionSlot {
    var provider: InstantCompletionProvider
    var endpoint: String
    var model: String
    var apiKey: String
    var headersJSON: String
}

struct KnowledgeProviderSlot {
    var provider: KnowledgeProviderPreset
    var endpoint: String
    var model: String
    var apiKey: String
    var headersJSON: String
}

enum ModelProviderConfigStore {
    private static let keychainService = "com.rag-ime.model-provider"
    private static let instantKeyAccount = "instant-api-key"
    private static let knowledgeKeyAccount = "knowledge-api-key"
    private static var supportDirectory: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
    }

    static var instantURL: URL { supportDirectory.appendingPathComponent("predictor.env") }
    static var knowledgeURL: URL { supportDirectory.appendingPathComponent("deepseek.env") }

    static func loadInstant() -> InstantCompletionSlot {
        let values = readEnv(instantURL)
        let provider = InstantCompletionProvider(rawValue: values["RAG_IME_PREDICTOR_PROVIDER"] ?? "") ?? .mlx
        return InstantCompletionSlot(
            provider: provider,
            endpoint: values["RAG_IME_PREDICTOR_BASE_URL"] ?? "http://127.0.0.1:8767",
            model: values["RAG_IME_PREDICTOR_MODEL"] ?? "",
            apiKey: readSecret(account: instantKeyAccount) ?? values["RAG_IME_PREDICTOR_API_KEY"] ?? "",
            headersJSON: values["RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON"] ?? ""
        )
    }

    static func loadKnowledge() -> KnowledgeProviderSlot {
        let values = readEnv(knowledgeURL)
        let provider = KnowledgeProviderPreset(rawValue: values["RAG_IME_KNOWLEDGE_PROVIDER"] ?? "") ?? .defaultRemote
        return KnowledgeProviderSlot(
            provider: provider,
            endpoint: values["RAG_IME_DEEPSEEK_BASE_URL"] ?? "https://api.deepseek.com",
            model: values["RAG_IME_DEEPSEEK_MODEL"] ?? "deepseek-v4-flash",
            apiKey: readSecret(account: knowledgeKeyAccount) ?? values["RAG_IME_DEEPSEEK_API_KEY"] ?? values["DEEPSEEK_API_KEY"] ?? "",
            headersJSON: values["RAG_IME_KNOWLEDGE_EXTRA_HEADERS_JSON"] ?? ""
        )
    }

    static func saveInstant(_ slot: InstantCompletionSlot, preservingKey: Bool = true) throws {
        let previous = loadInstant()
        try validateInstant(slot)
        let key = preservingKey && slot.apiKey.isEmpty ? previous.apiKey : slot.apiKey
        if !key.isEmpty { try writeSecret(key, account: instantKeyAccount) }
        try writeEnv([
            "RAG_IME_PREDICTOR_PROVIDER": slot.provider.rawValue,
            "RAG_IME_PREDICTOR_BASE_URL": slot.endpoint,
            "RAG_IME_PREDICTOR_MODEL": slot.model,
            "RAG_IME_PREDICTOR_EXTRA_HEADERS_JSON": compactJSON(slot.headersJSON),
        ], to: instantURL)
    }

    static func saveKnowledge(_ slot: KnowledgeProviderSlot, preservingKey: Bool = true) throws {
        let previous = loadKnowledge()
        try validateKnowledge(slot)
        let key = preservingKey && slot.apiKey.isEmpty ? previous.apiKey : slot.apiKey
        if !key.isEmpty { try writeSecret(key, account: knowledgeKeyAccount) }
        try writeEnv([
            "RAG_IME_KNOWLEDGE_PROVIDER": slot.provider.rawValue,
            "RAG_IME_DEEPSEEK_BASE_URL": slot.endpoint,
            "RAG_IME_DEEPSEEK_MODEL": slot.model,
            "RAG_IME_KNOWLEDGE_EXTRA_HEADERS_JSON": compactJSON(slot.headersJSON),
            "RAG_IME_DEEPSEEK_ACTIVE_RAG": "1",
        ], to: knowledgeURL)
    }

    static func validateInstant(_ slot: InstantCompletionSlot) throws {
        try validateURL(slot.endpoint, allowedSchemes: ["http", "https"])
        try validateHeaders(slot.headersJSON)
    }

    static func validateKnowledge(_ slot: KnowledgeProviderSlot) throws {
        try validateURL(slot.endpoint, allowedSchemes: ["http", "https"])
        try validateHeaders(slot.headersJSON)
    }

    private static func readEnv(_ url: URL) -> [String: String] {
        guard let text = try? String(contentsOf: url, encoding: .utf8) else { return [:] }
        return text.split(whereSeparator: \.isNewline).reduce(into: [:]) { result, rawLine in
            let line = rawLine.trimmingCharacters(in: .whitespacesAndNewlines)
            guard !line.isEmpty, !line.hasPrefix("#"), let separator = line.firstIndex(of: "=") else { return }
            let key = String(line[..<separator]).trimmingCharacters(in: .whitespacesAndNewlines)
            let value = String(line[line.index(after: separator)...]).trimmingCharacters(in: .whitespacesAndNewlines)
            result[key] = value.trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
        }
    }

    private static func readSecret(account: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: account,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }

    private static func writeSecret(_ value: String, account: String) throws {
        let identity: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: keychainService,
            kSecAttrAccount as String: account,
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
            guard addStatus == errSecSuccess else { throw ModelProviderConfigError.keychain(addStatus) }
            return
        }
        guard status == errSecSuccess else { throw ModelProviderConfigError.keychain(status) }
    }

    private static func writeEnv(_ values: [String: String], to url: URL) throws {
        try FileManager.default.createDirectory(at: supportDirectory, withIntermediateDirectories: true)
        let text = values.keys.sorted().map { key in
            "\(key)=\(sanitize(values[key] ?? ""))"
        }.joined(separator: "\n") + "\n"
        try text.write(to: url, atomically: true, encoding: .utf8)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: url.path)
    }

    private static func sanitize(_ value: String) -> String {
        value.replacingOccurrences(of: "\r", with: " ").replacingOccurrences(of: "\n", with: " ").trimmingCharacters(in: .whitespaces)
    }

    private static func validateURL(_ value: String, allowedSchemes: Set<String>) throws {
        guard let url = URL(string: value.trimmingCharacters(in: .whitespacesAndNewlines)),
              let scheme = url.scheme?.lowercased(), allowedSchemes.contains(scheme), url.host != nil else {
            throw ModelProviderConfigError.invalidURL
        }
    }

    private static func validateHeaders(_ value: String) throws {
        let raw = value.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !raw.isEmpty else { return }
        guard let data = raw.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data), object is [String: Any] else {
            throw ModelProviderConfigError.invalidHeaders
        }
    }

    private static func compactJSON(_ value: String) -> String {
        guard let data = value.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data),
              let compact = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: compact, encoding: .utf8) else { return "" }
        return text
    }
}

enum ModelProviderConfigError: LocalizedError {
    case invalidURL
    case invalidHeaders
    case keychain(OSStatus)

    var errorDescription: String? {
        switch self {
        case .invalidURL: return "请输入完整的 HTTP 或 HTTPS 地址"
        case .invalidHeaders: return "请求头必须是 JSON 对象"
        case .keychain(let status): return "Keychain 写入失败（\(status)）"
        }
    }
}
