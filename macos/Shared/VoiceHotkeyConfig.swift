import Foundation

enum VoiceHotkeyChoice: String, Codable, CaseIterable, Identifiable {
    case middleMouse = "middle_mouse"
    case rightOption = "right_option"
    case optionSpace = "option_space"

    var id: String { rawValue }

    var title: String {
        switch self {
        case .middleMouse: return "鼠标中键（滚轮）"
        case .rightOption: return "右 Option"
        case .optionSpace: return "Option + Space"
        }
    }

    var compactTitle: String {
        switch self {
        case .middleMouse: return "中键按住"
        case .rightOption: return "Right ⌥"
        case .optionSpace: return "⌥ Space"
        }
    }
}

struct VoiceHotkeyConfig: Codable, Equatable {
    static let schemaVersion = "rag-ime.voice-hotkey.v1"
    static let `default` = VoiceHotkeyConfig(schemaVersion: schemaVersion, choice: .middleMouse)

    let schemaVersion: String
    let choice: VoiceHotkeyChoice
}

enum VoiceHotkeyConfigStore {
    static var configURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
            .appendingPathComponent("voice-hotkey.json")
    }

    static func read() -> VoiceHotkeyConfig {
        guard let data = try? Data(contentsOf: configURL),
              let value = try? JSONDecoder().decode(VoiceHotkeyConfig.self, from: data),
              value.schemaVersion == VoiceHotkeyConfig.schemaVersion else {
            return .default
        }
        return value
    }

    static func write(_ choice: VoiceHotkeyChoice) throws {
        let value = VoiceHotkeyConfig(schemaVersion: VoiceHotkeyConfig.schemaVersion, choice: choice)
        let directory = configURL.deletingLastPathComponent()
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let data = try JSONEncoder().encode(value)
        try data.write(to: configURL, options: .atomic)
        try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: configURL.path)
    }
}
