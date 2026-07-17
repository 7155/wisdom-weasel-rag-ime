import AppKit
import Carbon
import Foundation

enum DesktopPrivacyPolicy {
    static let additionalBundleIDsEnvironmentKey = "RAG_IME_DESKTOP_DENIED_BUNDLE_IDS"

    private static let deniedBundlePrefixes = [
        "com.1password",
        "com.agilebits.onepassword",
        "com.bitwarden",
        "com.lastpass",
        "com.dashlane",
        "com.enpass",
        "org.keepassxc",
        "com.apple.passwords",
        "com.apple.keychainaccess",
        "com.icbc",
        "com.cmbchina",
        "com.ccb",
        "com.bankofchina",
        "com.boc",
        "com.cib",
        "com.spdb",
        "com.unionpay",
        "com.alipay",
        "org.torproject.torbrowser",
        "com.duckduckgo.macos.browser",
    ]

    private static let deniedApplicationNameFragments = [
        "1password", "bitwarden", "lastpass", "dashlane", "enpass", "keepass",
        "keychain access", "password manager", "tor browser", "duckduckgo",
        "密码", "钥匙串", "银行", "网银", "支付宝",
    ]

    private static let privateBrowsingFragments = [
        "private browsing", "private window", "incognito", "inprivate",
        "隐私浏览", "私密浏览", "无痕", "隐身模式",
    ]

    static func denialReason(
        bundleIdentifier: String,
        applicationName: String,
        metadata: String = "",
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> String? {
        if IsSecureEventInputEnabled() {
            return "secure_event_input"
        }
        let bundle = normalize(bundleIdentifier)
        guard !bundle.isEmpty else { return "application_bundle_missing" }
        let configured = configuredBundlePrefixes(environment: environment)
        if (deniedBundlePrefixes + configured).contains(where: { matches(bundle: bundle, prefix: $0) }) {
            return "sensitive_application"
        }
        let normalizedName = normalize(applicationName)
        if deniedApplicationNameFragments.contains(where: normalizedName.contains) {
            return "sensitive_application_name"
        }
        let normalizedMetadata = normalize(metadata)
        if privateBrowsingFragments.contains(where: normalizedMetadata.contains) {
            return "private_browsing_window"
        }
        return nil
    }

    static func elementIsSecure(role: String, subrole: String, metadata: String) -> Bool {
        let normalizedRole = normalize("\(role) \(subrole)")
        if normalizedRole.contains("securetextfield") || normalizedRole.contains("secure text") {
            return true
        }
        let normalizedMetadata = normalize(metadata)
        return ["password", "passcode", "密码", "口令"].contains(where: normalizedMetadata.contains)
    }

    private static func configuredBundlePrefixes(environment: [String: String]) -> [String] {
        guard let raw = environment[additionalBundleIDsEnvironmentKey] else { return [] }
        return raw
            .components(separatedBy: CharacterSet(charactersIn: ",;\n"))
            .map(normalize)
            .filter { !$0.isEmpty }
    }

    private static func matches(bundle: String, prefix: String) -> Bool {
        let normalizedPrefix = normalize(prefix).trimmingCharacters(in: CharacterSet(charactersIn: "."))
        return bundle == normalizedPrefix || bundle.hasPrefix(normalizedPrefix + ".")
    }

    private static func normalize(_ value: String) -> String {
        value.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
    }
}
