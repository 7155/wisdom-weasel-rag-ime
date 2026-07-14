const allowedTransports = new Set(['mock', 'http', 'native']);

export function bootstrapControlCenter(): void {
  const requestedTransport = import.meta.env.VITE_CONTROL_TRANSPORT ?? 'mock';
  const transport = allowedTransports.has(requestedTransport)
    ? requestedTransport
    : 'mock';

  document.documentElement.dataset.controlTransport = transport;
  document.documentElement.dataset.buildChannel =
    import.meta.env.VITE_BUILD_CHANNEL ?? 'dev';
}
