import Foundation
import Security

struct VoiceASRCredentials: Equatable {
    let appID: String
    let accessToken: String
    let resourceID: String

    var isComplete: Bool {
        !appID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !accessToken.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !resourceID.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }
}

enum VoiceKeychainStore {
    static let service = "com.rag-ime.voice.volcengine"
    static let defaultResourceID = "volc.seedasr.sauc.duration"

    private enum Account: String {
        case appID = "app-id"
        case accessToken = "access-token"
        case resourceID = "resource-id"
    }

    static func loadCredentials() -> VoiceASRCredentials? {
        guard let appID = read(.appID), let accessToken = read(.accessToken) else {
            return nil
        }
        return VoiceASRCredentials(
            appID: appID,
            accessToken: accessToken,
            resourceID: read(.resourceID) ?? defaultResourceID
        )
    }

    static func save(appID: String, accessToken: String?, resourceID: String) throws {
        let trimmedAppID = appID.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedResourceID = resourceID.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedAppID.isEmpty, !trimmedResourceID.isEmpty else {
            throw VoiceKeychainError.invalidValue
        }
        try write(trimmedAppID, account: .appID)
        try write(trimmedResourceID, account: .resourceID)
        if let accessToken {
            let trimmedToken = accessToken.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmedToken.isEmpty {
                try write(trimmedToken, account: .accessToken)
            }
        }
    }

    static var hasAccessToken: Bool {
        guard let token = read(.accessToken) else { return false }
        return !token.isEmpty
    }

    private static func read(_ account: Account) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
            kSecAttrAccount as String: account.rawValue,
            kSecReturnData as String: true,
            kSecMatchLimit as String: kSecMatchLimitOne,
        ]
        var result: CFTypeRef?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else {
            return nil
        }
        return String(data: data, encoding: .utf8)
    }

    private static func write(_ value: String, account: Account) throws {
        let identity: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrService as String: service,
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

enum VoiceKeychainError: LocalizedError {
    case invalidValue
    case osStatus(OSStatus)

    var errorDescription: String? {
        switch self {
        case .invalidValue:
            return "App ID 和 Resource ID 不能为空"
        case .osStatus(let status):
            return "Keychain 写入失败（\(status)）"
        }
    }
}
