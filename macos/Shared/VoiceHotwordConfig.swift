import Foundation

struct VoiceASRHotwordConfig: Codable, Equatable {
    static let schemaVersion = "rag-ime.voice-hotwords.v1"
    static let maxWordCount = 32
    static let minCharactersPerWord = 2
    static let maxCharactersPerWord = 9
    static let disabled = VoiceASRHotwordConfig(
        schemaVersion: schemaVersion,
        enabled: false,
        words: []
    )

    let schemaVersion: String
    let enabled: Bool
    let words: [String]

    var effectiveWords: [String] {
        enabled ? words : []
    }

    static func validated(enabled: Bool, rawLines: String) throws -> VoiceASRHotwordConfig {
        var normalized: [String] = []
        var seen = Set<String>()
        for rawWord in rawLines.components(separatedBy: .newlines) {
            let word = rawWord
                .trimmingCharacters(in: .whitespacesAndNewlines)
                .split(whereSeparator: { $0.isWhitespace })
                .joined(separator: " ")
            guard !word.isEmpty else { continue }
            guard word.count >= minCharactersPerWord, word.count <= maxCharactersPerWord else {
                throw VoiceHotwordError.invalidLength(word)
            }
            guard word.unicodeScalars.allSatisfy({ scalar in
                CharacterSet.letters.contains(scalar) || CharacterSet.whitespaces.contains(scalar)
            }) else {
                throw VoiceHotwordError.invalidCharacters(word)
            }
            let dedupeKey = word.folding(options: [.caseInsensitive, .widthInsensitive], locale: .current)
            guard seen.insert(dedupeKey).inserted else { continue }
            normalized.append(word)
            guard normalized.count <= maxWordCount else {
                throw VoiceHotwordError.tooManyWords(maxWordCount)
            }
        }
        if enabled && normalized.isEmpty {
            throw VoiceHotwordError.enabledWithoutWords
        }
        return VoiceASRHotwordConfig(
            schemaVersion: schemaVersion,
            enabled: enabled,
            words: normalized
        )
    }

    func requestContextJSONString() -> String? {
        guard !effectiveWords.isEmpty else { return nil }
        let payload: [String: Any] = [
            "hotwords": effectiveWords.map { ["word": $0] },
        ]
        guard let data = try? JSONSerialization.data(withJSONObject: payload) else { return nil }
        return String(data: data, encoding: .utf8)
    }
}

enum VoiceHotwordConfigStore {
    static var fileURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
            .appendingPathComponent("voice-hotwords.json", isDirectory: false)
    }

    static func read() -> VoiceASRHotwordConfig {
        guard let data = try? Data(contentsOf: fileURL),
              let config = try? JSONDecoder().decode(VoiceASRHotwordConfig.self, from: data),
              config.schemaVersion == VoiceASRHotwordConfig.schemaVersion,
              let validated = try? VoiceASRHotwordConfig.validated(
                  enabled: config.enabled,
                  rawLines: config.words.joined(separator: "\n")
              ) else {
            return .disabled
        }
        return validated
    }

    static func write(_ config: VoiceASRHotwordConfig) throws {
        let directory = fileURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = try JSONEncoder().encode(config)
        try data.write(to: fileURL, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: fileURL.path)
    }

    static func remove() {
        try? FileManager.default.removeItem(at: fileURL)
    }
}

enum VoiceHotwordError: LocalizedError, Equatable {
    case enabledWithoutWords
    case invalidLength(String)
    case invalidCharacters(String)
    case tooManyWords(Int)

    var errorDescription: String? {
        switch self {
        case .enabledWithoutWords:
            return "启用热词前至少填写一个词"
        case .invalidLength(let word):
            return "热词“\(word)”需为 2 至 9 个字符"
        case .invalidCharacters(let word):
            return "热词“\(word)”只能包含中英文字母与空格"
        case .tooManyWords(let limit):
            return "一次最多启用 \(limit) 个热词"
        }
    }
}
