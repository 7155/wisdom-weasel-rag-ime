import { describe, expect, it } from 'vitest';
import { productBuildLabel } from './product-identity';

describe('PAW product build identity', () => {
  it('distinguishes an uncommitted local build from the committed build number', () => {
    expect(productBuildLabel('0.1.0', '1425', true)).toBe(
      'v0.1.0 · build 1425 · 未提交',
    );
    expect(productBuildLabel('0.1.0', '1425', false)).toBe(
      'v0.1.0 · build 1425',
    );
  });

  it('keeps the lightweight development label when no package build exists', () => {
    expect(productBuildLabel('0.1.0', 'dev', true)).toBe('v0.1.0');
  });
});
