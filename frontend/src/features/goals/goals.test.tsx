import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { expect, test, vi } from 'vitest';

import { ApiError } from '../../lib/api/client';
import { renderApp } from '../../test/harness';
import type { Goal } from './api';

function goal(overrides: Partial<Goal> = {}): Goal {
  return {
    id: 1,
    title: 'Read more books',
    description: null,
    attribute: 'intellectual',
    status: 'active',
    created_at: '2026-01-15T12:00:00Z',
    ...overrides,
  };
}

/** A tiny in-memory /goals backend. */
function goalsBackend(initial: Goal[] = []) {
  let items = [...initial];
  let nextId = 100;
  return {
    'GET /goals': () => items,
    'POST /goals': (body: unknown) => {
      const created = goal({ ...(body as Partial<Goal>), id: nextId++ });
      items = [...items, created];
      return created;
    },
    'PATCH /goals/1': (body: unknown) => {
      items = items.map((g) => (g.id === 1 ? { ...g, ...(body as Partial<Goal>) } : g));
      return items.find((g) => g.id === 1);
    },
    'DELETE /goals/1': () => {
      items = items.filter((g) => g.id !== 1);
      return undefined;
    },
  };
}

test('lists my goals and shows an empty state', async () => {
  renderApp('/me/goals', { routes: { 'GET /goals': [] } });
  expect(await screen.findByText('No goals yet')).toBeInTheDocument();
});

test('adds a goal with an optional attribute (trimmed title)', async () => {
  const { calls } = renderApp('/me/goals', { routes: goalsBackend() });
  await screen.findByText('No goals yet');
  const add = screen.getByTestId('goal-add');
  expect(add).toBeDisabled();
  fireEvent.change(screen.getByLabelText('New goal'), { target: { value: '  Run 5k  ' } });
  fireEvent.click(screen.getByRole('button', { name: 'Physical' }));
  await act(async () => fireEvent.click(add));

  const item = await screen.findByTestId('goal-item');
  expect(item).toHaveTextContent('Run 5k');
  expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ title: 'Run 5k', attribute: 'physical' });
  // The body never carries an owner or server fields.
  expect(Object.keys(calls.find((c) => c.method === 'POST')!.body as object).sort()).toEqual(['attribute', 'title']);
  expect(screen.getByLabelText('New goal')).toHaveValue('');
});

test('archives, restores and deletes (via the in-app confirm sheet, no native dialog)', async () => {
  const confirm = vi.spyOn(window, 'confirm');
  const { calls } = renderApp('/me/goals', { routes: goalsBackend([goal()]) });
  const item = await screen.findByTestId('goal-item');

  await act(async () => fireEvent.click(within(item).getByRole('button', { name: 'Archive' })));
  expect(await screen.findByText('Archived')).toBeInTheDocument();
  expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ status: 'archived' });
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Restore' })));
  await waitFor(() => expect(screen.queryByText('Archived')).toBeNull());

  fireEvent.click(within(screen.getByTestId('goal-item')).getByRole('button', { name: 'Delete' }));
  const sheet = await screen.findByRole('dialog', { name: 'Delete this goal?' });
  await act(async () => fireEvent.click(within(sheet).getByRole('button', { name: 'Delete' })));
  expect(await screen.findByText('No goals yet')).toBeInTheDocument();
  expect(calls.some((c) => c.method === 'DELETE' && c.path === '/goals/1')).toBe(true);
  expect(confirm).not.toHaveBeenCalled();
  confirm.mockRestore();
});

test('cancelling the delete sheet keeps the goal', async () => {
  const { calls } = renderApp('/me/goals', { routes: goalsBackend([goal()]) });
  const item = await screen.findByTestId('goal-item');
  fireEvent.click(within(item).getByRole('button', { name: 'Delete' }));
  fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Cancel' }));
  expect(screen.getByTestId('goal-item')).toBeInTheDocument();
  expect(calls.some((c) => c.method === 'DELETE')).toBe(false);
});

test('shows the limit message on 409', async () => {
  renderApp('/me/goals', {
    routes: {
      'GET /goals': [],
      'POST /goals': () => {
        throw new ApiError(409, 'Too many goals');
      },
    },
  });
  await screen.findByText('No goals yet');
  fireEvent.change(screen.getByLabelText('New goal'), { target: { value: 'one more' } });
  await act(async () => fireEvent.click(screen.getByTestId('goal-add')));
  expect(await screen.findByRole('alert')).toHaveTextContent('maximum number of goals');
});

test('the title input is length-limited like the API', async () => {
  renderApp('/me/goals', { routes: { 'GET /goals': [] } });
  expect(await screen.findByLabelText('New goal')).toHaveAttribute('maxLength', '200');
});
