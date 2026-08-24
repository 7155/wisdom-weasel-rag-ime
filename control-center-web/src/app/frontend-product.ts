export type FrontendProduct = 'legacy' | 'paw-os';

type FrontendProductSource = {
  configured?: string | null;
  search?: string;
};

const FRONTEND_QUERY_KEY = 'frontend';

export function resolveFrontendProduct({
  configured,
  search = '',
}: FrontendProductSource = {}): FrontendProduct {
  const queryValue = new URLSearchParams(search).get(FRONTEND_QUERY_KEY)?.trim();
  const candidate = queryValue || configured?.trim() || 'paw-os';

  if (candidate === 'legacy' || candidate === 'paw-os') return candidate;

  throw new Error(`Unsupported frontend product: ${candidate}`);
}
