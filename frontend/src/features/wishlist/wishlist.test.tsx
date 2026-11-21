import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { expect, test } from 'vitest';

import { ApiError } from '../../lib/api/client';
import { renderApp } from '../../test/harness';
import type { WishlistItem } from './api';

function wish(overrides: Partial<WishlistItem> = {}): WishlistItem {
  return {
    id: 1,
    title: 'Breakfast in bed',
    description: null,
    status: 'open',
    linked_reward_id: null,
    ...overrides,
  };
}

function wishlistBackend(initial: WishlistItem[] = []) {
  let items = [...initial];
  let nextId = 100;
  return {
    'GET /wishlist': () => items,
    'POST /wishlist': (body: unknown) => {
      const created = wish({ ...(body as Partial<WishlistItem>), id: nextId++ });
      items = [...items, created];
      return created;
    },
    'PATCH /wishlist/1': (body: unknown) => {
      items = items.map((i) => (i.id === 1 ? { ...i, ...(body as Partial<WishlistItem>) } : i));
      return items.find((i) => i.id === 1);
    },
    'DELETE /wishlist/1': () => {
      items = items.filter((i) => i.id !== 1);
      return undefined;
    },
  };
}

test('shows an empty state', async () => {
  renderApp('/me/wishlist', { routes: { 'GET /wishlist': [] } });
  expect(await screen.findByText('Your wishlist is empty')).toBeInTheDocument();
});

test('adds a wish with an optional description', async () => {
  const { calls } = renderApp('/me/wishlist', { routes: wishlistBackend() });
  await screen.findByText('Your wishlist is empty');
  fireEvent.change(screen.getByLabelText('New wish'), { target: { value: ' Massage ' } });
  fireEvent.change(screen.getByLabelText('Details (optional)'), { target: { value: 'Back and shoulders' } });
  await act(async () => fireEvent.click(screen.getByTestId('wish-add')));
  const item = await screen.findByTestId('wish-item');
  expect(item).toHaveTextContent('Massage');
  expect(item).toHaveTextContent('Back and shoulders');
  expect(calls.find((c) => c.method === 'POST')?.body).toEqual({
    title: 'Massage',
    description: 'Back and shoulders',
  });
});

test('a blank description is sent as null', async () => {
  const { calls } = renderApp('/me/wishlist', { routes: wishlistBackend() });
  await screen.findByText('Your wishlist is empty');
  fireEvent.change(screen.getByLabelText('New wish'), { target: { value: 'Trip' } });
  fireEvent.change(screen.getByLabelText('Details (optional)'), { target: { value: '   ' } });
  await act(async () => fireEvent.click(screen.getByTestId('wish-add')));
  await screen.findByTestId('wish-item');
  expect(calls.find((c) => c.method === 'POST')?.body).toEqual({ title: 'Trip', description: null });
});

test('archives, restores and deletes through the confirm sheet', async () => {
  const { calls } = renderApp('/me/wishlist', { routes: wishlistBackend([wish()]) });
  const item = await screen.findByTestId('wish-item');
  await act(async () => fireEvent.click(within(item).getByRole('button', { name: 'Archive' })));
  expect(await screen.findByText('Archived')).toBeInTheDocument();
  await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Restore' })));
  await waitFor(() => expect(screen.queryByText('Archived')).toBeNull());
  expect(calls.filter((c) => c.method === 'PATCH').map((c) => c.body)).toEqual([
    { status: 'archived' },
    { status: 'open' },
  ]);

  fireEvent.click(within(screen.getByTestId('wish-item')).getByRole('button', { name: 'Delete' }));
  const sheet = await screen.findByRole('dialog', { name: 'Delete this wish?' });
  await act(async () => fireEvent.click(within(sheet).getByRole('button', { name: 'Delete' })));
  expect(await screen.findByText('Your wishlist is empty')).toBeInTheDocument();
});

test('an offered wish is labelled as in the shop', async () => {
  renderApp('/me/wishlist', { routes: { 'GET /wishlist': [wish({ status: 'offered', linked_reward_id: 3 })] } });
  expect(await screen.findByText('In the shop')).toBeInTheDocument();
});

test('deleting a wish that is a shop reward explains why it failed', async () => {
  renderApp('/me/wishlist', {
    routes: {
      'GET /wishlist': [wish({ status: 'offered', linked_reward_id: 3 })],
      'DELETE /wishlist/1': () => {
        throw new ApiError(409, 'Item is linked to a shop reward; archive it instead');
      },
    },
  });
  fireEvent.click(within(await screen.findByTestId('wish-item')).getByRole('button', { name: 'Delete' }));
  await act(async () =>
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Delete' })),
  );
  expect(await screen.findByRole('alert')).toHaveTextContent('already a shop reward');
});

test('shows the limit message on a 409 create', async () => {
  renderApp('/me/wishlist', {
    routes: {
      'GET /wishlist': [],
      'POST /wishlist': () => {
        throw new ApiError(409, 'Too many wishlist items');
      },
    },
  });
  await screen.findByText('Your wishlist is empty');
  fireEvent.change(screen.getByLabelText('New wish'), { target: { value: 'x' } });
  await act(async () => fireEvent.click(screen.getByTestId('wish-add')));
  expect(await screen.findByRole('alert')).toHaveTextContent('maximum number of wishes');
});
