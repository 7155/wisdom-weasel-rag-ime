import Foundation

final class RimeDictionaryCandidateProvider {
    private struct Entry {
        let text: String
        let code: String
        let initials: String
        let weight: Double
        let commonnessPenalty: Int
        let order: Int
    }

    private let dictionaryPath: String?
    private let dictionaryPaths: [String]
    private let essayPath: String?
    private let dictionaryLabel: String
    private var cachedEntries: [Entry]?
    private var cachedBuckets: [String: [Entry]]?

    init(environment: [String: String] = ProcessInfo.processInfo.environment) {
        let configured = environment["RAG_IME_RIME_DICT_PATH"].flatMap { $0.isEmpty ? nil : $0 }
        let configuredPaths = environment["RAG_IME_RIME_DICT_PATHS"].flatMap { $0.isEmpty ? nil : $0 }
        let configuredDirectory = environment["RAG_IME_RIME_DICT_DIR"].flatMap { $0.isEmpty ? nil : $0 }
        let configuredEssay = environment["RAG_IME_RIME_ESSAY_PATH"].flatMap { $0.isEmpty ? nil : $0 }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let resolvedPaths = Self.resolveDictionaryPaths(
            configuredPath: configured,
            configuredPaths: configuredPaths,
            configuredDirectory: configuredDirectory,
            defaultDirectory: "\(home)/Library/Rime"
        )
        self.dictionaryPaths = resolvedPaths
        self.dictionaryPath = resolvedPaths.first
        let essayCandidates = [
            configuredEssay,
            "\(home)/Library/Rime/essay.txt",
        ].compactMap { $0 }
        self.essayPath = essayCandidates.first { FileManager.default.fileExists(atPath: $0) }
        if resolvedPaths.contains(where: { $0.localizedCaseInsensitiveContains("wanxiang") }) {
            self.dictionaryLabel = "wanxiang"
        } else {
            self.dictionaryLabel = "rime"
        }
    }

    func candidates(for rawInput: String, maxCount: Int = 8) -> [RimeCandidatePayload] {
        let query = normalizedQuery(rawInput)
        guard !query.isEmpty, let entries = candidatePool(for: query) else {
            return []
        }

        var seen = Set<String>()
        let ranked = entries.compactMap { entry -> (rank: Double, score: Int, entry: Entry)? in
            guard let score = score(entry: entry, query: query) else {
                return nil
            }
            let rank = Double(score * 1_000 + entry.commonnessPenalty * 100) - min(entry.weight, 999_999)
            return (rank, score, entry)
        }
        .sorted { lhs, rhs in
            if lhs.rank != rhs.rank {
                return lhs.rank < rhs.rank
            }
            if lhs.entry.weight != rhs.entry.weight {
                return lhs.entry.weight > rhs.entry.weight
            }
            if lhs.entry.text.count != rhs.entry.text.count {
                return lhs.entry.text.count < rhs.entry.text.count
            }
            return lhs.entry.order < rhs.entry.order
        }

        var payloads: [RimeCandidatePayload] = []
        for item in ranked {
            guard !seen.contains(item.entry.text) else {
                continue
            }
            seen.insert(item.entry.text)
            payloads.append(RimeCandidatePayload(
                label: "\(payloads.count + 1)",
                text: item.entry.text,
                comment: dictionaryLabel,
                index: item.entry.order
            ))
            if payloads.count >= max(1, maxCount) {
                break
            }
        }
        return payloads
    }

    func diagnosticPayload(for queries: [String]) -> [String: [[String: String]]] {
        var payload: [String: [[String: String]]] = [:]
        for query in queries {
            payload[query] = candidates(for: query, maxCount: 8).map { candidate in
                [
                    "label": candidate.label,
                    "text": candidate.text,
                    "comment": candidate.comment,
                    "index": candidate.index.map(String.init) ?? "",
                ]
            }
        }
        return payload
    }

    private func loadEntries() -> [Entry]? {
        if let cachedEntries {
            return cachedEntries
        }
        guard !dictionaryPaths.isEmpty else {
            cachedEntries = []
            return cachedEntries
        }
        let essayWeights = loadEssayWeights()
        var entries: [Entry] = []
        for dictionaryPath in dictionaryPaths {
            guard let content = try? String(contentsOfFile: dictionaryPath, encoding: .utf8) else {
                continue
            }
            appendEntries(from: content, essayWeights: essayWeights, into: &entries)
        }
        cachedEntries = entries
        return entries
    }

    private func appendEntries(from content: String, essayWeights: [String: Double], into entries: inout [Entry]) {
        var inBody = false
        for line in content.split(separator: "\n", omittingEmptySubsequences: false) {
            let raw = String(line)
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed == "..." {
                inBody = true
                continue
            }
            guard inBody, !trimmed.isEmpty, !trimmed.hasPrefix("#") else {
                continue
            }
            let fields = raw.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            guard fields.count >= 2 else {
                continue
            }
            let text = fields[0].trimmingCharacters(in: .whitespacesAndNewlines)
            let codeText = fields[1].trimmingCharacters(in: .whitespacesAndNewlines)
            let normalizedCode = normalizePinyinCode(codeText)
            guard !text.isEmpty, !normalizedCode.isEmpty else {
                continue
            }
            let weight = fields.dropFirst(2).compactMap { Double($0.trimmingCharacters(in: .whitespacesAndNewlines)) }.first ?? 0
            let essayWeight = essayWeights[text] ?? 0
            entries.append(Entry(
                text: text,
                code: normalizedCode,
                initials: initials(from: codeText),
                weight: max(weight, essayWeight),
                commonnessPenalty: commonnessPenalty(text),
                order: entries.count
            ))
        }
    }

    private func candidatePool(for query: String) -> [Entry]? {
        guard let buckets = loadBuckets() else {
            return nil
        }
        return buckets[bucketKey(query)] ?? []
    }

    private func loadBuckets() -> [String: [Entry]]? {
        if let cachedBuckets {
            return cachedBuckets
        }
        guard let entries = loadEntries() else {
            return nil
        }
        var buckets: [String: [Entry]] = [:]
        for entry in entries {
            insert(entry, into: &buckets, key: bucketKey(entry.code))
            insert(entry, into: &buckets, key: bucketKey(entry.initials))
        }
        cachedBuckets = buckets
        return buckets
    }

    private func insert(_ entry: Entry, into buckets: inout [String: [Entry]], key: String) {
        guard !key.isEmpty else {
            return
        }
        buckets[key, default: []].append(entry)
    }

    private func loadEssayWeights() -> [String: Double] {
        guard let essayPath, let content = try? String(contentsOfFile: essayPath, encoding: .utf8) else {
            return [:]
        }
        var weights: [String: Double] = [:]
        for line in content.split(separator: "\n", omittingEmptySubsequences: false) {
            let fields = line.split(separator: "\t", omittingEmptySubsequences: false).map(String.init)
            guard fields.count >= 2 else {
                continue
            }
            let text = fields[0].trimmingCharacters(in: .whitespacesAndNewlines)
            let weight = Double(fields[1].trimmingCharacters(in: .whitespacesAndNewlines)) ?? 0
            if !text.isEmpty {
                weights[text] = max(weights[text] ?? 0, weight)
            }
        }
        return weights
    }

    private func score(entry: Entry, query: String) -> Int? {
        if entry.code == query {
            return 0
        }
        if entry.code.hasPrefix(query) {
            return 1
        }
        if entry.initials == query {
            return 2
        }
        if entry.initials.hasPrefix(query) {
            return 3
        }
        return nil
    }

    private func normalizedQuery(_ rawInput: String) -> String {
        let trimmed = rawInput.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed.count <= 32 else {
            return ""
        }
        guard trimmed.unicodeScalars.allSatisfy({ scalar in
            CharacterSet.alphanumerics.contains(scalar) || scalar == "'" || scalar == "-"
        }) else {
            return ""
        }
        return normalizePinyinCode(trimmed)
    }

    private func normalizePinyinCode(_ value: String) -> String {
        value
            .folding(options: [.caseInsensitive, .diacriticInsensitive], locale: Locale(identifier: "en_US_POSIX"))
            .unicodeScalars
            .filter { CharacterSet.alphanumerics.contains($0) }
            .map { Character($0).lowercased() }
            .joined()
    }

    private func initials(from code: String) -> String {
        code.split { scalar in
            scalar == " " || scalar == "'" || scalar == "-" || scalar == "_"
        }
        .compactMap { part -> Character? in
            normalizePinyinCode(String(part)).first
        }
        .map { String($0).lowercased() }
        .joined()
    }

    private func bucketKey(_ value: String) -> String {
        String(value.prefix(2))
    }

    private func commonnessPenalty(_ text: String) -> Int {
        var penalty = 0
        for scalar in text.unicodeScalars {
            if scalar.value >= 0x4E00 && scalar.value <= 0x9FFF {
                continue
            }
            if scalar.isASCII && CharacterSet.alphanumerics.contains(scalar) {
                continue
            }
            penalty += 1
        }
        return penalty
    }

    private static func resolveDictionaryPaths(
        configuredPath: String?,
        configuredPaths: String?,
        configuredDirectory: String?,
        defaultDirectory: String
    ) -> [String] {
        let fileManager = FileManager.default
        var paths: [String] = []
        if let configuredPaths {
            paths.append(contentsOf: configuredPaths.split(separator: ":").map(String.init))
        }
        if let configuredPath {
            paths.append(configuredPath)
        }
        if let configuredDirectory {
            paths.append(contentsOf: dictionaryEntryPoints(in: configuredDirectory))
        }
        if paths.isEmpty {
            paths.append(contentsOf: dictionaryEntryPoints(in: defaultDirectory))
        }

        var expanded: [String] = []
        var visited = Set<String>()
        for path in paths where fileManager.fileExists(atPath: path) {
            expanded.append(contentsOf: expandDictionary(path: path, visited: &visited))
        }
        return stableUnique(expanded.filter { fileManager.fileExists(atPath: $0) })
    }

    private static func dictionaryEntryPoints(in directory: String) -> [String] {
        [
            "\(directory)/wanxiang.dict.yaml",
            "\(directory)/custom/wanxiang_pro.dict.yaml",
            "\(directory)/custom/wanxiang_pure.dict.yaml",
            "\(directory)/luna_pinyin.dict.yaml",
        ].filter { FileManager.default.fileExists(atPath: $0) }
    }

    private static func expandDictionary(path: String, visited: inout Set<String>) -> [String] {
        let standardized = URL(fileURLWithPath: path).standardizedFileURL.path
        guard !visited.contains(standardized) else {
            return []
        }
        visited.insert(standardized)
        let imports = importTables(from: standardized)
        guard !imports.isEmpty else {
            return [standardized]
        }
        let baseURL = URL(fileURLWithPath: standardized).deletingLastPathComponent()
        let parentURL = baseURL.deletingLastPathComponent()
        var paths: [String] = [standardized]
        for table in imports {
            let candidates: [URL]
            if table.hasPrefix("/") {
                candidates = [URL(fileURLWithPath: table)]
            } else {
                candidates = [
                    baseURL.appendingPathComponent("\(table).dict.yaml"),
                    parentURL.appendingPathComponent("\(table).dict.yaml"),
                ]
            }
            if let found = candidates.first(where: { FileManager.default.fileExists(atPath: $0.path) }) {
                paths.append(contentsOf: expandDictionary(path: found.path, visited: &visited))
            }
        }
        return paths
    }

    private static func importTables(from path: String) -> [String] {
        guard let content = try? String(contentsOfFile: path, encoding: .utf8) else {
            return []
        }
        var inImports = false
        var imports: [String] = []
        for rawLine in content.split(separator: "\n", omittingEmptySubsequences: false).map(String.init) {
            let line = rawLine.split(separator: "#", maxSplits: 1, omittingEmptySubsequences: false).first.map(String.init) ?? ""
            let trimmed = line.trimmingCharacters(in: .whitespacesAndNewlines)
            if trimmed == "import_tables:" {
                inImports = true
                continue
            }
            guard inImports else {
                continue
            }
            if trimmed.hasPrefix("-") {
                let table = String(trimmed.dropFirst()).trimmingCharacters(in: .whitespacesAndNewlines)
                if !table.isEmpty {
                    imports.append(table)
                }
                continue
            }
            if !trimmed.isEmpty {
                break
            }
        }
        return imports
    }

    private static func stableUnique(_ paths: [String]) -> [String] {
        var seen = Set<String>()
        var result: [String] = []
        for path in paths {
            let standardized = URL(fileURLWithPath: path).standardizedFileURL.path
            guard !seen.contains(standardized) else {
                continue
            }
            seen.insert(standardized)
            result.append(standardized)
        }
        return result
    }
}
