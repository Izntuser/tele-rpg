import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { setLocale } from '../../i18n';
import { makeUser, renderApp, type Routes } from '../../test/harness';
import type { Inbox, NotificationItem, Preferences } from './api';

afterEach(() => {
  setLocale('en');
  vi.restoreAllMocks();
});

function item(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    id: 1,
    type: 'quest_offered',
    category: 'quests',
    entity_type: 'quest_occurrence',
    entity_id: 77,
    payload: { title: 'Morning run', gold: 40 },
    deep_link: 'q_77',
    read_at: null,
    created_at: '2026-01-15T12:00:00Z',
    ...overrides,
  };
}

function inbox(items: NotificationItem[], extra: Partial<Inbox> = {}): Inbox {
  return { items, next_cursor: null, unread_count: items.filter((i) => !i.read_at).length, ...extra };
}

const PREFS: Preferences = {
  categories: { quests: true, reviews: true, rewards: true, reminders: true, summary: true },
  quiet_hours_start: '23:00',
  quiet_hours_end: '08:00',
  daily_summary: true,
  can_message: false,
};

const UNPAIRED = { partnership: null, pending_invitation: null };

describe('header bell', () => {
  test('shows the unread count and opens the inbox', async () => {
    const { router } = renderApp('/', {
      routes: {
        'GET /notifications/unread-count': { count: 3 },
        'GET /notifications?limit=30': inbox([item()]),
      },
    });
    const bell = await screen.findByTestId('notification-bell');
    await waitFor(() => expect(within(bell).getByTestId('notification-badge')).toHaveTextContent('3'));
    expect(bell).toHaveAccessibleName('Notifications, 3 unread');
    await act(async () => fireEvent.click(bell));
    expect(router.state.location.pathname).toBe('/notifications');
    expect(await screen.findByTestId('notification-item')).toBeInTheDocument();
  });

  test('no badge when everything is read, and no bell before onboarding', async () => {
    renderApp('/', { routes: { 'GET /notifications/unread-count': { count: 0 } } });
    const bell = await screen.findByTestId('notification-bell');
    expect(within(bell).queryByTestId('notification-badge')).toBeNull();
    expect(bell).toHaveAccessibleName('Notifications');
  });

  test('a user who is not onboarded sees no bell', async () => {
    renderApp('/onboarding', { user: makeUser({ onboarded_at: null }) });
    await screen.findByTestId('page-onboarding');
    expect(screen.queryByTestId('notification-bell')).toBeNull();
  });
});

describe('inbox page', () => {
  const routes = (extra: Routes = {}): Routes => ({ 'GET /notifications/unread-count': { count: 0 }, ...extra });

  test('lists localized items and tapping one marks it read and opens its screen', async () => {
    const read = vi.fn(() => item({ read_at: '2026-01-15T12:01:00Z' }));
    const { router, adapter } = renderApp('/notifications', {
      routes: routes({
        'GET /notifications?limit=30': inbox([
          item(),
          item({
            id: 2,
            type: 'reward_fulfilled',
            category: 'rewards',
            payload: { title: 'Movie night', price: 40 },
            deep_link: 'r_5',
            read_at: '2026-01-15T11:00:00Z',
          }),
        ]),
        'POST /notifications/1/read': read,
        'GET /quests/77': new Promise(() => {}),
      }),
    });
    const items = await screen.findAllByTestId('notification-item');
    expect(items[0]).toHaveTextContent('New quest offered: Morning run (40 Gold)');
    expect(items[0]).toHaveAttribute('data-unread', 'true');
    expect(items[1]).toHaveTextContent('Your reward was fulfilled: Movie night');
    expect(items[1]).toHaveAttribute('data-unread', 'false');
    await act(async () => fireEvent.click(items[0]!));
    await waitFor(() => expect(read).toHaveBeenCalled());
    expect(router.state.location.pathname).toBe('/quests/77');
    expect(adapter.calls).toContainEqual({ method: 'haptic.selection', args: [] });
  });

  test('a read item opens without another read call; a voucher link opens the inventory', async () => {
    const { router, calls } = renderApp('/notifications', {
      routes: routes({
        'GET /notifications?limit=30': inbox([item({ id: 2, deep_link: 'r_5', read_at: '2026-01-15T11:00:00Z' })]),
        'GET /inventory?limit=200': [],
      }),
    });
    await act(async () => fireEvent.click(await screen.findByTestId('notification-item')));
    expect(router.state.location.pathname).toBe('/shop/inventory');
    expect(router.state.location.search).toBe('?item=5');
    expect(calls.some((c) => c.path.endsWith('/read'))).toBe(false);
  });

  test('renders in Ukrainian and falls back for unknown types', async () => {
    renderApp('/notifications', {
      user: makeUser({ locale: 'uk' }),
      routes: routes({
        'GET /notifications?limit=30': inbox([
          item({ type: 'quest_revision_superseded', payload: { title: 'Біг' } }),
          item({ id: 2, type: 'from_the_future', payload: {} }),
        ]),
      }),
    });
    const items = await screen.findAllByTestId('notification-item');
    expect(items[0]).toHaveTextContent('Твої запропоновані умови для квесту Біг скасовано');
    expect(items[1]).toHaveTextContent('У тебе нове сповіщення.');
  });

  test('mark all as read', async () => {
    const readAll = vi.fn(() => ({ updated: 1 }));
    let page = inbox([item()]);
    renderApp('/notifications', {
      routes: routes({
        'GET /notifications?limit=30': () => page,
        'POST /notifications/read-all': () => {
          page = inbox([item({ read_at: '2026-01-15T12:01:00Z' })]);
          return readAll();
        },
      }),
    });
    await act(async () => fireEvent.click(await screen.findByTestId('notifications-read-all')));
    await waitFor(() => expect(readAll).toHaveBeenCalled());
    await waitFor(() => expect(screen.queryByTestId('notifications-read-all')).toBeNull());
    expect(screen.getByTestId('notification-item')).toHaveAttribute('data-unread', 'false');
  });

  test('loads older pages with the cursor', async () => {
    renderApp('/notifications', {
      routes: routes({
        'GET /notifications?limit=30': inbox([item({ id: 9 })], { next_cursor: 9 }),
        'GET /notifications?limit=30&cursor=9': inbox([item({ id: 3, payload: { title: 'Old one', gold: 1 } })]),
      }),
    });
    await act(async () => fireEvent.click(await screen.findByTestId('notifications-more')));
    await waitFor(() => expect(screen.getAllByTestId('notification-item')).toHaveLength(2));
    expect(screen.getAllByTestId('notification-item')[1]).toHaveTextContent('Old one');
    expect(screen.queryByTestId('notifications-more')).toBeNull();
  });

  test('empty inbox', async () => {
    renderApp('/notifications', { routes: routes({ 'GET /notifications?limit=30': inbox([]) }) });
    expect(await screen.findByText('No notifications yet')).toBeInTheDocument();
  });
});

describe('notification settings', () => {
  function settings(extra: Routes = {}, prefs: Preferences = PREFS) {
    return renderApp('/settings', {
      routes: {
        'GET /partnership': UNPAIRED,
        'GET /notifications/unread-count': { count: 0 },
        'GET /notifications/preferences': prefs,
        ...extra,
      },
    });
  }

  test('toggling a category and the daily summary sends a partial update', async () => {
    const patch = vi.fn((body: unknown) => ({ ...PREFS, ...(body as object), categories: PREFS.categories }));
    const { calls } = settings({ 'PATCH /notifications/preferences': patch });
    const rewards = await screen.findByLabelText('Shop and rewards');
    expect(rewards).toBeChecked();
    await act(async () => fireEvent.click(rewards));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ categories: { rewards: false } });
    await act(async () => fireEvent.click(screen.getByLabelText('Morning summary at 09:00')));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    expect(calls.filter((c) => c.method === 'PATCH')[1]?.body).toEqual({ daily_summary: false });
  });

  test('quiet hours can be changed and turned off', async () => {
    const patch = vi.fn((body: unknown) => ({ ...PREFS, ...(body as object) }));
    const { calls } = settings({ 'PATCH /notifications/preferences': patch });
    const start = await screen.findByTestId('settings-quiet-start');
    expect(start).toHaveValue('23:00');
    await act(async () => fireEvent.change(start, { target: { value: '22:30' } }));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(1));
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({
      quiet_hours_start: '22:30',
      quiet_hours_end: '08:00',
    });
    await act(async () => fireEvent.click(screen.getByTestId('settings-quiet-toggle')));
    await waitFor(() => expect(patch).toHaveBeenCalledTimes(2));
    expect(calls.filter((c) => c.method === 'PATCH')[1]?.body).toEqual({
      quiet_hours_start: null,
      quiet_hours_end: null,
    });
    await waitFor(() => expect(screen.queryByTestId('settings-quiet-start')).toBeNull());
  });

  test('enabling bot messages asks Telegram, then records the answer', async () => {
    const writeAccess = vi.fn((body: unknown) => ({ ...PREFS, can_message: (body as { allowed: boolean }).allowed }));
    const { adapter } = renderApp('/settings', {
      telegram: { writeAccess: true },
      routes: {
        'GET /partnership': UNPAIRED,
        'GET /notifications/unread-count': { count: 0 },
        'GET /notifications/preferences': PREFS,
        'POST /notifications/write-access': writeAccess,
      },
    });
    expect(await screen.findByTestId('settings-bot-status')).toHaveTextContent('cannot message you yet');
    await act(async () => fireEvent.click(screen.getByTestId('settings-enable-bot')));
    await waitFor(() => expect(writeAccess).toHaveBeenCalledWith({ allowed: true }, '/notifications/write-access'));
    expect(adapter.calls.map((c) => c.method)).toContain('requestWriteAccess');
    expect(await screen.findByText('The bot can message you.')).toBeInTheDocument();
    expect(screen.queryByTestId('settings-enable-bot')).toBeNull();
  });

  test('a denied request is recorded and explained', async () => {
    const writeAccess = vi.fn(() => ({ ...PREFS, can_message: false }));
    settings({ 'POST /notifications/write-access': writeAccess });
    await act(async () => fireEvent.click(await screen.findByTestId('settings-enable-bot')));
    await waitFor(() => expect(writeAccess).toHaveBeenCalledWith({ allowed: false }, '/notifications/write-access'));
    expect(await screen.findByText(/did not allow messages/)).toBeInTheDocument();
  });
});
