import SwiftUI

struct RagImeAssistantOverlayView: View {
    let payload: RagImeAssistantOverlayPayload
    let onSelect: (RimeDisplayCandidate, Int) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            header
            if !payload.statusText.isEmpty {
                Text(statusDisplayText)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }
            ForEach(Array(payload.candidates.prefix(3).enumerated()), id: \.element.candidateStableKey) { index, candidate in
                Button {
                    onSelect(candidate, index)
                } label: {
                    HStack(spacing: 8) {
                        Text(shortcutLabel(for: candidate, fallback: index + 1))
                            .font(.system(size: 11, weight: .semibold, design: .monospaced))
                            .foregroundStyle(.blue)
                            .frame(width: 32, alignment: .leading)
                        Text(candidate.text.isEmpty ? candidate.insertText : candidate.text)
                            .font(.system(size: 13, weight: .medium))
                            .foregroundStyle(.primary)
                            .lineLimit(1)
                        Spacer(minLength: 6)
                        Text(candidate.sourceBadgeText)
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 6)
                    .padding(.horizontal, 8)
                    .background(.quaternary, in: RoundedRectangle(cornerRadius: 7))
                }
                .buttonStyle(.plain)
            }
            if !payload.sourceCards.isEmpty {
                sourceCards
            }
            footer
        }
        .padding(12)
        .frame(width: payload.phase == "post_commit" ? 340 : 460, alignment: .leading)
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .strokeBorder(Color.white.opacity(0.22), lineWidth: 0.8)
        )
        .shadow(color: Color.black.opacity(0.24), radius: 18, y: 8)
    }

    private var header: some View {
        HStack(spacing: 8) {
            Text("AI")
                .font(.system(size: 11, weight: .bold))
                .foregroundStyle(.white)
                .padding(.horizontal, 7)
                .padding(.vertical, 3)
                .background(Color.blue, in: Capsule())
            Text(title)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(.primary)
            if payload.animation.kind == "thinking_dots" {
                Text(String(repeating: "·", count: max(1, min(3, payload.animation.frame + 1))))
                    .font(.system(size: 16, weight: .bold))
                    .foregroundStyle(.secondary)
                    .animation(.easeInOut(duration: 0.2), value: payload.animation.frame)
            }
            Spacer(minLength: 8)
        }
    }

    private var sourceCards: some View {
        VStack(alignment: .leading, spacing: 5) {
            ForEach(payload.sourceCards.prefix(3), id: \.stableKey) { card in
                HStack(spacing: 6) {
                    Text(card.sourceBadge)
                        .font(.system(size: 10, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Text(card.title)
                        .font(.system(size: 11))
                        .foregroundStyle(.secondary)
                        .lineLimit(1)
                }
            }
        }
        .padding(.top, 2)
    }

    private var footer: some View {
        HStack(spacing: 12) {
            Text("Tab 插入")
            Text("⌥数字选择")
            Text("Esc 关闭")
        }
        .font(.system(size: 10, weight: .medium))
        .foregroundStyle(.tertiary)
        .padding(.top, 2)
    }

    private var title: String {
        if payload.uiMode.contains("pending") || payload.animation.kind == "thinking_dots" {
            return "正在生成"
        }
        if payload.candidates.contains(where: { $0.sourceType == "action" }) {
            return "DeepSeek / RAG"
        }
        return "AI 建议"
    }

    private var statusDisplayText: String {
        if payload.animation.kind == "thinking_dots" && payload.statusText.isEmpty {
            return "AI 正在想..."
        }
        return payload.statusText
    }

    private func shortcutLabel(for candidate: RimeDisplayCandidate, fallback: Int) -> String {
        if candidate.sourceType == "action" {
            return "⌃."
        }
        if let rank = candidate.selectionRank, rank > 0 {
            return rank == 1 ? "Tab" : "⌥\(rank)"
        }
        return fallback == 1 ? "Tab" : "⌥\(fallback)"
    }
}

private extension RimeDisplayCandidate {
    var candidateStableKey: String {
        if !suggestionId.isEmpty {
            return "\(sourceType):\(suggestionId)"
        }
        if !memoryId.isEmpty {
            return "\(sourceType):\(memoryId)"
        }
        return "\(sourceType):\(sourceIndex):\(text)"
    }

    var sourceBadgeText: String {
        switch sourceType {
        case "model": return "模型"
        case "rag": return "RAG"
        case "memory": return "记忆"
        case "action": return "生成"
        default: return sourceType
        }
    }
}

private extension RagImeAssistantSourceCard {
    var stableKey: String {
        if !suggestionId.isEmpty {
            return "\(sourceType):\(suggestionId)"
        }
        if !memoryId.isEmpty {
            return "\(sourceType):\(memoryId)"
        }
        return "\(sourceType):\(title)"
    }
}
