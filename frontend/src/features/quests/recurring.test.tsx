import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, test, vi } from 'vitest';

import { renderApp, type Routes } from '../../test/harness';
import type { Template, TemplateDetail, Terms } from './api';

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));

const TERMS: Terms = {
  title: 'Morning run',
  description: null,
  attribute: 'physical',
  difficulty: 'normal',
  gold: 50,
  xp: 50,
  deadline: null,
  confirmation: 'manual',
  photo_required: false,
};

function template(overrides: Partial<Template> = {}): Template {
  return {
    id: 5,
    partnership_id: 9,
    creator_id: 1,
    assignee_id: 2,
    role: 'gm',
    status: 'active',
    recurrence: 'daily',
    terms: TERMS,
    version: 1,
    pending_revision: null,
    last_declined_revision: null,
    streak: { current: 3, best: 7, last_completed_date: '2026-01-14' },
    created_at: '2026-01-10T09:00:00Z',
    ...overrides,
  };
}

const COMPANION = { user_id: 2, display_name: 'Bohdan', avatar_url: null, character_name: 'Bold', nickname: null, level: 3 };

function routes(templates: Template[], extra: Routes = {}): Routes {
  return {
    'GET /partnership': { partnership: { id: 9, accepted_at: null, companion: COMPANION }, pending_invitation: null },
    'GET /quests?limit=200': [],
    'GET /quest-templates?limit=200': templates,
    ...extra,
  };
}

async function openRecurring() {
  await act(async () => fireEvent.click(await screen.findByTestId('quest-tab-recurring')));
  return screen.findByTestId('recurring-list');
}

describe('recurring tab', () => {
  test('shows the streak of a daily quest and lets its creator pause it', async () => {
    const paused = vi.fn((): TemplateDetail => ({ ...template({ status: 'paused' }), latest_occurrence: null }));
    const { adapter } = renderApp('/quests', {
      routes: routes([template()], { 'POST /quest-templates/5/pause': paused }),
    });
    const list = await openRecurring();
    expect(within(list).getByText('Morning run')).toBeInTheDocument();
    expect(within(list).getByTestId('recurring-streak')).toHaveTextContent('3 day streak');
    expect(within(list).getByTestId('recurring-streak')).toHaveTextContent('best 7');
    expect(within(list).queryByTestId('recurring-resume')).not.toBeInTheDocument();

    await act(async () => fireEvent.click(within(list).getByTestId('recurring-pause')));
    await waitFor(() => expect(paused).toHaveBeenCalled());
    expect(adapter.calls).toContainEqual({ method: 'haptic.notification', args: ['success'] });
  });

  test('a paused quest offers resume and says generation is stopped', async () => {
    const resumed = vi.fn((): TemplateDetail => ({ ...template(), latest_occurrence: null }));
    renderApp('/quests', {
      routes: routes([template({ status: 'paused' })], { 'POST /quest-templates/5/resume': resumed }),
    });
    const list = await openRecurring();
    expect(within(list).getByText('Paused', { selector: '[data-status="paused"]' })).toBeInTheDocument();
    expect(within(list).getByText(/no new quests are created/i)).toBeInTheDocument();
    await act(async () => fireEvent.click(within(list).getByTestId('recurring-resume')));
    await waitFor(() => expect(resumed).toHaveBeenCalled());
  });

  test('the player sees status and streak but no pause control; weekly has no streak', async () => {
    renderApp('/quests', {
      routes: routes([
        template({ id: 5, role: 'player' }),
        template({ id: 6, role: 'player', recurrence: 'weekly', streak: null, terms: { ...TERMS, title: 'Weekly' } }),
      ]),
    });
    const list = await openRecurring();
    expect(within(list).getAllByTestId('recurring-item')).toHaveLength(2);
    expect(within(list).getAllByTestId('recurring-streak')).toHaveLength(1);
    expect(within(list).queryByTestId('recurring-pause')).not.toBeInTheDocument();
    expect(within(list).queryByTestId('recurring-resume')).not.toBeInTheDocument();
  });

  test('an empty tab shows the empty state', async () => {
    renderApp('/quests', { routes: routes([]) });
    await act(async () => fireEvent.click(await screen.findByTestId('quest-tab-recurring')));
    expect(await screen.findByText('No recurring quests yet.')).toBeInTheDocument();
  });
});
