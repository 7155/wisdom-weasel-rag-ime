/** Product identity shown by both the PAWOS shell and the native host. */
const version = typeof __PAW_PRODUCT_VERSION__ === 'string'
  ? __PAW_PRODUCT_VERSION__.trim()
  : '';
const buildCommit = typeof __PAW_BUILD_COMMIT__ === 'string'
  ? __PAW_BUILD_COMMIT__.trim()
  : '';
const buildNumber = typeof __PAW_BUILD_NUMBER__ === 'string'
  ? __PAW_BUILD_NUMBER__.trim()
  : '';
const sourceDirty = typeof __PAW_SOURCE_DIRTY__ === 'boolean'
  ? __PAW_SOURCE_DIRTY__
  : false;

export const PAW_PRODUCT_VERSION = version || '0.1.0';
export const PAW_BUILD_COMMIT = buildCommit || 'dev';
export const PAW_BUILD_NUMBER = buildNumber || 'dev';
export const PAW_SOURCE_DIRTY = sourceDirty;
export const PAW_PRODUCT_VERSION_LABEL = `v${PAW_PRODUCT_VERSION}`;
export const PAW_PRODUCT_BUILD_LABEL = productBuildLabel(
  PAW_PRODUCT_VERSION,
  PAW_BUILD_NUMBER,
  PAW_SOURCE_DIRTY,
);

/** Keep the visible identity aligned with the plist while making local dirty
 * builds impossible to confuse with the committed build that shares their
 * numeric CFBundleVersion. */
export function productBuildLabel(
  productVersion: string,
  productBuildNumber: string,
  dirty: boolean,
): string {
  const versionLabel = `v${productVersion}`;
  if (productBuildNumber === 'dev') return versionLabel;
  return `${versionLabel} · build ${productBuildNumber}${dirty ? ' · 未提交' : ''}`;
}
