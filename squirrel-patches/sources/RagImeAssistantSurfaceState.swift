import Foundation

enum RagImeAssistantSurfaceState: String {
  case hidden
  case compactPrediction
  case expandedPredictions
  case explicitGenerating
  case explicitResult
  case transientConfirmation

  var isExplicit: Bool {
    switch self {
    case .explicitGenerating, .explicitResult, .transientConfirmation: return true
    default: return false
    }
  }
}
