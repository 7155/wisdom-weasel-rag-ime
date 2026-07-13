import Foundation

enum VoicePrivacyPolicy {
    static let additionalBundleIDsEnvironmentKey = "RAG_IME_VOICE_DENIED_BUNDLE_IDS"

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

    static func denies(
        bundleIdentifier: String,
        applicationName: String,
        metadata: String,
        environment: [String: String] = ProcessInfo.processInfo.environment
    ) -> Bool {
        let bundle = normalize(bundleIdentifier)
        // This is deliberately a denylist: missing browser/AX metadata must
        // not turn every custom web editor into a false positive.
        guard !bundle.isEmpty else { return false }
        let configured = configuredBundlePrefixes(environment: environment)
        if (deniedBundlePrefixes + configured).contains(where: { matches(bundle: bundle, prefix: $0) }) {
            return true
        }

        let normalizedName = normalize(applicationName)
        if deniedApplicationNameFragments.contains(where: normalizedName.contains) { return true }

        let normalizedMetadata = normalize(metadata)
        return privateBrowsingFragments.contains(where: normalizedMetadata.contains)
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
