import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { defaultPawHostPort } from './host-config.mjs';

const contentTypes = new Map([
  ['.css', 'text/css; charset=utf-8'],
  ['.html', 'text/html; charset=utf-8'],
  ['.ico', 'image/x-icon'],
  ['.jpeg', 'image/jpeg'],
  ['.jpg', 'image/jpeg'],
  ['.js', 'text/javascript; charset=utf-8'],
  ['.json', 'application/json; charset=utf-8'],
  ['.png', 'image/png'],
  ['.svg', 'image/svg+xml'],
  ['.webmanifest', 'application/manifest+json; charset=utf-8'],
  ['.woff2', 'font/woff2'],
]);

export async function startPawHostServer({
  browserBridge = null,
  frontendEntry,
  controlOrigin = 'http://127.0.0.1:8768',
  port = defaultPawHostPort,
}) {
  const frontendRoot = path.dirname(frontendEntry);
  const controlUrl = new URL(controlOrigin);
  let hostOrigin = '';
  const server = http.createServer((request, response) => {
    const requestUrl = new URL(request.url || '/', 'http://127.0.0.1');
    if (requestUrl.pathname.startsWith('/__paw_browser/')) {
      void handleBrowserBridgeRequest(request, response, requestUrl.pathname, browserBridge);
      return;
    }
    if (requestUrl.pathname.startsWith('/api/') || requestUrl.pathname.startsWith('/control/')) {
      if (!isAllowedControlRequest(request, hostOrigin)) {
        response.writeHead(403, { 'Content-Type': 'application/json; charset=utf-8' });
        response.end('{"ok":false,"error":"PAW host origin rejected"}\n');
        return;
      }
      proxyControlRequest(request, response, controlUrl);
      return;
    }
    serveFrontend(requestUrl.pathname, response, frontendRoot, frontendEntry);
  });
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(port, '127.0.0.1', resolve);
  });
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('PAWOS host did not bind loopback');
  hostOrigin = `http://127.0.0.1:${address.port}`;
  return {
    close: () => new Promise((resolve) => server.close(resolve)),
    origin: hostOrigin,
  };
}

function isAllowedControlRequest(request, hostOrigin) {
  const expectedHost = new URL(hostOrigin).host;
  if (request.headers.host !== expectedHost) return false;
  const origin = request.headers.origin;
  if (origin && origin !== hostOrigin) return false;
  const fetchSite = request.headers['sec-fetch-site'];
  if (fetchSite && fetchSite !== 'same-origin' && fetchSite !== 'none') return false;
  return ['GET', 'HEAD', 'OPTIONS'].includes(request.method || 'GET') || origin === hostOrigin;
}

async function handleBrowserBridgeRequest(request, response, pathname, bridge) {
  if (!bridge || request.method !== 'POST' || request.headers['x-paw-browser-token'] !== bridge.token) {
    response.writeHead(403).end();
    return;
  }
  let body = '';
  for await (const chunk of request) body += chunk;
  try {
    const input = JSON.parse(body || '{}');
    const result = pathname === '/__paw_browser/tabs'
      ? await bridge.createTab(String(input.url || 'about:blank'))
      : pathname === '/__paw_browser/activate'
        ? await bridge.activateTarget(String(input.targetId || ''))
        : null;
    if (!result) {
      response.writeHead(404).end();
      return;
    }
    response.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(`${JSON.stringify(result)}\n`);
  } catch (error) {
    response.writeHead(500, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end(`${JSON.stringify({ ok: false, error: String(error?.message || error) })}\n`);
  }
}

function proxyControlRequest(request, response, controlUrl) {
  const headers = { ...request.headers };
  headers.host = controlUrl.host;
  if (headers.origin) headers.origin = controlUrl.origin;
  const upstream = http.request({
    hostname: controlUrl.hostname,
    port: controlUrl.port,
    method: request.method,
    path: request.url,
    headers,
  }, (upstreamResponse) => {
    response.writeHead(upstreamResponse.statusCode || 502, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  upstream.on('error', () => {
    if (response.headersSent) return response.destroy();
    response.writeHead(502, { 'Content-Type': 'application/json; charset=utf-8' });
    response.end('{"ok":false,"error":"PAW local authority is unavailable"}\n');
  });
  request.pipe(upstream);
}

function serveFrontend(pathname, response, frontendRoot, frontendEntry) {
  let decoded;
  try {
    decoded = decodeURIComponent(pathname);
  } catch {
    response.writeHead(400).end();
    return;
  }
  const relative = decoded === '/' ? 'index.html' : decoded.replace(/^\/+/, '');
  let target = path.resolve(frontendRoot, relative);
  if (!target.startsWith(`${frontendRoot}${path.sep}`) || !fs.existsSync(target) || !fs.statSync(target).isFile()) {
    target = frontendEntry;
  }
  response.writeHead(200, {
    'Cache-Control': target === frontendEntry ? 'no-store' : 'public, max-age=31536000, immutable',
    'Content-Type': contentTypes.get(path.extname(target).toLowerCase()) || 'application/octet-stream',
    'X-Content-Type-Options': 'nosniff',
  });
  fs.createReadStream(target).pipe(response);
}
