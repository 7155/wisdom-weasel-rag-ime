export {
  captureTranscriptAnchor,
  resolveAnchorRowIndex,
  resolveAnchorScrollTop,
  type AnchorRestoreSource,
  type AnchorRowRestore,
  type AnchorScrollRestore,
  type TranscriptAnchor,
  type TranscriptRowGeometry,
} from './message-anchor';
export {
  createChatPerformanceMarker,
  measureAgentChatOperation,
  measureAgentChatOperationAsync,
  messageLengthBucket,
  noopAgentChatTelemetrySink,
  observeAgentChatLongTasks,
  performanceMarkTelemetrySink,
  type AgentChatPerformanceSample,
  type AgentChatTelemetrySink,
  type ChatPerformanceMarker,
  type LongTaskObserverHandle,
} from './telemetry';
