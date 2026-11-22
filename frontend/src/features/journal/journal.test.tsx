import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, test } from 'vitest';

import { setLocale } from '../../i18n';
import { makeCharacter, renderApp, type Routes } from '../../test/harness';
import type { JournalEvent, JournalPage } from '../stats/api';

afterEach(() => setLocale('en'));

let nextId = 100;
function event(type: string, payload: Record<string, unknown> = {}, overrides: Partial<JournalEvent> = {}): JournalEvent {
  nextId -= 1;
  return {
    id: nextId,
    type,
    actor: 'me',
    visibility: 'shared',
    entity_type: 'quest_occurrence',
    entity_id: 7,
    payload,
    created_at: '2026-01-15T12:00:00Z',
    ...overrides,
  };
}

const page = (items: JournalEvent[], next_cursor: number | null = null): JournalPage => ({ items, next_cursor });

function routes(extra: Routes = {}): Routes {
  return { 'GET /notifications/unread-count': { count: 0 }, 'GET /character': makeCharacter(), ...extra };
}

describe('adventure journal', () => {
  test('renders every event as a sentence with who did it, and quest events link to the quest', async () => {
    const items = [
      event('achievement_unlocked', { code: 'first_quest' }, { entity_type: 'achievement', entity_id: null }),
      event('attribute_level_up', { attribute: 'creativity', level: 3 }),
      event('quest_completed', { title: 'Morning run', xp: 50, gold: 40 }),
      event('reward_purchased', { title: 'Movie night', price: 40 }, { entity_type: 'reward_purchase', entity_id: 3 }),
      event('quest_offered', { title: 'Morning run' }, { actor: 'companion' }),
      event('something_new', {}),
    ];
    renderApp('/stats/journal', { routes: routes({ 'GET /journal?scope=me&limit=30': page(items) }) });
    const list = await screen.findByTestId('journal-list');
    const rows = within(list).getAllByTestId('journal-event');
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining('Achievement unlocked: First steps'),
      expect.stringContaining('Creativity reached level 3'),
      expect.stringContaining('Quest completed: Morning run (+50 XP, +40 Gold)'),
      expect.stringContaining('Reward bought: Movie night (40 Gold)'),
      expect.stringContaining('Quest offered: Morning run'),
      expect.stringContaining('Adventure event'),
    ]);
    expect(rows[2]).toHaveTextContent('You');
    expect(rows[4]).toHaveTextContent('Companion');
    expect(within(rows[2]!).getByRole('link')).toHaveAttribute('href', '/quests/7');
    expect(within(rows[3]!).queryByRole('link')).toBeNull();
  });

  test('switches to the shared scope and loads older pages', async () => {
    const { calls } = renderApp('/stats/journal', {
      routes: routes({
        'GET /journal?scope=me&limit=30': page([event('quest_accepted', { title: 'Mine' })]),
        'GET /journal?scope=shared&limit=30': page([event('quest_offered', { title: 'Newer' })], 5),
        'GET /journal?scope=shared&limit=30&cursor=5': page([event('quest_offered', { title: 'Older' })]),
      }),
    });
    await screen.findByText(/Quest accepted: Mine/);
    await act(async () => fireEvent.click(screen.getByTestId('journal-scope-shared')));
    expect(await screen.findByText(/Quest offered: Newer/)).toBeInTheDocument();
    expect(screen.getByTestId('journal-scope-shared')).toHaveAttribute('aria-selected', 'true');
    await act(async () => fireEvent.click(screen.getByTestId('journal-more')));
    expect(await screen.findByText(/Quest offered: Older/)).toBeInTheDocument();
    expect(screen.queryByTestId('journal-more')).toBeNull();
    expect(calls.map((c) => c.path)).toContain('/journal?scope=shared&limit=30&cursor=5');
  });

  test('empty and error states', async () => {
    let fail = true;
    renderApp('/stats/journal', {
      routes: routes({
        'GET /journal?scope=me&limit=30': () => {
          if (fail) throw new Error('boom');
          return page([]);
        },
      }),
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the journal.');
    fail = false;
    await act(async () => fireEvent.click(screen.getByRole('button', { name: 'Try again' })));
    await waitFor(() => expect(screen.getByTestId('empty-state')).toHaveTextContent('The journal is empty'));
  });

  test('speaks Ukrainian', async () => {
    renderApp('/stats/journal', {
      routes: routes({ 'GET /journal?scope=me&limit=30': page([event('quest_completed', { title: 'Біг', xp: 50, gold: 40 })]) }),
    });
    await screen.findByTestId('journal-list');
    await act(async () => setLocale('uk'));
    expect(screen.getByTestId('journal-event')).toHaveTextContent('Квест виконано: Біг (+50 XP, +40 золота)');
    expect(screen.getByTestId('journal-event')).toHaveTextContent('Ти');
  });
});
