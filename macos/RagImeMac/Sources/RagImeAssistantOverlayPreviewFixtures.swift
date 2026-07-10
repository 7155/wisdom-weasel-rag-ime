import Foundation

enum RagImeAssistantOverlayPreviewFixtures {
    static let compactOneCandidate = payload(
        mode: "compact_prediction",
        phase: "post_commit",
        candidates: [candidate(text: "优先整理内容结构", source: "model", rank: 1)]
    )

    static let expandedThreeCandidates = payload(
        mode: "expanded_predictions",
        phase: "post_commit",
        candidates: [
            candidate(text: "优先整理内容结构", source: "model", rank: 1),
            candidate(text: "先完成真实前台链路", source: "rag", rank: 2),
            candidate(text: "避免跨文档记忆污染", source: "memory", rank: 3),
        ]
    )

    static let explicitGenerating = payload(
        mode: "active_rag_thinking",
        phase: "active_rag",
        status: "正在生成...",
        animation: "thinking_dots",
        candidates: []
    )

    static let explicitResult = payload(
        mode: "active_rag_ready",
        phase: "active_rag",
        status: "已生成",
        candidates: [
            candidate(text: "建议先完成真实前台链路，再统一整理内容结构。", source: "rag", rank: 1)
        ]
    )

    private static func payload(
        mode: String,
        phase: String,
        status: String = "",
        animation: String = "none",
        candidates: [RimeDisplayCandidate]
    ) -> RagImeAssistantOverlayPayload {
        RagImeAssistantOverlayPayload(
            schemaVersion: "rag-ime.assistant-overlay.v1",
            visible: true,
            uiMode: mode,
            phase: phase,
            inputMode: phase == "active_rag" ? "active_rag_assist" : "post_commit_predicting",
            statusText: status,
            animation: RagImeAssistantOverlayAnimation(kind: animation, frame: 0),
            candidates: candidates,
            sourceCards: [],
            snapshotId: "preview-\(mode)",
            sessionFingerprint: "preview",
            expiresAfterMs: 8_000,
            keyPolicy: RimeKeyPolicyPayload(
                numberKeys: "pass_through",
                tab: "accept_top_prediction",
                optionNumber: "select_prediction_by_ordinal",
                escape: "dismiss_prediction"
            ),
            progressive: nil,
            frontendTransaction: nil,
            dismissReason: ""
        )
    }

    private static func candidate(text: String, source: String, rank: Int) -> RimeDisplayCandidate {
        RimeDisplayCandidate(
            label: "",
            selectionKey: nil,
            selectionRank: rank,
            text: text,
            insertText: text,
            sourceType: source,
            selectionAction: "commit_side_candidate",
            sourceIndex: rank - 1,
            comment: "",
            evidencePreview: source == "rag" ? "本地检索依据" : "",
            expandedEvidence: nil,
            suggestionId: "preview-\(source)-\(rank)",
            memoryId: "",
            sourceEventId: nil,
            rimeIndex: nil,
            displayLayout: "inline",
            displayLane: "assistant_overlay",
            metadata: [:]
        )
    }
}
