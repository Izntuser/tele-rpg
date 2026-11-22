import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { setLocale } from '../../i18n';
import { makeCharacter, renderApp, type Routes } from '../../test/harness';
import { ACHIEVEMENTS_KEY, ATTRIBUTES, type Achievements, type LifeBalance, type Stats } from './api';

afterEach(() => setLocale('en'));

function days(n: number, values: Record<number, number> = {}) {
  return Array.from({ length: n }, (_, i) => ({
    date: new Date(Date.UTC(2026, 0, 15 - (n - 1) + i)).toISOString().slice(0, 10),
    value: values[i] ?? 0,
  }));
}

function stats(overrides: Partial<Stats> = {}): Stats {
  return {
    period: '7d',
    since: '2026-01-09',
    quests_completed: 3,
    quests_completed_total: 12,
    quests_completed_week: 3,
    quests_completed_month: 8,
    xp_total: 640,
    xp_period: 170,
    gold_earned: 90,
    gold_spent: 40,
    gold_earned_total: 400,
    gold_spent_total: 120,
    gold_balance: 280,
    rewards_purchased: 1,
    rewards_fulfilled: 1,
    xp_per_day: days(7, { 6: 120, 4: 50 }),
    quests_per_day: days(7, { 6: 2, 4: 1 }),
    ...overrides,
  };
}

function balance(overrides: Partial<LifeBalance> = {}): LifeBalance {
  const scores: Record<string, number> = { physical: 100, intellectual: 0, discipline: 20, social: 60, creativity: 0, wellbeing: 80 };
  return {
    period: '7d',
    user: 'me',
    attributes: ATTRIBUTES.map((attribute) => ({
      attribute,
      earned_xp: scores[attribute]!,
      weekly_target: 100,
      period_target: 100,
      score: scores[attribute]!,
    })),
    suggestions: [
      { attribute: 'intellectual', reason: 'no_activity', score: 0 },
      { attribute: 'creativity', reason: 'no_activity', score: 0 },
      { attribute: 'discipline', reason: 'below_target', score: 20 },
    ],
    balanced: false,
    ...overrides,
  };
}

function achievements(unlocked: string[] = []): Achievements {
  const codes = ['first_quest', 'quests_10', 'quest_giver'];
  return {
    definitions: codes.map((code) => ({
      code,
      icon: 'star',
      target: code === 'quests_10' ? 10 : 1,
      progress: unlocked.includes(code) ? (code === 'quests_10' ? 10 : 1) : code === 'quests_10' ? 3 : 0,
      unlocked_at: unlocked.includes(code) ? '2026-01-15T12:00:00Z' : null,
    })),
    unlocks: unlocked.map((code) => ({ code, unlocked_at: '2026-01-15T12:00:00Z' })),
  };
}

const TARGETS = { targets: Object.fromEntries(ATTRIBUTES.map((a) => [a, 100])) };

function statsRoutes(extra: Routes = {}): Routes {
  return {
    'GET /notifications/unread-count': { count: 0 },
    'GET /stats?period=7d': stats(),
    'GET /stats?period=30d': stats({ period: '30d', quests_completed: 8, xp_per_day: days(30, { 29: 50 }) }),
    'GET /stats/life-balance?period=7d&user=me': balance(),
    'GET /stats/life-balance?period=30d&user=me': balance({ period: '30d', balanced: true, suggestions: [] }),
    'GET /stats/life-balance/targets': TARGETS,
    'GET /character': makeCharacter(),
    'GET /achievements': achievements(['first_quest']),
    ...extra,
  };
}

describe('stats page', () => {
  test('shows the summary, charts, radar, suggestions, attribute progress and achievements', async () => {
    renderApp('/stats', { routes: statsRoutes() });
    const summary = await screen.findByTestId('stats-summary');
    expect(within(summary).getByTestId('stat-quests')).toHaveTextContent('Quests completed3');
    expect(within(summary).getByTestId('stat-xp')).toHaveTextContent('170');
    expect(within(summary).getByTestId('stat-gold-spent')).toHaveTextContent('40');
    expect(within(summary).getByTestId('stat-rewards-fulfilled')).toHaveTextContent('1');
    expect(screen.getByTestId('chart-xp')).toHaveAttribute('data-total', '170');
    expect(screen.getByTestId('chart-quests')).toHaveAttribute('data-total', '3');

    const radar = await screen.findByTestId('life-balance-radar');
    expect(radar).toHaveAccessibleName(/Physical 100%.*Creativity 0%/);
    expect(screen.getByTestId('balance-score-social')).toHaveTextContent('60%');
    const tips = screen.getAllByTestId('life-balance-suggestion');
    expect(tips.map((t) => t.dataset.attribute)).toEqual(['intellectual', 'creativity', 'discipline']);
    expect(tips[0]).toHaveTextContent('No Intellectual activity yet in this period');

    expect(await screen.findByTestId('attribute-progress')).toBeInTheDocument();
    expect(within(screen.getByTestId('attribute-progress')).getAllByRole('progressbar')).toHaveLength(6);
    await waitFor(() => expect(screen.getAllByTestId('achievement')).toHaveLength(3));
    expect(screen.getByTestId('achievements-count')).toHaveTextContent('1 of 3 unlocked');
    const locked = screen.getAllByTestId('achievement').find((a) => a.dataset.code === 'quests_10')!;
    expect(locked).toHaveAttribute('data-unlocked', 'false');
    expect(locked).toHaveTextContent('3 / 10');
    expect(screen.getByTestId('stats-journal-link')).toHaveAttribute('href', '/stats/journal');
  });

  test('switching periods refetches the summary and the life balance', async () => {
    const { calls } = renderApp('/stats', { routes: statsRoutes() });
    await screen.findByTestId('stats-summary');
    await act(async () => fireEvent.click(screen.getByTestId('stats-period-30d')));
    await waitFor(() => expect(screen.getByTestId('stat-quests')).toHaveTextContent('8'));
    expect(screen.getByTestId('stats-period-30d')).toHaveAttribute('aria-checked', 'true');
    expect(screen.getByTestId('chart-xp')).toHaveAttribute('data-total', '50');

    await act(async () => fireEvent.click(screen.getByTestId('life-balance-period-30d')));
    expect(await screen.findByTestId('life-balance-balanced')).toHaveTextContent('Nicely balanced');
    expect(calls.map((c) => c.path)).toContain('/stats/life-balance?period=30d&user=me');
  });

  test('editing my targets sends only valid whole numbers', async () => {
    let sent: unknown = null;
    renderApp('/stats', {
      routes: statsRoutes({
        'PUT /stats/life-balance/targets': (body: unknown) => {
          sent = body;
          return { targets: { ...TARGETS.targets, physical: 150 } };
        },
      }),
    });
    await act(async () => fireEvent.click(await screen.findByTestId('targets-edit')));
    const physical = await screen.findByTestId('target-physical');
    expect(physical).toHaveValue(100);
    fireEvent.change(physical, { target: { value: '-5' } });
    expect(screen.getByTestId('targets-save')).toBeDisabled();
    expect(screen.getByRole('alert')).toHaveTextContent('Use whole numbers');
    fireEvent.change(physical, { target: { value: '150' } });
    await act(async () => fireEvent.click(screen.getByTestId('targets-save')));
    await waitFor(() => expect(sent).not.toBeNull());
    expect(sent).toEqual({ targets: { ...TARGETS.targets, physical: 150 } });
    await waitFor(() => expect(screen.queryByTestId('targets-form')).toBeNull());
  });

  test('renders in Ukrainian', async () => {
    renderApp('/stats', { routes: statsRoutes() });
    await screen.findByTestId('stats-summary');
    await act(async () => setLocale('uk'));
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Статистика');
    expect(screen.getByText('Баланс життя')).toBeInTheDocument();
  });
});

describe('achievement toast', () => {
  test('the first load records existing unlocks without storing anything; a new unlock after a refetch shows a toast', async () => {
    let current = achievements(['first_quest']);
    const { queryClient, adapter } = renderApp('/', {
      routes: {
        'GET /notifications/unread-count': { count: 0 },
        'GET /character': makeCharacter(),
        'GET /achievements': () => current,
      },
    });
    await waitFor(() => expect(queryClient.getQueryData(ACHIEVEMENTS_KEY)).toBeDefined());
    expect(screen.queryByTestId('achievement-toast')).toBeNull();

    current = achievements(['first_quest', 'quest_giver']);
    await act(async () => queryClient.invalidateQueries({ queryKey: ACHIEVEMENTS_KEY }));
    const toast = await screen.findByTestId('achievement-toast');
    expect(toast).toHaveAttribute('data-code', 'quest_giver');
    expect(toast).toHaveTextContent('Achievement unlocked!');
    expect(toast).toHaveTextContent('Quest giver');
    expect(adapter.calls.some((c) => c.method === 'haptic.notification')).toBe(true);

    // The same unlock never toasts twice.
    await act(async () => queryClient.invalidateQueries({ queryKey: ACHIEVEMENTS_KEY }));
    expect(screen.getAllByTestId('achievement-toast')).toHaveLength(1);
    expect(window.localStorage.length).toBe(0);
  });
});

describe('companion life balance', () => {
  const CARD = { user_id: 2, display_name: 'Bohdan', avatar_url: null, character_name: 'Bold', nickname: null, level: 4 };
  const PROFILE = {
    card: CARD,
    bio: null,
    total_xp: 500,
    xp_into_level: 50,
    xp_for_next_level: 300,
    attributes: makeCharacter().attributes,
    goals: [],
    wishlist: [],
  };
  const PAIRED = { partnership: { id: 9, accepted_at: '2026-01-15T12:00:00Z', companion: CARD }, pending_invitation: null };

  test("shows the companion's radar with encouraging quest ideas and a create-quest link", async () => {
    const { calls } = renderApp('/companion', {
      routes: {
        'GET /notifications/unread-count': { count: 0 },
        'GET /partnership': PAIRED,
        'GET /partnership/companion': PROFILE,
        'GET /stats/life-balance?period=7d&user=companion': balance({ user: 'companion' }),
      },
    });
    const section = await screen.findByTestId('companion-life-balance');
    expect(await within(section).findByTestId('life-balance-radar')).toBeInTheDocument();
    const [first] = within(section).getAllByTestId('life-balance-suggestion');
    expect(first).toHaveTextContent('Your companion has not done any Intellectual activities lately');
    expect(within(section).getByTestId('suggestion-create-quest')).toHaveAttribute('href', '/quests/new');
    expect(within(section).queryByTestId('targets-edit')).toBeNull();
    expect(calls.map((c) => c.path)).toContain('/stats/life-balance?period=7d&user=companion');
  });
});
