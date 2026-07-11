import Foundation
import Security

struct VoiceASRCredentials: Codable, Equatable {
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
        if let local = VoiceCredentialFileStore.loadCredentials() {
            return local
        }
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

    static func saveLocal(appID: String, accessToken: String?, resourceID: String) throws {
        let previous = VoiceCredentialFileStore.loadCredentials()
        let trimmedAppID = appID.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedResourceID = resourceID.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedToken = accessToken?.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedAppID.isEmpty,
              !trimmedResourceID.isEmpty,
              let token = (trimmedToken?.isEmpty == false ? trimmedToken : previous?.accessToken),
              !token.isEmpty else {
            throw VoiceKeychainError.invalidValue
        }
        try VoiceCredentialFileStore.save(
            VoiceASRCredentials(appID: trimmedAppID, accessToken: token, resourceID: trimmedResourceID)
        )
    }

    static var hasAccessToken: Bool {
        if VoiceCredentialFileStore.loadCredentials()?.isComplete == true {
            return true
        }
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

enum VoiceCredentialFileStore {
    private struct Payload: Codable {
        static let schemaVersion = "rag-ime.voice-credentials.v1"
        let schemaVersion: String
        let appID: String
        let accessToken: String
        let resourceID: String
    }

    static var configURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
            .appendingPathComponent("voice-credentials.json")
    }

    static func loadCredentials() -> VoiceASRCredentials? {
        guard let data = try? Data(contentsOf: configURL),
              let payload = try? JSONDecoder().decode(Payload.self, from: data),
              payload.schemaVersion == Payload.schemaVersion else {
            return nil
        }
        let credentials = VoiceASRCredentials(
            appID: payload.appID,
            accessToken: payload.accessToken,
            resourceID: payload.resourceID
        )
        return credentials.isComplete ? credentials : nil
    }

    static func save(_ credentials: VoiceASRCredentials) throws {
        guard credentials.isComplete else { throw VoiceKeychainError.invalidValue }
        let directory = configURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let payload = Payload(
            schemaVersion: Payload.schemaVersion,
            appID: credentials.appID,
            accessToken: credentials.accessToken,
            resourceID: credentials.resourceID
        )
        let data = try JSONEncoder().encode(payload)
        try data.write(to: configURL, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: configURL.path)
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
