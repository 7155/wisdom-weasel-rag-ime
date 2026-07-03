import Foundation

struct RagBridgeConfig {
    let repoRoot: String
    let dbPath: String
    let pythonExecutable: String
    let project: String
    let topK: Int
    let sidecarBaseUrl: String
    let rimeDictDir: String?
    let rimeCandidateIndexPath: String?
    let configSource: String

    static func load() -> RagBridgeConfig {
        let env = ProcessInfo.processInfo.environment
        let bundle = Bundle.main
        let userConfig = RagBridgeConfigFile.userConfig()
        let bundledConfig = RagBridgeConfigFile.bundledConfig(in: bundle)
        let repoRoot = env["RAG_IME_REPO_ROOT"]
            ?? userConfig.string("repoRoot")
            ?? bundledConfig.string("repoRoot")
            ?? bundle.object(forInfoDictionaryKey: "RagImeRepoRoot") as? String
            ?? FileManager.default.currentDirectoryPath
        let dbPath = env["RAG_IME_DB_PATH"]
            ?? userConfig.string("dbPath")
            ?? bundledConfig.string("dbPath")
            ?? bundle.object(forInfoDictionaryKey: "RagImeDBPath") as? String
            ?? "\(repoRoot)/.rag-ime-data/rag-ime.sqlite"
        let python = env["RAG_IME_PYTHON"]
            ?? userConfig.string("pythonExecutable")
            ?? bundledConfig.string("pythonExecutable")
            ?? bundle.object(forInfoDictionaryKey: "RagImePythonExecutable") as? String
            ?? "/usr/bin/python3"
        let project = env["RAG_IME_PROJECT"]
            ?? userConfig.string("project")
            ?? bundledConfig.string("project")
            ?? bundle.object(forInfoDictionaryKey: "RagImeProject") as? String
            ?? "wisdom-weasel-rag-ime"
        let topKText = env["RAG_IME_TOP_K"]
        let topK = topKText.flatMap(Int.init)
            ?? userConfig.int("topK")
            ?? bundledConfig.int("topK")
            ?? bundle.object(forInfoDictionaryKey: "RagImeTopK") as? Int
            ?? 5
        let sidecarBaseUrl = env["RAG_IME_SIDECAR_URL"]
            ?? userConfig.string("sidecarBaseUrl")
            ?? bundledConfig.string("sidecarBaseUrl")
            ?? "http://127.0.0.1:8766"
        let rimeDictDir = env["RAG_IME_RIME_DICT_DIR"]
            ?? userConfig.string("rimeDictDir")
            ?? bundledConfig.string("rimeDictDir")
        let rimeCandidateIndexPath = env["RAG_IME_RIME_INDEX_PATH"]
            ?? userConfig.string("rimeCandidateIndexPath")
            ?? bundledConfig.string("rimeCandidateIndexPath")
        return RagBridgeConfig(
            repoRoot: repoRoot,
            dbPath: dbPath,
            pythonExecutable: python,
            project: project,
            topK: topK,
            sidecarBaseUrl: sidecarBaseUrl,
            rimeDictDir: rimeDictDir,
            rimeCandidateIndexPath: rimeCandidateIndexPath,
            configSource: userConfig.source ?? bundledConfig.source ?? "environment/plist/default"
        )
    }

    func dictionary() -> [String: Any] {
        [
            "repoRoot": repoRoot,
            "dbPath": dbPath,
            "pythonExecutable": pythonExecutable,
            "project": project,
            "sidecarBaseUrl": sidecarBaseUrl,
            "topK": topK,
            "rimeDictDir": rimeDictDir ?? "",
            "rimeCandidateIndexPath": rimeCandidateIndexPath ?? "",
            "configSource": configSource,
        ]
    }
}

private struct RagBridgeConfigFile {
    let values: [String: Any]
    let source: String?

    static func userConfig() -> RagBridgeConfigFile {
        let home = FileManager.default.homeDirectoryForCurrentUser
        let url = home
            .appendingPathComponent("Library", isDirectory: true)
            .appendingPathComponent("Application Support", isDirectory: true)
            .appendingPathComponent("RagImeMac", isDirectory: true)
            .appendingPathComponent("bridge-config.json", isDirectory: false)
        return load(url: url)
    }

    static func bundledConfig(in bundle: Bundle) -> RagBridgeConfigFile {
        guard let url = bundle.url(forResource: "bridge-config", withExtension: "json") else {
            return RagBridgeConfigFile(values: [:], source: nil)
        }
        return load(url: url)
    }

    static func load(url: URL) -> RagBridgeConfigFile {
        guard
            let data = try? Data(contentsOf: url),
            let object = try? JSONSerialization.jsonObject(with: data),
            let values = object as? [String: Any]
        else {
            return RagBridgeConfigFile(values: [:], source: nil)
        }
        return RagBridgeConfigFile(values: values, source: url.path)
    }

    func string(_ key: String) -> String? {
        guard let value = values[key] as? String, !value.isEmpty else {
            return nil
        }
        return value
    }

    func int(_ key: String) -> Int? {
        if let value = values[key] as? Int {
            return value
        }
        if let value = values[key] as? NSNumber {
            return value.intValue
        }
        if let value = values[key] as? String {
            return Int(value)
        }
        return nil
    }
}

enum RagBridgeError: LocalizedError {
    case invalidUTF8
    case processFailed(command: String, status: Int32, stderr: String)
    case invalidURL(String)
    case httpFailed(url: String, status: Int, body: String)

    var errorDescription: String? {
        switch self {
        case .invalidUTF8:
            return "RAG IME bridge returned non-UTF8 output"
        case .processFailed(let command, let status, let stderr):
            return "RAG IME bridge failed (\(status)): \(command)\n\(stderr)"
        case .invalidURL(let value):
            return "RAG IME bridge sidecar URL is invalid: \(value)"
        case .httpFailed(let url, let status, let body):
            return "RAG IME sidecar HTTP failed (\(status)): \(url)\n\(body)"
        }
    }
}

final class RagBridgeClient {
    private let config: RagBridgeConfig
    private let decoder = JSONDecoder()

    init(config: RagBridgeConfig = .load()) {
        self.config = config
    }

    var project: String {
        config.project
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

    func rimeSuggest(request: RimeSidecarRequest) throws -> RimeSidecarResponse {
        if let response = try? postSidecar(path: "/rime-suggest", payload: request, responseType: RimeSidecarResponse.self) {
            return response
        }
        let payloadURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("rag-ime-rime-sidecar-\(UUID().uuidString).json")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let payload = try encoder.encode(request)
        try payload.write(to: payloadURL, options: .atomic)
        defer {
            try? FileManager.default.removeItem(at: payloadURL)
        }
        let data = try runCli([
            "rime-suggest-json",
            "--payload-file",
            payloadURL.path,
        ])
        return try decoder.decode(RimeSidecarResponse.self, from: data)
    }

    func rimeSelect(request: RimeSelectRequest) throws -> RimeSelectResponse {
        if let response = try? postSidecar(path: "/rime-select", payload: request, responseType: RimeSelectResponse.self) {
            return response
        }
        let payloadURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("rag-ime-rime-select-\(UUID().uuidString).json")
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys, .withoutEscapingSlashes]
        let payload = try encoder.encode(request)
        try payload.write(to: payloadURL, options: .atomic)
        defer {
            try? FileManager.default.removeItem(at: payloadURL)
        }
        let data = try runCli([
            "rime-select-json",
            "--payload-file",
            payloadURL.path,
        ])
        return try decoder.decode(RimeSelectResponse.self, from: data)
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

    private func postSidecar<Request: Encodable, Response: Decodable>(
        path: String,
        payload: Request,
        responseType: Response.Type
    ) throws -> Response {
        let base = config.sidecarBaseUrl.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        guard let url = URL(string: base + path) else {
            throw RagBridgeError.invalidURL(base + path)
        }

        let requestData = try JSONEncoder().encode(payload)
        var urlRequest = URLRequest(url: url, timeoutInterval: 1.6)
        urlRequest.httpMethod = "POST"
        urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
        urlRequest.httpBody = requestData

        let semaphore = DispatchSemaphore(value: 0)
        var result: Result<Data, Error>!
        URLSession.shared.dataTask(with: urlRequest) { data, response, error in
            defer { semaphore.signal() }
            if let error {
                result = .failure(error)
                return
            }
            let status = (response as? HTTPURLResponse)?.statusCode ?? 0
            let body = data ?? Data()
            guard (200..<300).contains(status) else {
                let bodyText = String(data: body, encoding: .utf8) ?? "<non-utf8 body>"
                result = .failure(RagBridgeError.httpFailed(url: url.absoluteString, status: status, body: bodyText))
                return
            }
            result = .success(body)
        }.resume()

        _ = semaphore.wait(timeout: .now() + 1.8)
        guard let result else {
            throw RagBridgeError.httpFailed(url: url.absoluteString, status: -1, body: "timeout")
        }
        let data = try result.get()
        return try decoder.decode(responseType, from: data)
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
