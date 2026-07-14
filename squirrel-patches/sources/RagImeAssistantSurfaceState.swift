import AppKit
import QuartzCore

/// AppKit adapter for the shared motion language in macos/Shared/RagImeMotion.swift.
/// Squirrel is patched and built as a separate target, so it cannot import that module.
enum RagImeAssistantMotion {
  enum Duration {
    static let micro: TimeInterval = 0.10
    static let entrance: TimeInterval = 0.14
    static let transition: TimeInterval = 0.18
    static let ambientPulse: TimeInterval = 0.72
  }

  enum Distance {
    static let tiny: CGFloat = 3
    static let small: CGFloat = 5
  }

  static let stagger: TimeInterval = 0.04
  static let confirmationHoldMilliseconds = 360

  static func timingFunction(_ name: CAMediaTimingFunctionName = .easeOut) -> CAMediaTimingFunction {
    CAMediaTimingFunction(name: name)
  }
}

enum RagImeAssistantSurfaceState: String {
  case hidden
  case pendingPrediction
  case compactPrediction
  case expandedPredictions
  case explicitGenerating
  case explicitNoSuggestion
  case explicitError
  case explicitResult
  case transientConfirmation

  var isExplicit: Bool {
    switch self {
    case .explicitGenerating, .explicitNoSuggestion, .explicitError, .explicitResult, .transientConfirmation:
      return true
    default: return false
    }
  }
}
