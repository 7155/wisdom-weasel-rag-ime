import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const electronDirectory = path.dirname(fileURLToPath(import.meta.url));

export const browserPartition = 'persist:paw-browser';
export const defaultPawHostPort = 8770;

export function resolveHostPaths(env = process.env) {
  const repositoryRoot = path.resolve(electronDirectory, '..', '..');
  const appSupportRoot = path.resolve(
    env.RAG_IME_APP_SUPPORT_DIR
      || path.join(env.HOME || '', 'Library', 'Application Support', 'RagIme'),
  );
  const profilePath = path.resolve(
    env.PAW_BROWSER_PROFILE_DIR
      || path.join(appSupportRoot, 'Browser', 'runtime-profile'),
  );
  const packagedEntry = path.join(electronDirectory, '..', 'dist', 'index.html');
  const sourceEntry = path.join(repositoryRoot, 'control-center-web', 'dist', 'index.html');
  return {
    frontendEntry: env.PAW_FRONTEND_ENTRY
      ? path.resolve(env.PAW_FRONTEND_ENTRY)
      : fs.existsSync(packagedEntry)
        ? packagedEntry
        : sourceEntry,
    hostPidFile: path.join(profilePath, 'PAWBrowserHost.pid'),
    browserHistoryFile: path.join(profilePath, 'PAWBrowserHost.history.json'),
    browserSettingsFile: path.join(profilePath, 'PAWBrowserHost.settings.json'),
    browserExtensionsDir: path.join(profilePath, 'Extensions'),
    preloadEntry: path.join(electronDirectory, 'preload.cjs'),
    profilePath,
    repositoryRoot,
  };
}

export function isBrowserGuestUrl(rawUrl) {
  try {
    const url = new URL(rawUrl);
    return ['http:', 'https:'].includes(url.protocol) || rawUrl === 'about:blank';
  } catch {
    return false;
  }
}
