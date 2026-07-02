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
    private let essayPath: String?
    private let dictionaryLabel: String
    private var cachedEntries: [Entry]?

    init(environment: [String: String] = ProcessInfo.processInfo.environment) {
        let configured = environment["RAG_IME_RIME_DICT_PATH"].flatMap { $0.isEmpty ? nil : $0 }
        let configuredEssay = environment["RAG_IME_RIME_ESSAY_PATH"].flatMap { $0.isEmpty ? nil : $0 }
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let candidates = [
            configured,
            "\(home)/Library/Rime/wanxiang.dict.yaml",
            "\(home)/Library/Rime/luna_pinyin.dict.yaml",
        ].compactMap { $0 }
        self.dictionaryPath = candidates.first { FileManager.default.fileExists(atPath: $0) }
        let essayCandidates = [
            configuredEssay,
            "\(home)/Library/Rime/essay.txt",
        ].compactMap { $0 }
        self.essayPath = essayCandidates.first { FileManager.default.fileExists(atPath: $0) }
        if let dictionaryPath, dictionaryPath.localizedCaseInsensitiveContains("wanxiang") {
            self.dictionaryLabel = "wanxiang"
        } else {
            self.dictionaryLabel = "rime"
        }
    }

    func candidates(for rawInput: String, maxCount: Int = 8) -> [RimeCandidatePayload] {
        let query = normalizedQuery(rawInput)
        guard !query.isEmpty, let entries = loadEntries() else {
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
        guard let dictionaryPath, let content = try? String(contentsOfFile: dictionaryPath, encoding: .utf8) else {
            cachedEntries = []
            return cachedEntries
        }
        let essayWeights = loadEssayWeights()
        var inBody = false
        var entries: [Entry] = []
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
        cachedEntries = entries
        return entries
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
        value.unicodeScalars
            .filter { CharacterSet.alphanumerics.contains($0) }
            .map { Character($0).lowercased() }
            .joined()
    }

    private func initials(from code: String) -> String {
        code.split { scalar in
            scalar == " " || scalar == "'" || scalar == "-" || scalar == "_"
        }
        .compactMap { part -> Character? in
            part.first
        }
        .map { String($0).lowercased() }
        .joined()
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
}
