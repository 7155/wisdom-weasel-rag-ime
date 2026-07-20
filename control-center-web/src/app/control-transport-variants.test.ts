import { describe, expect, it } from 'vitest';
import * as httpTransport from './control-transport.http';
import * as nativeTransport from './control-transport.native';

describe('control transport build variants', () => {
  it.each([
    ['http', httpTransport],
    ['native', nativeTransport],
  ])('%s exports the optional provider hook used by Room panels', (_name, variant) => {
    expect(variant.useOptionalControlTransport).toBeTypeOf('function');
  });
});
