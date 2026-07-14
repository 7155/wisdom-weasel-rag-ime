import SwiftUI

@MainActor
final class ControlNavigationModel: ObservableObject {
    @Published var destination: ControlDestination = .overview
}

enum ControlDestination: String, CaseIterable, Identifiable {
    case overview
    case inputMethod
    case voiceInput
    case planning
    case assistant
    case memory
    case ragAndModels
    case history
    case diagnostics
    case configuration

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: return "概览"
        case .inputMethod: return "输入法"
        case .voiceInput: return "语音输入"
        case .planning: return "规划与任务"
        case .assistant: return "智能对话"
        case .memory: return "记忆"
        case .ragAndModels: return "RAG 与模型"
        case .history: return "历史与反馈"
        case .diagnostics: return "诊断与修复"
        case .configuration: return "配置与迁移"
        }
    }

    var symbol: String {
        switch self {
        case .overview: return "gauge.with.dots.needle.67percent"
        case .inputMethod: return "keyboard"
        case .voiceInput: return "waveform.and.mic"
        case .planning: return "checklist"
        case .assistant: return "sparkles.rectangle.stack"
        case .memory: return "brain.head.profile"
        case .ragAndModels: return "point.3.connected.trianglepath.dotted"
        case .history: return "clock.arrow.circlepath"
        case .diagnostics: return "stethoscope"
        case .configuration: return "gearshape.2"
        }
    }
}
