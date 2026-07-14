import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { ControlTransportProvider, useControlTransport } from '@/app/control-transport';

function Probe() {
  const transport = useControlTransport();
  return <output>{transport.kind}</output>;
}

describe('ControlTransportProvider', () => {
  it('provides the preview transport when no native bridge is present', () => {
    render(
      <ControlTransportProvider>
        <Probe />
      </ControlTransportProvider>,
    );
    expect(screen.getByText('mock')).toBeInTheDocument();
  });
});
