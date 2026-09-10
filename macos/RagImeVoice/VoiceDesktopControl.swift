import Foundation

/// A bounded stdin/stdout interface for the installed Electron desktop host.
/// Secrets stay in the existing credential owner and never enter process arguments.
enum VoiceDesktopControl {
    static func run() -> Int32 {
        do {
            let data = FileHandle.standardInput.readData(ofLength: 65_537)
            guard data.count <= 65_536,
                  let request = try JSONSerialization.jsonObject(with: data) as? [String: String],
                  let operation = request["operation"] else { throw VoiceKeychainError.invalidValue }
            var result: [String: Any] = [:]
            if operation == "credential_status" || operation == "save_credentials" {
                guard let provider = VoiceASRProvider(rawValue: request["provider"] ?? "") else {
                    throw VoiceKeychainError.invalidValue
                }
                if operation == "save_credentials" {
                    try VoiceKeychainStore.save(
                        provider: provider, appID: request["appId"] ?? "",
                        accessToken: request["accessToken"], resourceID: request["resourceId"] ?? "",
                        endpoint: request["endpoint"] ?? "", model: request["model"] ?? "",
                        headersJSON: request["headersJson"] ?? ""
                    )
                }
                result = ["provider": provider.rawValue, "configured": VoiceCredentialMetadataStore.isConfigured(provider)]
            } else {
                let notifications = [
                    "reload_configuration": "configuration-changed",
                    "request_microphone_permission": "request-microphone-permission",
                    "request_accessibility_permission": "request-accessibility-permission",
                ]
                guard let name = notifications[operation] else { throw VoiceKeychainError.invalidValue }
                DistributedNotificationCenter.default().postNotificationName(
                    Notification.Name("com.rag-ime.voice.\(name)"), object: nil,
                    userInfo: nil, deliverImmediately: true
                )
                result = ["accepted": true]
            }
            let output = try JSONSerialization.data(withJSONObject: result)
            FileHandle.standardOutput.write(output)
            return 0
        } catch {
            // Do not echo request data or keychain contents in errors.
            fputs("Voice desktop operation failed\n", stderr)
            return 1
        }
    }
}
