export type AgentSurfaceLayout = {
  compact: boolean;
  overlayInspectors: boolean;
};

export function resolveAgentSurfaceLayout({
  browserMobile,
  browserStatusOverlay,
  surface,
}: {
  browserMobile: boolean;
  browserStatusOverlay: boolean;
  surface: { width: number } | null;
}): AgentSurfaceLayout {
  return {
    compact: browserMobile || (surface?.width !== undefined && surface.width <= 760),
    overlayInspectors: browserStatusOverlay || (surface?.width !== undefined && surface.width <= 1120),
  };
}
