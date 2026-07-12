import Foundation

enum RagImeAssistantSurfaceState: String {
  case hidden
  case pendingPrediction
  case compactPrediction
  case expandedPredictions
  case explicitGenerating
  case explicitError
  case explicitResult
  case transientConfirmation

  var isExplicit: Bool {
    switch self {
    case .explicitGenerating, .explicitError, .explicitResult, .transientConfirmation: return true
    default: return false
    }
  }
}
