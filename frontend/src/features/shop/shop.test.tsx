import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { setLocale } from '../../i18n';
import { makeCharacter, renderApp, type Routes } from '../../test/harness';
import type { Reward, Voucher } from './api';
import { buyBlock } from './api';

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));

afterEach(() => {
  setLocale('en');
  vi.restoreAllMocks();
});

const COMPANION = { user_id: 2, display_name: 'Bohdan', avatar_url: null, character_name: 'Bold', nickname: null, level: 3 };
const PAIRED = { partnership: { id: 9, accepted_at: null, companion: COMPANION }, pending_invitation: null };
const UNPAIRED = { partnership: null, pending_invitation: null };
const FUTURE = '2999-01-01T10:00:00Z';

function reward(overrides: Partial<Reward> = {}): Reward {
  return {
    id: 1,
    creator_id: 2,
    title: 'Movie night',
    description: 'Pick the film',
    price: 40,
    image_file_id: null,
    quantity_limit: null,
    quantity_remaining: null,
    cooldown_days: null,
    status: 'active',
    source_wishlist_item_id: null,
    mine: false,
    cooldown_until: null,
    created_at: '2026-01-15T10:00:00Z',
    updated_at: '2026-01-15T10:00:00Z',
    ...overrides,
  };
}

function voucher(overrides: Partial<Voucher> = {}): Voucher {
  return {
    id: 5,
    reward_id: 1,
    buyer_id: 2,
    provider_id: 1,
    side: 'provider',
    price_paid: 40,
    reward: { reward_id: 1, title: 'Movie night', description: null, price: 40, image_file_id: null, cooldown_days: null, quantity_limit: null },
    status: 'requested',
    scheduled_for: null,
    schedule_note: null,
    purchased_at: '2026-01-15T10:00:00Z',
    requested_at: '2026-01-15T11:00:00Z',
    scheduled_at: null,
    fulfilled_at: null,
    disputed_at: null,
    refunded_at: null,
    refunded_by: null,
    frozen: false,
    dispute_until: null,
    ...overrides,
  };
}

const click = (el: HTMLElement) => act(async () => fireEvent.click(el));

function shopRoutes(rewards: Reward[], gold = 75): Routes {
  return {
    'GET /partnership': PAIRED,
    'GET /character': makeCharacter({ gold }),
    'GET /rewards?shop=companion&limit=100': rewards,
  };
}

describe('buyBlock', () => {
  test('orders sold out, cooldown, gold', () => {
    const now = Date.parse('2026-02-01T00:00:00Z');
    expect(buyBlock(reward(), 100, now)).toBeNull();
    expect(buyBlock(reward({ status: 'sold_out' }), 100, now)).toBe('soldOut');
    expect(buyBlock(reward({ quantity_remaining: 0 }), 100, now)).toBe('soldOut');
    expect(buyBlock(reward({ cooldown_until: '2026-03-01T00:00:00Z' }), 100, now)).toBe('cooldown');
    expect(buyBlock(reward({ cooldown_until: '2026-01-01T00:00:00Z' }), 100, now)).toBeNull();
    expect(buyBlock(reward({ price: 40 }), 39, now)).toBe('gold');
    expect(buyBlock(reward({ price: 40 }), undefined, now)).toBeNull();
  });
});

describe('shop page', () => {
  test('the shop switcher is not a nav landmark, so the bottom bar owns aria-current', async () => {
    renderApp('/shop', { routes: shopRoutes([reward()]) });
    await screen.findAllByTestId('reward-card');
    expect(screen.getByTestId('shop-nav-shop')).toHaveAttribute('aria-current', 'page');
    expect(screen.getByTestId('shop-nav-shop').closest('nav')).toBeNull();
    expect(document.querySelectorAll('nav a[aria-current="page"]')).toHaveLength(1);
  });

  test('lists rewards with price, quantity, cooldown and my balance', async () => {
    renderApp('/shop', {
      routes: shopRoutes([
        reward({ id: 1, title: 'Movie night', quantity_limit: 3, quantity_remaining: 2 }),
        reward({ id: 2, title: 'Massage', price: 20, cooldown_until: FUTURE }),
        reward({ id: 3, title: 'Gone', status: 'sold_out', quantity_limit: 1, quantity_remaining: 0 }),
      ]),
    });
    const cards = await screen.findAllByTestId('reward-card');
    expect(cards).toHaveLength(3);
    expect(within(cards[0]!).getByTestId('reward-quantity')).toHaveTextContent('Left: 2');
    expect(within(cards[0]!).getByLabelText('40 gold')).toBeInTheDocument();
    expect(within(cards[0]!).getByTestId('reward-buy')).toBeEnabled();
    expect(within(cards[1]!).getByTestId('reward-quantity')).toHaveTextContent('Unlimited');
    expect(within(cards[1]!).getByTestId('reward-buy')).toBeDisabled();
    expect(within(cards[1]!).getByTestId('reward-reason')).toHaveTextContent('Available again');
    expect(within(cards[2]!).getByTestId('reward-reason')).toHaveTextContent('Sold out');
    await waitFor(() => expect(screen.getByTestId('shop-balance')).toHaveTextContent('75'));
  });

  test('not enough gold disables the button and says how much is missing', async () => {
    renderApp('/shop', { routes: shopRoutes([reward({ price: 100 })], 75) });
    const buy = await screen.findByTestId('reward-buy');
    await waitFor(() => expect(buy).toBeDisabled());
    expect(screen.getByTestId('reward-reason')).toHaveTextContent('Not enough gold: 25 more needed.');
  });

  test('a purchase goes through a ConfirmSheet, celebrates and refreshes the balance', async () => {
    let gold = 75;
    const routes = shopRoutes([reward()]);
    routes['GET /character'] = () => makeCharacter({ gold });
    routes['POST /rewards/1/purchase'] = () => {
      gold = 35;
      return { ...voucher({ side: 'buyer', status: 'purchased' }), balance: 35 };
    };
    const { request, adapter } = renderApp('/shop', { routes });
    const haptic = vi.spyOn(adapter.haptic, 'notification');
    await click(await screen.findByTestId('reward-buy'));

    // Nothing is bought until the sheet is confirmed.
    expect(request).not.toHaveBeenCalledWith('POST', '/rewards/1/purchase', expect.anything());
    const sheet = await screen.findByRole('dialog', { name: 'Buy Movie night?' });
    expect(sheet).toHaveTextContent('This costs 40 gold. You have 75.');
    await click(within(sheet).getByRole('button', { name: 'Buy' }));

    const overlay = await screen.findByRole('alertdialog', { name: 'Reward claimed!' });
    expect(overlay).toHaveTextContent('Balance: 35 gold.');
    const call = request.mock.calls.find((c) => c[1] === '/rewards/1/purchase');
    expect(call?.[2]).toMatchObject({ idempotencyKey: true });
    expect(haptic).toHaveBeenCalledWith('success');
    await waitFor(() => expect(screen.getByTestId('shop-balance')).toHaveTextContent('35'));
  });

  test('an unpaired user sees the invite CTA', async () => {
    renderApp('/shop', { routes: { 'GET /partnership': UNPAIRED, 'GET /character': makeCharacter(), 'GET /rewards?shop=companion&limit=100': [] } });
    expect(await screen.findByText('The shop needs a companion')).toBeInTheDocument();
    expect(screen.getByTestId('invite-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('reward-list')).not.toBeInTheDocument();
  });
});

describe('manage page', () => {
  const manageRoutes = (extra: Routes = {}): Routes => ({
    'GET /partnership': PAIRED,
    'GET /character': makeCharacter(),
    'GET /rewards?shop=mine&limit=100': [reward({ id: 7, mine: true, creator_id: 1, title: 'Breakfast' })],
    'GET /inventory?side=provider&limit=100': [],
    'GET /partnership/companion': { wishlist: [{ id: 4, title: 'Spa day', description: null, status: 'open' }, { id: 5, title: 'Done', description: null, status: 'offered' }] },
    ...extra,
  });

  test('creates a reward from the form', async () => {
    const created = vi.fn(() => reward({ id: 8, title: 'Walk' }));
    const { request } = renderApp('/shop/manage', { routes: manageRoutes({ 'POST /rewards': created }) });
    await screen.findByText('Breakfast');
    await click(screen.getByTestId('reward-add'));
    const save = screen.getByTestId('reward-save');
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByTestId('reward-title'), { target: { value: 'Walk' } });
    fireEvent.change(screen.getByTestId('reward-price'), { target: { value: '15' } });
    fireEvent.change(screen.getByTestId('reward-quantity-limit'), { target: { value: '2' } });
    await click(save);
    await waitFor(() => expect(created).toHaveBeenCalled());
    expect(created).toHaveBeenCalledWith(
      expect.objectContaining({ title: 'Walk', price: 15, quantity_limit: 2, cooldown_days: null, status: 'active' }),
      expect.anything(),
    );
    const call = request.mock.calls.find((c) => c[0] === 'POST' && c[1] === '/rewards');
    expect(call?.[2]).toMatchObject({ idempotencyKey: true });
  });

  test('turns an open wish into a reward and hides a reward', async () => {
    const created = vi.fn(() => reward({ id: 9 }));
    const patched = vi.fn(() => reward({ id: 7, status: 'hidden' }));
    renderApp('/shop/manage', { routes: manageRoutes({ 'POST /rewards': created, 'PATCH /rewards/7': patched }) });
    const wishes = await screen.findAllByTestId('wish-option');
    expect(wishes).toHaveLength(1);
    await click(screen.getByTestId('wish-make-reward'));
    expect(screen.getByTestId('reward-title')).toHaveValue('Spa day');
    fireEvent.change(screen.getByTestId('reward-price'), { target: { value: '30' } });
    await click(screen.getByTestId('reward-save'));
    await waitFor(() => expect(created).toHaveBeenCalled());
    expect(created).toHaveBeenCalledWith(expect.objectContaining({ wishlist_item_id: 4, price: 30 }), expect.anything());

    await click(screen.getByTestId('reward-toggle'));
    await waitFor(() => expect(patched).toHaveBeenCalledWith({ status: 'hidden' }, expect.anything()));
  });

  test('the queue offers schedule, fulfil and refund by status; refund asks first', async () => {
    const schedule = vi.fn(() => voucher({ status: 'scheduled' }));
    const fulfill = vi.fn(() => voucher({ id: 6, status: 'fulfilled' }));
    const refund = vi.fn(() => voucher({ status: 'refunded' }));
    const { request } = renderApp('/shop/manage', {
      routes: manageRoutes({
        'GET /inventory?side=provider&limit=100': [
          voucher({ id: 5, status: 'requested' }),
          voucher({ id: 6, status: 'scheduled', scheduled_for: FUTURE }),
          voucher({ id: 8, status: 'fulfilled' }),
        ],
        'POST /inventory/5/schedule': schedule,
        'POST /inventory/6/fulfill': fulfill,
        'POST /inventory/5/refund': refund,
      }),
    });
    const cards = await screen.findAllByTestId('voucher-card');
    expect(cards).toHaveLength(2);
    expect(within(cards[0]!).queryByTestId('voucher-fulfill')).not.toBeInTheDocument();
    expect(within(cards[1]!).getByTestId('voucher-fulfill')).toBeInTheDocument();

    await click(within(cards[0]!).getByTestId('voucher-schedule-open'));
    const save = screen.getByTestId('schedule-save');
    expect(save).toBeDisabled();
    fireEvent.change(screen.getByTestId('schedule-when'), { target: { value: '2999-01-01T10:00' } });
    fireEvent.change(screen.getByTestId('schedule-note'), { target: { value: 'Bring snacks' } });
    await click(save);
    await waitFor(() => expect(schedule).toHaveBeenCalled());
    expect(schedule).toHaveBeenCalledWith({ scheduled_for: expect.stringMatching(/^2999-01-01T/), note: 'Bring snacks' }, expect.anything());

    await click(within(cards[1]!).getByTestId('voucher-fulfill'));
    await waitFor(() => expect(fulfill).toHaveBeenCalled());

    await click(within(cards[0]!).getByTestId('voucher-refund'));
    expect(refund).not.toHaveBeenCalled();
    const sheet = await screen.findByRole('dialog', { name: 'Refund this reward?' });
    await click(within(sheet).getByRole('button', { name: 'Refund' }));
    await waitFor(() => expect(refund).toHaveBeenCalled());
    expect(request.mock.calls.find((c) => c[1] === '/inventory/5/refund')?.[2]).toMatchObject({ idempotencyKey: true });
  });
});
