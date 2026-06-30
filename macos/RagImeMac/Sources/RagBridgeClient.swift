import Foundation

struct RagBridgeConfig {
    let repoRoot: String
    let dbPath: String
    let pythonExecutable: String
    let project: String
    let topK: Int

    static func load() -> RagBridgeConfig {
        let env = ProcessInfo.processInfo.environment
        let bundle = Bundle.main
        let repoRoot = env["RAG_IME_REPO_ROOT"]
            ?? bundle.object(forInfoDictionaryKey: "RagImeRepoRoot") as? String
            ?? FileManager.default.currentDirectoryPath
        let dbPath = env["RAG_IME_DB_PATH"]
            ?? bundle.object(forInfoDictionaryKey: "RagImeDBPath") as? String
            ?? "\(repoRoot)/.rag-ime-data/rag-ime.sqlite"
        let python = env["RAG_IME_PYTHON"]
            ?? bundle.object(forInfoDictionaryKey: "RagImePythonExecutable") as? String
            ?? "/usr/bin/python3"
        let project = env["RAG_IME_PROJECT"]
            ?? bundle.object(forInfoDictionaryKey: "RagImeProject") as? String
            ?? "wisdom-weasel-rag-ime"
        let topKText = env["RAG_IME_TOP_K"]
        let topK = topKText.flatMap(Int.init)
            ?? bundle.object(forInfoDictionaryKey: "RagImeTopK") as? Int
            ?? 5
        return RagBridgeConfig(repoRoot: repoRoot, dbPath: dbPath, pythonExecutable: python, project: project, topK: topK)
    }
}

enum RagBridgeError: LocalizedError {
    case invalidUTF8
    case processFailed(command: String, status: Int32, stderr: String)

    var errorDescription: String? {
        switch self {
        case .invalidUTF8:
            return "RAG IME bridge returned non-UTF8 output"
        case .processFailed(let command, let status, let stderr):
            return "RAG IME bridge failed (\(status)): \(command)\n\(stderr)"
        }
    }
}

final class RagBridgeClient {
    private let config: RagBridgeConfig
    private let decoder = JSONDecoder()

    init(config: RagBridgeConfig = .load()) {
        self.config = config
    }

    func initializeDatabase() throws {
        _ = try runCli(["init-db"])
    }

    func seedDemo(reset: Bool) throws {
        var args = ["seed-demo"]
        if reset {
            args.append("--reset")
        }
        _ = try runCli(args)
    }

    func suggest(currentInput: String, recentContext: String = "") throws -> SuggestionResponse {
        let data = try runCli([
            "suggest-json",
            currentInput,
            "--recent-context",
            recentContext,
            "--project",
            config.project,
            "--top-k",
            String(config.topK),
        ])
        return try decoder.decode(SuggestionResponse.self, from: data)
    }

    func recordCommit(text: String, recentContext: String = "", preedit: String = "", source: String = "macos_inputmethod") throws {
        _ = try runCli([
            "commit",
            text,
            "--recent-context",
            recentContext,
            "--preedit",
            preedit,
            "--project",
            config.project,
            "--tag",
            "macos",
        ])
    }

    func apply(actionType: String, suggestion: RagSuggestion, query: String) throws -> ActionResponse {
        let data = try runCli([
            "action-json",
            actionType,
            "--memory-id",
            suggestion.memoryId,
            "--suggestion-id",
            suggestion.suggestionId,
            "--source-event-id",
            String(suggestion.sourceEventId),
            "--query",
            query,
            "--surface-text",
            suggestion.surfaceText,
        ])
        return try decoder.decode(ActionResponse.self, from: data)
    }

    private func runCli(_ cliArgs: [String]) throws -> Data {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: config.pythonExecutable)
        process.arguments = ["-m", "rag_ime.cli", "--db-path", config.dbPath] + cliArgs
        process.currentDirectoryURL = URL(fileURLWithPath: config.repoRoot, isDirectory: true)

        var environment = ProcessInfo.processInfo.environment
        let oldPythonPath = environment["PYTHONPATH"].map { ":\($0)" } ?? ""
        environment["PYTHONPATH"] = config.repoRoot + oldPythonPath
        environment["RAG_IME_DB_PATH"] = config.dbPath
        process.environment = environment

        let stdout = Pipe()
        let stderr = Pipe()
        process.standardOutput = stdout
        process.standardError = stderr
        try process.run()
        process.waitUntilExit()

        let output = stdout.fileHandleForReading.readDataToEndOfFile()
        let errorOutput = stderr.fileHandleForReading.readDataToEndOfFile()
        if process.terminationStatus != 0 {
            let stderrText = String(data: errorOutput, encoding: .utf8) ?? "<non-utf8 stderr>"
            throw RagBridgeError.processFailed(
                command: ([config.pythonExecutable] + (process.arguments ?? [])).joined(separator: " "),
                status: process.terminationStatus,
                stderr: stderrText
            )
        }
        return output
    }
}
