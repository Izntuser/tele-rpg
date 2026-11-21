import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { setLocale } from '../../i18n';
import { makeCharacter, renderApp, type Routes } from '../../test/harness';
import type { Voucher } from '../shop/api';
import { voucherActions } from './api';

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));

afterEach(() => {
  setLocale('en');
  vi.restoreAllMocks();
});

const COMPANION = { user_id: 2, display_name: 'Bohdan', avatar_url: null, character_name: 'Bold', nickname: null, level: 3 };
const PAIRED = { partnership: { id: 9, accepted_at: null, companion: COMPANION }, pending_invitation: null };
const NOW = Date.parse('2026-02-01T12:00:00Z');

function voucher(overrides: Partial<Voucher> = {}): Voucher {
  return {
    id: 5,
    reward_id: 1,
    buyer_id: 1,
    provider_id: 2,
    side: 'buyer',
    price_paid: 40,
    reward: { reward_id: 1, title: 'Movie night', description: null, price: 40, image_file_id: null, cooldown_days: null, quantity_limit: null },
    status: 'purchased',
    scheduled_for: null,
    schedule_note: null,
    purchased_at: '2026-01-15T10:00:00Z',
    requested_at: null,
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

describe('voucherActions', () => {
  const buyer = (o: Partial<Voucher>) => voucherActions(voucher(o), 'buyer', NOW);
  const provider = (o: Partial<Voucher>) => voucherActions(voucher({ side: 'provider', ...o }), 'provider', NOW);

  test('the buyer requests or refunds a purchased voucher, nothing else', () => {
    expect(buyer({ status: 'purchased' })).toMatchObject({ request: true, refund: true, dispute: false, schedule: false });
    for (const status of ['requested', 'scheduled', 'refunded', 'cancelled'] as const) {
      expect(Object.values(buyer({ status })).some(Boolean)).toBe(false);
    }
  });

  test('a dispute needs a fulfilled voucher inside the 48h window', () => {
    expect(buyer({ status: 'fulfilled', dispute_until: '2026-02-02T00:00:00Z' }).dispute).toBe(true);
    expect(buyer({ status: 'fulfilled', dispute_until: '2026-01-31T00:00:00Z' }).dispute).toBe(false);
    expect(buyer({ status: 'fulfilled', dispute_until: null }).dispute).toBe(false);
  });

  test('the provider schedules, fulfils and refunds before fulfilment', () => {
    expect(provider({ status: 'requested' })).toMatchObject({ schedule: true, fulfill: false, refund: true });
    expect(provider({ status: 'scheduled' })).toMatchObject({ schedule: true, fulfill: true, refund: true });
    expect(provider({ status: 'purchased' })).toMatchObject({ schedule: false, fulfill: false, refund: true });
    expect(Object.values(provider({ status: 'fulfilled' })).some(Boolean)).toBe(false);
  });

  test('a frozen voucher can only be refunded by its provider', () => {
    expect(buyer({ status: 'purchased', frozen: true })).toMatchObject({ request: false, refund: false });
    expect(provider({ status: 'scheduled', frozen: true })).toMatchObject({ schedule: false, fulfill: false, refund: true });
  });
});

function routes(vouchers: Voucher[], extra: Routes = {}): Routes {
  return {
    'GET /partnership': PAIRED,
    'GET /character': makeCharacter(),
    'GET /inventory?side=buyer&limit=100': vouchers,
    ...extra,
  };
}

describe('inventory page', () => {
  test('groups vouchers by status and offers only the allowed actions', async () => {
    const soon = new Date(Date.now() + 3_600_000).toISOString();
    const past = new Date(Date.now() - 3_600_000).toISOString();
    renderApp('/shop/inventory', {
      routes: routes([
        voucher({ id: 1, status: 'purchased' }),
        voucher({ id: 2, status: 'requested' }),
        voucher({ id: 3, status: 'scheduled', scheduled_for: '2999-01-01T10:00:00Z' }),
        voucher({ id: 4, status: 'fulfilled', fulfilled_at: past, dispute_until: soon }),
        voucher({ id: 6, status: 'fulfilled', fulfilled_at: past, dispute_until: past }),
        voucher({ id: 7, status: 'refunded' }),
      ]),
    });
    await screen.findAllByTestId('voucher-card');
    const group = (status: string) => screen.getByTestId(`voucher-group-${status}`);
    expect(within(group('purchased')).getByTestId('voucher-request')).toBeInTheDocument();
    expect(within(group('purchased')).getByTestId('voucher-refund')).toBeInTheDocument();
    expect(within(group('requested')).queryByRole('button')).not.toBeInTheDocument();
    expect(within(group('scheduled')).getByTestId('voucher-schedule')).toHaveTextContent('Planned for');
    const fulfilled = within(group('fulfilled')).getAllByTestId('voucher-card');
    expect(within(fulfilled[0]!).getByTestId('voucher-dispute')).toBeInTheDocument();
    expect(within(fulfilled[1]!).queryByTestId('voucher-dispute')).not.toBeInTheDocument();
    expect(within(group('refunded')).queryByRole('button')).not.toBeInTheDocument();
  });

  test('request fires at once; refund and dispute ask first', async () => {
    const soon = new Date(Date.now() + 3_600_000).toISOString();
    const request = vi.fn(() => voucher({ id: 1, status: 'requested' }));
    const refund = vi.fn(() => voucher({ id: 1, status: 'refunded' }));
    const dispute = vi.fn(() => voucher({ id: 4, status: 'requested' }));
    const app = renderApp('/shop/inventory', {
      routes: routes([voucher({ id: 1 }), voucher({ id: 4, status: 'fulfilled', fulfilled_at: soon, dispute_until: soon })], {
        'POST /inventory/1/request': request,
        'POST /inventory/1/refund': refund,
        'POST /inventory/4/dispute': dispute,
      }),
    });
    await click(await screen.findByTestId('voucher-request'));
    await waitFor(() => expect(request).toHaveBeenCalled());
    expect(app.request.mock.calls.find((c) => c[1] === '/inventory/1/request')?.[2]).toMatchObject({ idempotencyKey: true });

    await click(screen.getByTestId('voucher-refund'));
    expect(refund).not.toHaveBeenCalled();
    let sheet = await screen.findByRole('dialog', { name: 'Refund this reward?' });
    await click(within(sheet).getByRole('button', { name: 'Refund' }));
    await waitFor(() => expect(refund).toHaveBeenCalled());

    await click(screen.getByTestId('voucher-dispute'));
    expect(dispute).not.toHaveBeenCalled();
    sheet = await screen.findByRole('dialog', { name: 'Dispute this reward?' });
    await click(within(sheet).getByRole('button', { name: 'Dispute' }));
    await waitFor(() => expect(dispute).toHaveBeenCalled());
  });

  test('an empty inventory says so', async () => {
    renderApp('/shop/inventory', { routes: routes([]) });
    expect(await screen.findByText('No vouchers yet')).toBeInTheDocument();
  });
});
