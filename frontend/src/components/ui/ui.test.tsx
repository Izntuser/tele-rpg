import { fireEvent, render, screen } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import { BottomSheet } from './BottomSheet';
import { ConfirmSheet } from './ConfirmSheet';
import { EmptyState } from './EmptyState';
import { StatusPill } from './StatusPill';

test('EmptyState shows a default title, custom text and an action', () => {
  const { rerender } = render(<EmptyState />);
  expect(screen.getByText('Nothing here yet')).toBeInTheDocument();
  rerender(<EmptyState title="No quests" description="Create one" action={<button>New</button>} />);
  expect(screen.getByText('No quests')).toBeInTheDocument();
  expect(screen.getByText('Create one')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'New' })).toBeInTheDocument();
});

test('StatusPill renders the translated status', () => {
  render(<StatusPill status="completed" />);
  expect(screen.getByText('Completed')).toHaveAttribute('data-status', 'completed');
});

test('BottomSheet is hidden when closed and closes on Escape and backdrop', () => {
  const onClose = vi.fn();
  const { rerender } = render(
    <BottomSheet open={false} onClose={onClose} title="Sheet">
      body
    </BottomSheet>,
  );
  expect(screen.queryByRole('dialog')).toBeNull();
  rerender(
    <BottomSheet open onClose={onClose} title="Sheet">
      body
    </BottomSheet>,
  );
  expect(screen.getByRole('dialog', { name: 'Sheet' })).toHaveTextContent('body');
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(onClose).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByTestId('sheet-backdrop'));
  expect(onClose).toHaveBeenCalledTimes(2);
});

test('ConfirmSheet confirms and cancels without window.confirm', () => {
  const confirmSpy = vi.spyOn(window, 'confirm');
  const onConfirm = vi.fn();
  const onCancel = vi.fn();
  render(<ConfirmSheet open title="Sure?" description="Really" onConfirm={onConfirm} onCancel={onCancel} />);
  fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
  expect(onConfirm).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Cancel' }));
  expect(onCancel).toHaveBeenCalledTimes(1);
  expect(confirmSpy).not.toHaveBeenCalled();
  confirmSpy.mockRestore();
});

test('ConfirmSheet typed mode keeps confirm disabled until the exact text is typed', () => {
  const onConfirm = vi.fn();
  render(<ConfirmSheet open title="Delete" requireText="DELETE" destructive onConfirm={onConfirm} onCancel={() => {}} />);
  const button = screen.getByRole('button', { name: 'Confirm' });
  expect(button).toBeDisabled();
  const input = screen.getByLabelText('Type "DELETE" to confirm');
  fireEvent.change(input, { target: { value: 'delete' } });
  expect(button).toBeDisabled();
  fireEvent.change(input, { target: { value: 'DELETE' } });
  expect(button).toBeEnabled();
  fireEvent.click(button);
  expect(onConfirm).toHaveBeenCalledTimes(1);
});
