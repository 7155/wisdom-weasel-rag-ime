import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Field } from './Field';
import { Select } from './Select';

afterEach(cleanup);

const options = [
  { value: 'a', label: '产品资料库' },
  { value: 'b', label: '会议纪要' },
] as const;

describe('Select inside a Field', () => {
  it('answers to the field label instead of naming itself after its own value', () => {
    render(
      <Field htmlFor="library" label="当前知识库">
        <Select id="library" onValueChange={() => undefined} options={options} value="a" />
      </Field>,
    );

    // A `<label for>` cannot reach the Radix trigger, because the trigger is a
    // button; without the field label the control would announce as 产品资料库.
    const trigger = screen.getByRole('combobox', { name: '当前知识库' });
    expect(trigger).toHaveTextContent('产品资料库');
  });

  it('lets an explicit aria-label win over the surrounding field label', () => {
    render(
      <Field htmlFor="library" label="当前知识库">
        <Select aria-label="切换知识库" id="library" onValueChange={() => undefined} options={options} value="a" />
      </Field>,
    );

    expect(screen.getByRole('combobox', { name: '切换知识库' })).toBeInTheDocument();
  });

  it('keeps naming itself from its value when it stands outside a field', () => {
    render(<Select id="library" onValueChange={() => undefined} options={options} value="a" />);

    // No dangling aria-labelledby: an unreachable reference would blank the
    // name out entirely, which is worse than falling back to the value.
    expect(screen.getByRole('combobox')).not.toHaveAttribute('aria-labelledby');
  });

  it('keeps a portalled option interactive inside the desktop lasso boundary', async () => {
    const user = userEvent.setup();
    const onValueChange = vi.fn();
    render(
      <div onPointerDown={(event) => {
        const target = event.target as HTMLElement;
        if (!target.closest('[data-paw-desktop-ui]')) event.preventDefault();
      }}>
        <Select aria-label="切换知识库" onValueChange={onValueChange} options={options} value="a" />
      </div>,
    );

    await user.click(screen.getByRole('combobox', { name: '切换知识库' }));
    expect(await screen.findByRole('listbox')).toHaveAttribute('data-paw-desktop-ui');
    await user.click(await screen.findByRole('option', { name: '会议纪要' }));

    expect(onValueChange).toHaveBeenCalledWith('b');
  });
});
