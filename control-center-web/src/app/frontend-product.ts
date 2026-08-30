export type FrontendProduct = 'legacy' | 'paw-os';

type FrontendProductSource = {
  buildChannel?: string | null;
  configured?: string | null;
  search?: string;
};

const FRONTEND_QUERY_KEY = 'frontend';

export function resolveFrontendProduct({
  buildChannel,
  configured,
  search = '',
}: FrontendProductSource = {}): FrontendProduct {
  const channel = buildChannel?.trim() || import.meta.env.VITE_BUILD_CHANNEL?.trim() || 'preview';
  const queryValue = new URLSearchParams(search).get(FRONTEND_QUERY_KEY)?.trim();
  const candidate = queryValue || configured?.trim() || 'paw-os';

  if (candidate === 'legacy' || candidate === 'paw-os') {
    if (channel === 'production' && candidate === 'legacy') {
      throw new Error('Legacy frontend product is only available outside production');
    }
    return candidate;
  }

  throw new Error(`Unsupported frontend product: ${candidate}`);
}
