import { readFile } from 'node:fs/promises';
import process from 'node:process';
import { pathToFileURL } from 'node:url';

const MAX_REQUEST_BYTES = 64 * 1024;
const MAX_MODELS_PER_PROVIDER = 120;
const PROVIDER_ID_PATTERN = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/;

function emit(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

function publicError(error) {
  const raw = error instanceof Error ? error.message : String(error);
  return raw
    .replace(/(?:sk|key|token|bearer)[-_A-Za-z0-9.]{8,}/gi, '[redacted]')
    .replace(/[\r\n\t]+/g, ' ')
    .slice(0, 300) || 'Pi provider operation failed';
}

async function readRequest() {
  const chunks = [];
  let size = 0;
  for await (const chunk of process.stdin) {
    size += chunk.length;
    if (size > MAX_REQUEST_BYTES) throw new Error('request is too large');
    chunks.push(chunk);
  }
  const text = Buffer.concat(chunks).toString('utf8');
  const request = JSON.parse(text || '{}');
  if (!request || typeof request !== 'object' || Array.isArray(request)) {
    throw new Error('request must be an object');
  }
  return request;
}

function requiredString(request, key, maximum = 4096) {
  const value = typeof request[key] === 'string' ? request[key].trim() : '';
  if (!value || value.length > maximum) throw new Error(`${key} is invalid`);
  return value;
}

function providerId(request) {
  const value = requiredString(request, 'provider', 128);
  if (!PROVIDER_ID_PATTERN.test(value)) throw new Error('provider is invalid');
  return value;
}

async function loadPi(request) {
  const packageEntry = requiredString(request, 'packageEntry', 4096);
  const imported = await import(pathToFileURL(packageEntry).href);
  if (typeof imported.AuthStorage !== 'function' || typeof imported.ModelRegistry !== 'function') {
    throw new Error('managed Pi package does not export credential services');
  }
  const agentDir = requiredString(request, 'agentDir', 4096);
  const auth = imported.AuthStorage.create(`${agentDir}/auth.json`);
  const registry = imported.ModelRegistry.create(auth, `${agentDir}/models.json`);
  return { auth, registry };
}

async function configuredProviderIds(request) {
  const ids = new Set();
  try {
    const raw = await readFile(`${requiredString(request, 'agentDir', 4096)}/models.json`, 'utf8');
    const parsed = JSON.parse(raw);
    const providers = parsed && typeof parsed === 'object' ? parsed.providers : undefined;
    if (providers && typeof providers === 'object' && !Array.isArray(providers)) {
      for (const id of Object.keys(providers)) ids.add(id);
    }
  } catch {
    // ModelRegistry reports a public load error; provider discovery stays fail-open.
  }
  return ids;
}

function providerCatalog(auth, registry, configuredIds) {
  const models = registry.getAll();
  const oauthProviders = new Map(auth.getOAuthProviders().map((provider) => [provider.id, provider]));
  const ids = new Set([
    ...models.map((model) => model.provider),
    ...auth.list(),
    ...oauthProviders.keys(),
    ...configuredIds,
  ]);
  const providers = [];
  for (const id of [...ids].sort((left, right) => left.localeCompare(right))) {
    const providerModels = models.filter((model) => model.provider === id);
    const available = providerModels.filter((model) => registry.hasConfiguredAuth(model));
    const credential = auth.get(id);
    const status = registry.getProviderAuthStatus(id);
    const oauth = oauthProviders.get(id);
    providers.push({
      id,
      name: registry.getProviderDisplayName(id),
      auth: {
        configured: Boolean(status.configured || available.length),
        type: credential?.type ?? '',
        source: status.source ?? '',
        sourceLabel: status.label ?? '',
        oauthSupported: Boolean(oauth),
        oauthDeviceCodeSupported: id === 'openai-codex',
        ...(credential?.type === 'oauth'
          ? { expiresAtMs: Number.isFinite(credential.expires) ? credential.expires : 0 }
          : {}),
      },
      configuredInCatalog: configuredIds.has(id),
      modelCount: providerModels.length,
      availableModelCount: available.length,
      availableModels: available.slice(0, MAX_MODELS_PER_PROVIDER).map((model) => ({
        id: model.id,
        name: model.name,
        reasoning: Boolean(model.reasoning),
        imageInput: Array.isArray(model.input) && model.input.includes('image'),
      })),
      modelsTruncated: available.length > MAX_MODELS_PER_PROVIDER,
    });
  }
  return providers;
}

async function catalog(request) {
  const { auth, registry } = await loadPi(request);
  const configuredIds = await configuredProviderIds(request);
  return {
    event: 'result',
    ok: true,
    providers: providerCatalog(auth, registry, configuredIds),
    catalogError: registry.getError() || '',
  };
}

async function setApiKey(request) {
  const provider = providerId(request);
  const apiKey = requiredString(request, 'apiKey', 16 * 1024);
  const { auth, registry } = await loadPi(request);
  const known = new Set([
    ...registry.getAll().map((model) => model.provider),
    ...auth.getOAuthProviders().map((item) => item.id),
    ...(await configuredProviderIds(request)),
  ]);
  if (!known.has(provider)) throw new Error('provider is not in the Pi model catalog');
  const beforeType = auth.get(provider)?.type ?? '';
  auth.set(provider, { type: 'api_key', key: apiKey });
  const errors = auth.drainErrors();
  if (errors.length) throw errors[0];
  return { event: 'result', ok: true, provider, beforeType, authType: 'api_key' };
}

async function logout(request) {
  const provider = providerId(request);
  const { auth } = await loadPi(request);
  const beforeType = auth.get(provider)?.type ?? '';
  auth.logout(provider);
  const errors = auth.drainErrors();
  if (errors.length) throw errors[0];
  return { event: 'result', ok: true, provider, beforeType, authType: '' };
}

async function oauthDeviceCode(request) {
  const provider = providerId(request);
  if (provider !== 'openai-codex') throw new Error('device-code login is unavailable for this provider');
  const { auth } = await loadPi(request);
  const oauthProvider = auth.getOAuthProviders().find((item) => item.id === provider);
  if (!oauthProvider) throw new Error('OAuth provider is unavailable in the managed Pi package');
  emit({ event: 'state', state: 'starting', provider });
  await auth.login(provider, {
    onAuth: (info) => emit({ event: 'auth_url', url: info.url, instructions: info.instructions || '' }),
    onDeviceCode: (info) => emit({
      event: 'device_code',
      userCode: info.userCode,
      verificationUri: info.verificationUri,
      intervalSeconds: info.intervalSeconds ?? 0,
      expiresInSeconds: info.expiresInSeconds ?? 0,
    }),
    onPrompt: async () => { throw new Error('interactive OAuth input is unavailable'); },
    onProgress: (message) => emit({ event: 'progress', message: String(message).slice(0, 200) }),
    onSelect: async () => 'device_code',
  });
  const errors = auth.drainErrors();
  if (errors.length) throw errors[0];
  emit({ event: 'completed', ok: true, provider });
}

async function main() {
  const request = await readRequest();
  switch (request.action) {
    case 'catalog':
      emit(await catalog(request));
      return;
    case 'set_api_key':
      emit(await setApiKey(request));
      return;
    case 'logout':
      emit(await logout(request));
      return;
    case 'oauth_device_code':
      await oauthDeviceCode(request);
      return;
    default:
      throw new Error('action is not allowed');
  }
}

main().catch((error) => {
  emit({ event: 'failed', ok: false, error: publicError(error) });
  process.exitCode = 1;
});
