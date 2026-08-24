const allowedTransports = new Set(['mock', 'http', 'native']);

export function bootstrapControlCenter(): void {
  const developmentDefault = import.meta.env.DEV ? 'http' : 'mock';
  const requestedTransport =
    import.meta.env.VITE_CONTROL_TRANSPORT ??
    (window.webkit?.messageHandlers?.ragImeNativeBridge
      ? 'native'
      : import.meta.env.DEV
        ? developmentDefault
        : 'http');
  const transport = allowedTransports.has(requestedTransport)
    ? requestedTransport
    : 'mock';

  document.documentElement.dataset.controlTransport = transport;
  document.documentElement.dataset.buildChannel =
    import.meta.env.VITE_BUILD_CHANNEL ?? 'dev';
}
