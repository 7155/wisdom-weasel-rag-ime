import SwiftUI

enum ControlDestination: String, CaseIterable, Identifiable {
    case overview
    case inputMethod
    case memory
    case ragAndModels
    case history
    case diagnostics

    var id: String { rawValue }

    var title: String {
        switch self {
        case .overview: return "概览"
        case .inputMethod: return "输入法"
        case .memory: return "记忆"
        case .ragAndModels: return "RAG 与模型"
        case .history: return "历史与反馈"
        case .diagnostics: return "诊断与修复"
        }
    }

    var symbol: String {
        switch self {
        case .overview: return "gauge.with.dots.needle.67percent"
        case .inputMethod: return "keyboard"
        case .memory: return "brain.head.profile"
        case .ragAndModels: return "point.3.connected.trianglepath.dotted"
        case .history: return "clock.arrow.circlepath"
        case .diagnostics: return "stethoscope"
        }
    }
}
