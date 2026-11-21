import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, expect, test, vi } from 'vitest';

import { Avatar } from './Avatar';
import { CelebrationOverlay } from './CelebrationOverlay';
import { AttributeChip, DifficultyChip } from './chips';
import { GoldBadge } from './GoldBadge';
import { XpBar } from './XpBar';

const confetti = vi.hoisted(() => vi.fn());
vi.mock('canvas-confetti', () => ({ default: confetti }));

afterEach(() => {
  confetti.mockClear();
  vi.unstubAllGlobals();
});

function stubReducedMotion(reduce: boolean) {
  vi.stubGlobal('matchMedia', (query: string) => ({
    matches: reduce && query.includes('reduce'),
    media: query,
    addEventListener() {},
    removeEventListener() {},
  }));
}

test('XpBar exposes level, xp text and progressbar values', () => {
  render(<XpBar level={3} current={40} max={100} />);
  expect(screen.getAllByText('Level 3').length).toBeGreaterThan(0);
  expect(screen.getByText('40 / 100 XP')).toBeInTheDocument();
  const bar = screen.getByRole('progressbar');
  expect(bar).toHaveAttribute('aria-valuenow', '40');
  expect(bar).toHaveAttribute('aria-valuemax', '100');
});

test('XpBar clamps overflow and a zero max', () => {
  const { rerender } = render(<XpBar level={1} current={150} max={100} />);
  expect(screen.getByRole('progressbar')).toHaveAttribute('aria-valuenow', '100');
  rerender(<XpBar level={1} current={5} max={0} />);
  expect(screen.getByRole('progressbar').firstElementChild).toHaveStyle({ width: '0%' });
});

test('GoldBadge shows the amount with an accessible label', () => {
  render(<GoldBadge amount={120} />);
  expect(screen.getByLabelText('120 gold')).toHaveTextContent('120');
});

test('AttributeChip is a label, or a toggle button when selectable', () => {
  const onSelect = vi.fn();
  const { rerender } = render(<AttributeChip attribute="physical" />);
  expect(screen.getByText('Physical').tagName).toBe('SPAN');
  rerender(<AttributeChip attribute="physical" selected onSelect={onSelect} />);
  const button = screen.getByRole('button', { name: 'Physical' });
  expect(button).toHaveAttribute('aria-pressed', 'true');
  fireEvent.click(button);
  expect(onSelect).toHaveBeenCalledTimes(1);
});

test('DifficultyChip renders each difficulty label', () => {
  render(
    <>
      <DifficultyChip difficulty="easy" />
      <DifficultyChip difficulty="epic" selected onSelect={() => {}} />
    </>,
  );
  expect(screen.getByText('Easy')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: 'Epic' })).toHaveAttribute('aria-pressed', 'true');
});

test('Avatar falls back to the initial when there is no image or it fails', () => {
  const { rerender } = render(<Avatar name="alice" />);
  expect(screen.getByRole('img', { name: 'alice' })).toHaveTextContent('A');
  rerender(<Avatar name="alice" src="/x.png" />);
  const img = screen.getByRole('img', { name: 'alice' });
  expect(img.tagName).toBe('IMG');
  fireEvent.error(img);
  expect(screen.getByRole('img', { name: 'alice' })).toHaveTextContent('A');
});

test('CelebrationOverlay animates and fires confetti normally', () => {
  stubReducedMotion(false);
  const onDone = vi.fn();
  render(<CelebrationOverlay open kind="levelUp" detail="Level 2" onDone={onDone} />);
  expect(screen.getByRole('alertdialog')).toHaveAttribute('data-animated', 'true');
  expect(screen.getByText('Level up!')).toBeInTheDocument();
  expect(confetti).toHaveBeenCalledTimes(1);
  fireEvent.click(screen.getByRole('button', { name: 'Continue' }));
  expect(onDone).toHaveBeenCalled();
});

test('CelebrationOverlay does not animate under reduced motion', () => {
  stubReducedMotion(true);
  render(<CelebrationOverlay open kind="questComplete" onDone={() => {}} />);
  expect(screen.getByRole('alertdialog')).toHaveAttribute('data-animated', 'false');
  expect(screen.getByText('Quest complete!')).not.toHaveClass('animate-bounce');
  expect(confetti).not.toHaveBeenCalled();
});

test('CelebrationOverlay renders nothing when closed', () => {
  render(<CelebrationOverlay open={false} kind="purchase" onDone={() => {}} />);
  expect(screen.queryByRole('alertdialog')).toBeNull();
});
