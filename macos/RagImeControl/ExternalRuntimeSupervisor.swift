import Darwin
import Foundation

struct ValidatedExternalCommand: Sendable, Equatable {
    let executableURL: URL
    let arguments: [String]
    let currentDirectoryURL: URL?

    var displayCommand: [String] {
        [executableURL.path] + arguments
    }
}

struct ExternalSupervisorExecutionResult: Sendable {
    let command: [String]
    let exitCode: Int32
    let stdout: String
    let stderr: String
    let timedOut: Bool

    var succeeded: Bool { !timedOut && exitCode == 0 }
}

enum ExternalRuntimeSupervisorError: LocalizedError {
    case missingCommand(String)
    case rejectedCommand(String)

    var errorDescription: String? {
        switch self {
        case .missingCommand(let action):
            return "\(action) 没有可用的外部修复命令。控制中心不会猜测或调用不存在的仓库脚本；请先从源码安装 LaunchAgent helper。"
        case .rejectedCommand(let reason):
            return "Sidecar 返回的外部命令未通过本地白名单校验：\(reason)"
        }
    }
}

enum ExternalCommandPolicy {
    private static let launchctlURL = URL(fileURLWithPath: "/bin/launchctl")
    private static let bashURL = URL(fileURLWithPath: "/bin/bash")
    private static let sidecarLabel = "com.rag-ime.sidecar"
    private static let predictorLabel = "com.rag-ime.mlx-predictor"
    private static let repairHelperNames: Set<String> = ["repair_rag_ime_launch_agents.sh"]
    private static let repairHelperDirectories: Set<String> = ["scripts", "supervisor-helpers", "supervisorhelpers"]

    static func validate(
        action: String,
        command: [String],
        uid: uid_t = getuid(),
        trustedRoots: [URL] = ExternalRuntimeSupervisor.trustedHelperRoots()
    ) throws -> ValidatedExternalCommand {
        guard !command.isEmpty else {
            throw ExternalRuntimeSupervisorError.missingCommand(action)
        }

        switch action {
        case "restart_sidecar":
            return try validateLaunchctl(command, uid: uid, expectedLabel: sidecarLabel)
        case "restart_predictor":
            return try validateLaunchctl(command, uid: uid, expectedLabel: predictorLabel)
        case "repair_launch_agents":
            return try validateRepairHelper(command, trustedRoots: trustedRoots)
        default:
            throw ExternalRuntimeSupervisorError.rejectedCommand("操作 \(action) 不允许由外部监督器执行")
        }
    }

    private static func validateLaunchctl(
        _ command: [String],
        uid: uid_t,
        expectedLabel: String
    ) throws -> ValidatedExternalCommand {
        guard command.count == 4 else {
            throw ExternalRuntimeSupervisorError.rejectedCommand("launchctl 参数数量不匹配")
        }
        guard command[0] == "launchctl" || command[0] == launchctlURL.path else {
            throw ExternalRuntimeSupervisorError.rejectedCommand("只允许 /bin/launchctl")
        }
        let expectedTarget = "gui/\(uid)/\(expectedLabel)"
        guard Array(command.dropFirst()) == ["kickstart", "-k", expectedTarget] else {
            throw ExternalRuntimeSupervisorError.rejectedCommand("launchctl target 必须是当前用户的 \(expectedLabel)")
        }
        return ValidatedExternalCommand(
            executableURL: launchctlURL,
            arguments: Array(command.dropFirst()),
            currentDirectoryURL: nil
        )
    }

    private static func validateRepairHelper(
        _ command: [String],
        trustedRoots: [URL]
    ) throws -> ValidatedExternalCommand {
        guard command.count == 2, command[0] == bashURL.path else {
            throw ExternalRuntimeSupervisorError.rejectedCommand("修复操作只允许 /bin/bash 加一个已知 helper 路径，且不接受 -c")
        }

        let suppliedURL = URL(fileURLWithPath: command[1]).standardizedFileURL
        let resolvedURL = suppliedURL.resolvingSymlinksInPath().standardizedFileURL
        guard repairHelperNames.contains(resolvedURL.lastPathComponent) else {
            throw ExternalRuntimeSupervisorError.rejectedCommand("helper 文件名不在白名单")
        }
        guard repairHelperDirectories.contains(resolvedURL.deletingLastPathComponent().lastPathComponent.lowercased()) else {
            throw ExternalRuntimeSupervisorError.rejectedCommand("helper 必须位于 scripts 或 supervisor-helpers 目录")
        }

        let resolvedRoots = trustedRoots.map { $0.resolvingSymlinksInPath().standardizedFileURL }
        guard resolvedRoots.contains(where: { isDirectKnownHelper(resolvedURL, root: $0) }) else {
            throw ExternalRuntimeSupervisorError.rejectedCommand("helper 不在可信源码或 Application Support 根目录")
        }

        var isDirectory: ObjCBool = false
        guard FileManager.default.fileExists(atPath: resolvedURL.path, isDirectory: &isDirectory), !isDirectory.boolValue else {
            throw ExternalRuntimeSupervisorError.missingCommand("repair_launch_agents")
        }
        let attributes = try? FileManager.default.attributesOfItem(atPath: resolvedURL.path)
        guard attributes?[.type] as? FileAttributeType == .typeRegular else {
            throw ExternalRuntimeSupervisorError.rejectedCommand("helper 不是普通文件")
        }

        return ValidatedExternalCommand(
            executableURL: bashURL,
            arguments: [resolvedURL.path],
            currentDirectoryURL: resolvedURL.deletingLastPathComponent()
        )
    }

    private static func isDirectKnownHelper(_ candidate: URL, root: URL) -> Bool {
        let helperDirectory = candidate.deletingLastPathComponent()
        guard repairHelperDirectories.contains(helperDirectory.lastPathComponent.lowercased()) else { return false }
        return helperDirectory.deletingLastPathComponent() == root
    }
}

enum ExternalRuntimeSupervisor {
    static func trustedHelperRoots(
        environment: [String: String] = ProcessInfo.processInfo.environment,
        homeDirectory: URL = FileManager.default.homeDirectoryForCurrentUser,
        bundle: Bundle = .main
    ) -> [URL] {
        var roots: [URL] = []
        for key in ["RAG_IME_SOURCE_ROOT", "RAG_IME_REPO_ROOT"] {
            if let value = environment[key], !value.isEmpty {
                roots.append(URL(fileURLWithPath: value))
            }
        }

        let appSupport = homeDirectory
            .appendingPathComponent("Library/Application Support/RagIme", isDirectory: true)
        roots.append(appSupport)
        if let resources = bundle.resourceURL {
            roots.append(resources)
        }

        for label in ["com.rag-ime.sidecar", "com.rag-ime.mlx-predictor"] {
            let plistURL = homeDirectory
                .appendingPathComponent("Library/LaunchAgents", isDirectory: true)
                .appendingPathComponent("\(label).plist")
            guard
                let data = try? Data(contentsOf: plistURL),
                let plist = try? PropertyListSerialization.propertyList(from: data, format: nil),
                let object = plist as? [String: Any],
                let variables = object["EnvironmentVariables"] as? [String: Any],
                let sourceRoot = variables["RAG_IME_SOURCE_ROOT"] as? String,
                !sourceRoot.isEmpty
            else { continue }
            roots.append(URL(fileURLWithPath: sourceRoot))
        }

        var seen: Set<String> = []
        return roots.compactMap { root in
            let resolved = root.resolvingSymlinksInPath().standardizedFileURL
            return seen.insert(resolved.path).inserted ? resolved : nil
        }
    }

    static func execute(
        action: String,
        command: [String],
        timeoutSeconds: TimeInterval = 90,
        trustedRoots: [URL]? = nil
    ) async throws -> ExternalSupervisorExecutionResult {
        let validated = try ExternalCommandPolicy.validate(
            action: action,
            command: command,
            trustedRoots: trustedRoots ?? trustedHelperRoots()
        )
        return try await run(validated, timeoutSeconds: timeoutSeconds)
    }

    private static func run(
        _ command: ValidatedExternalCommand,
        timeoutSeconds: TimeInterval
    ) async throws -> ExternalSupervisorExecutionResult {
        try await Task.detached(priority: .userInitiated) {
            let fileManager = FileManager.default
            let outputRoot = fileManager.temporaryDirectory
                .appendingPathComponent("rag-ime-supervisor-\(UUID().uuidString)", isDirectory: true)
            try fileManager.createDirectory(at: outputRoot, withIntermediateDirectories: true)
            defer { try? fileManager.removeItem(at: outputRoot) }

            let stdoutURL = outputRoot.appendingPathComponent("stdout.log")
            let stderrURL = outputRoot.appendingPathComponent("stderr.log")
            fileManager.createFile(atPath: stdoutURL.path, contents: nil)
            fileManager.createFile(atPath: stderrURL.path, contents: nil)
            let stdoutHandle = try FileHandle(forWritingTo: stdoutURL)
            let stderrHandle = try FileHandle(forWritingTo: stderrURL)
            defer {
                try? stdoutHandle.close()
                try? stderrHandle.close()
            }

            let process = Process()
            process.executableURL = command.executableURL
            process.arguments = command.arguments
            process.currentDirectoryURL = command.currentDirectoryURL
            process.standardOutput = stdoutHandle
            process.standardError = stderrHandle
            try process.run()

            let deadline = Date().addingTimeInterval(max(1, timeoutSeconds))
            while process.isRunning, Date() < deadline {
                try? await Task.sleep(nanoseconds: 50_000_000)
            }
            let timedOut = process.isRunning
            if timedOut {
                process.terminate()
            }
            process.waitUntilExit()
            try? stdoutHandle.synchronize()
            try? stderrHandle.synchronize()

            let stdout = String(decoding: (try? Data(contentsOf: stdoutURL)) ?? Data(), as: UTF8.self)
            let stderr = String(decoding: (try? Data(contentsOf: stderrURL)) ?? Data(), as: UTF8.self)
            return ExternalSupervisorExecutionResult(
                command: command.displayCommand,
                exitCode: process.terminationStatus,
                stdout: String(stdout.suffix(4_000)).trimmingCharacters(in: .whitespacesAndNewlines),
                stderr: String(stderr.suffix(4_000)).trimmingCharacters(in: .whitespacesAndNewlines),
                timedOut: timedOut
            )
        }.value
    }
}
