import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { setLocale } from '../../i18n';
import { makeCharacter, renderApp, type Routes } from '../../test/harness';
import {
  bucketQuests,
  parseQuestRef,
  viewOfOccurrence,
  viewOfTemplate,
  type Occurrence,
  type OccurrenceDetail,
  type Template,
  type TemplateDetail,
  type Terms,
} from './api';
import { allowedActions } from './components/QuestActions';
import { buildTimeline } from './components/StatusTimeline';

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));

afterEach(() => {
  setLocale('en');
  vi.restoreAllMocks();
});

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

function occurrence(overrides: Partial<Occurrence> = {}): Occurrence {
  return {
    id: 11,
    template_id: 5,
    creator_id: 2,
    assignee_id: 1,
    role: 'player',
    status: 'active',
    template_status: 'active',
    recurrence: 'once',
    scheduled_date: '2026-01-15',
    due_at: null,
    terms: TERMS,
    accepted_at: '2026-01-15T10:00:00Z',
    submitted_at: null,
    completed_at: null,
    cancelled_by: null,
    decline_reason: null,
    has_pending_revision: false,
    ...overrides,
  };
}

function template(overrides: Partial<Template> = {}): Template {
  return {
    id: 5,
    partnership_id: 9,
    creator_id: 2,
    assignee_id: 1,
    role: 'player',
    status: 'active',
    recurrence: 'once',
    terms: TERMS,
    version: 1,
    pending_revision: null,
    last_declined_revision: null,
    created_at: '2026-01-15T09:00:00Z',
    ...overrides,
  };
}

function detail(overrides: Partial<Occurrence> = {}, tpl: Partial<Template> = {}): OccurrenceDetail {
  return { ...occurrence(overrides), template: template({ role: overrides.role ?? 'player', ...tpl }), submissions: [] };
}

const COMPANION = { user_id: 2, display_name: 'Bohdan', avatar_url: null, character_name: 'Bold', nickname: null, level: 3 };
const PAIRED = { partnership: { id: 9, accepted_at: null, companion: COMPANION }, pending_invitation: null };
const UNPAIRED = { partnership: null, pending_invitation: null };

function lists(occurrences: Occurrence[], templates: Template[] = []): Routes {
  return {
    'GET /partnership': PAIRED,
    'GET /quests?limit=200': occurrences,
    'GET /quest-templates?limit=200': templates,
  };
}

describe('pure helpers', () => {
  test('parseQuestRef accepts occurrence ids and t<id>, rejects everything else', () => {
    expect(parseQuestRef('12')).toEqual({ kind: 'occurrence', id: 12 });
    expect(parseQuestRef('t7')).toEqual({ kind: 'template', id: 7 });
    for (const bad of [undefined, '', '0', '-1', 'x', 't', '1/2', '1e3', '12 ']) {
      expect(parseQuestRef(bad)).toBeNull();
    }
  });

  test('bucketQuests fills the six tabs and merges recurring offers into Offers', () => {
    const buckets = bucketQuests(
      [
        occurrence({ id: 1, status: 'active' }),
        occurrence({ id: 2, status: 'in_review' }),
        occurrence({ id: 3, status: 'offered' }),
        occurrence({ id: 4, status: 'active', has_pending_revision: true }),
        occurrence({ id: 5, role: 'gm', status: 'offered' }),
        occurrence({ id: 6, role: 'gm', status: 'in_review' }),
        occurrence({ id: 7, role: 'gm', status: 'completed' }),
        occurrence({ id: 8, role: 'player', status: 'completed' }),
      ],
      [
        template({ id: 20, status: 'offered', recurrence: 'daily' }),
        template({ id: 21, status: 'offered', recurrence: 'once' }),
        template({ id: 22, status: 'active', recurrence: 'weekly', role: 'gm' }),
        template({ id: 23, status: 'cancelled', recurrence: 'weekly' }),
      ],
    );
    expect(buckets.active.map((o) => o.id)).toEqual([1, 2, 4]);
    expect(buckets.offers.map((o) => `${'partnership_id' in o ? 't' : 'o'}${o.id}`)).toEqual(['o3', 'o4', 't20']);
    expect(buckets.recurring.map((t) => t.id)).toEqual([20, 22]);
    expect(buckets.assigned.map((o) => o.id)).toEqual([5]);
    expect(buckets.toConfirm.map((o) => o.id)).toEqual([6]);
    expect(buckets.completed.map((o) => o.id)).toEqual([7, 8]);
  });

  test('allowedActions offers only what the viewer may do', () => {
    const by = (status: Occurrence['status'], role: 'player' | 'gm', tpl: Partial<Template> = {}) =>
      allowedActions(viewOfOccurrence(detail({ status, role }, tpl)));
    expect(by('offered', 'player')).toMatchObject({ accept: true, decline: true, submit: false, confirm: false, cancel: true });
    expect(by('offered', 'gm')).toMatchObject({ accept: false, decline: false, cancel: true });
    expect(by('active', 'player')).toMatchObject({ submit: true, accept: false, cancel: true });
    expect(by('active', 'gm')).toMatchObject({ submit: false, confirm: false, cancel: true });
    expect(by('in_review', 'gm')).toMatchObject({ confirm: true, redo: true, cancel: false });
    expect(by('in_review', 'player')).toMatchObject({ confirm: false, redo: false, cancel: false });
    for (const status of ['completed', 'declined', 'cancelled', 'expired'] as const) {
      for (const role of ['player', 'gm'] as const) {
        expect(Object.values(by(status, role)).some(Boolean)).toBe(false);
      }
    }
    const revision = by('active', 'player', {
      pending_revision: { id: 1, version: 2, terms: TERMS, status: 'pending', proposed_by: 2, created_at: '', decided_at: null, decline_reason: null },
    });
    expect(revision).toMatchObject({ revision: true, accept: true, decline: true });
  });

  test('the timeline lists the lifecycle in order', () => {
    const view = viewOfOccurrence({
      ...detail({ status: 'completed', completed_at: '2026-01-16T10:00:00Z', submitted_at: '2026-01-16T09:00:00Z' }),
      submissions: [
        { id: 1, submitted_by: 1, comment: 'Done!', attachment_id: null, created_at: '2026-01-16T09:00:00Z', review_status: 'approved', review_comment: null, reviewed_at: null },
      ],
    });
    const keys = buildTimeline(view, (k) => k).map((e) => e.key);
    expect(keys).toEqual(['offered', 'accepted', 'sub-1', 'completed']);
  });

  test('a recurring offer without an occurrence is a template view', () => {
    const tpl: TemplateDetail = { ...template({ status: 'offered', recurrence: 'daily' }), latest_occurrence: null };
    const view = viewOfTemplate(tpl);
    expect(view.ref).toEqual({ kind: 'template', id: 5 });
    expect(view.status).toBe('offered');
    expect(allowedActions(view).accept).toBe(true);
  });
});

describe('quests page', () => {
  test('an unpaired user sees the invite CTA instead of the tabs', async () => {
    renderApp('/quests', { routes: { 'GET /partnership': UNPAIRED } });
    expect(await screen.findByText('Quests need a companion')).toBeInTheDocument();
    expect(screen.getByTestId('invite-panel')).toBeInTheDocument();
    expect(screen.queryByRole('tablist')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quest-fab')).not.toBeInTheDocument();
  });

  test('the six tabs show real data and switch', async () => {
    renderApp('/quests', {
      routes: lists(
        [
          occurrence({ id: 1, terms: { ...TERMS, title: 'Active one' } }),
          occurrence({ id: 3, status: 'offered', terms: { ...TERMS, title: 'Offered one' } }),
          occurrence({ id: 5, role: 'gm', status: 'active', terms: { ...TERMS, title: 'Mine to watch' } }),
          occurrence({ id: 6, role: 'gm', status: 'in_review', terms: { ...TERMS, title: 'Review me' } }),
          occurrence({ id: 7, status: 'completed', terms: { ...TERMS, title: 'Done one' } }),
        ],
        [template({ id: 20, status: 'offered', recurrence: 'daily', terms: { ...TERMS, title: 'Daily offer' } })],
      ),
    });
    const tablist = await screen.findByRole('tablist');
    expect(within(tablist).getAllByRole('tab')).toHaveLength(6);
    const list = screen.getByTestId('quest-list');
    await waitFor(() => expect(within(list).getByText('Active one')).toBeInTheDocument());

    const open = async (tab: string) => act(async () => fireEvent.click(screen.getByTestId(`quest-tab-${tab}`)));
    await open('offers');
    expect(within(list).getByText('Offered one')).toBeInTheDocument();
    expect(within(list).getByText('Daily offer')).toBeInTheDocument();
    await open('recurring');
    expect(within(list).getByText('Daily offer')).toBeInTheDocument();
    await open('assigned');
    expect(within(list).getByText('Mine to watch')).toBeInTheDocument();
    await open('toConfirm');
    expect(within(list).getByText('Review me')).toBeInTheDocument();
    await open('completed');
    expect(within(list).getByText('Done one')).toBeInTheDocument();
    expect(screen.getByTestId('quest-tab-completed')).toHaveAttribute('aria-selected', 'true');
  });
});

describe('create sheet', () => {
  const presets = {
    builtin: [
      { key: 'run', builtin: true, saved_id: null, title: 'Go for a run', description: null, attribute: 'physical', difficulty: 'normal', gold: 50, recurrence: 'once', confirmation: 'manual', photo_required: false },
      { key: 'read', builtin: true, saved_id: null, title: 'Read for 30 minutes', description: null, attribute: 'intellectual', difficulty: 'easy', gold: 20, recurrence: 'daily', confirmation: 'manual', photo_required: false },
    ],
    saved: [
      { key: 'saved-4', builtin: false, saved_id: 4, title: 'My template', description: null, attribute: 'social', difficulty: 'hard', gold: 90, recurrence: 'once', confirmation: 'auto', photo_required: true },
    ],
  };

  test('creates a Normal / Physical / 50 gold quest and opens its detail', async () => {
    const created = vi.fn(() => ({ template: template({ role: 'gm' }), occurrence: occurrence({ id: 77, role: 'gm', status: 'offered' }) }));
    const { request, router } = renderApp('/quests/new', {
      routes: {
        ...lists([]),
        'POST /quests': created,
        'GET /quests/77': detail({ id: 77, role: 'gm', status: 'offered' }, { role: 'gm' }),
      },
    });
    const submit = await screen.findByTestId('quest-create');
    expect(submit).toBeDisabled();
    fireEvent.change(screen.getByTestId('quest-title'), { target: { value: '  Morning run ' } });
    expect(submit).toBeDisabled();
    fireEvent.click(screen.getByTestId('attribute-physical'));
    expect(screen.getByTestId('difficulty-normal')).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByTestId('quest-gold')).toHaveValue('50');
    expect(screen.queryByTestId('more-fields')).not.toBeInTheDocument();
    await act(async () => fireEvent.click(submit));
    await waitFor(() => expect(router.state.location.pathname).toBe('/quests/77'));
    expect(created).toHaveBeenCalledWith(
      {
        title: 'Morning run',
        description: null,
        attribute: 'physical',
        difficulty: 'normal',
        gold: 50,
        recurrence: 'once',
        confirmation: 'manual',
        photo_required: false,
        deadline_at: null,
      },
      '/quests',
    );
    const call = request.mock.calls.find((c) => c[1] === '/quests' && c[0] === 'POST');
    expect(call?.[2]).toMatchObject({ idempotencyKey: true });
  });

  test('more options add recurrence, deadline, confirmation and photo; a recurring quest shows the estimate', async () => {
    renderApp('/quests/new', {
      routes: {
        ...lists([]),
        'GET /quests/estimate?gold=50&recurrence=daily': { gold: 50, recurrence: 'daily', weekly: 350, monthly: 1500 },
      },
    });
    await screen.findByTestId('quest-create');
    fireEvent.click(screen.getByTestId('more-options'));
    expect(screen.getByTestId('quest-deadline')).toBeInTheDocument();
    expect(screen.getByTestId('quest-confirmation')).toBeInTheDocument();
    expect(screen.getByTestId('quest-photo')).toBeInTheDocument();
    expect(screen.queryByTestId('quest-estimate')).not.toBeInTheDocument();
    fireEvent.change(screen.getByTestId('quest-recurrence'), { target: { value: 'daily' } });
    expect(screen.queryByTestId('quest-deadline')).not.toBeInTheDocument();
    expect(await screen.findByText(/Up to 350 gold a week and about 1500 gold a month/)).toBeInTheDocument();
  });

  test('picking a preset fills the form; saving a template and deleting one hit /quest-presets', async () => {
    const saved = vi.fn(() => ({ ...presets.saved[0], key: 'saved-9', saved_id: 9 }));
    const removed = vi.fn(() => undefined);
    const { calls } = renderApp('/quests/new', {
      routes: {
        ...lists([]),
        'GET /quest-presets': presets,
        'POST /quest-presets': saved,
        'DELETE /quest-presets/4': removed,
      },
    });
    await screen.findByTestId('quest-create');
    fireEvent.click(screen.getByTestId('preset-toggle'));
    const picker = await screen.findByTestId('preset-picker');
    expect(within(picker).getAllByTestId('preset-option')).toHaveLength(3);
    fireEvent.click(within(picker).getByText('Go for a run'));
    expect(screen.getByTestId('quest-title')).toHaveValue('Go for a run');
    expect(screen.getByTestId('attribute-physical')).toHaveAttribute('aria-pressed', 'true');

    await act(async () => fireEvent.click(screen.getByTestId('save-template')));
    await waitFor(() => expect(saved).toHaveBeenCalled());
    expect(calls.find((c) => c.path === '/quest-presets' && c.method === 'POST')?.body).toMatchObject({
      title: 'Go for a run',
      attribute: 'physical',
      gold: 50,
    });

    fireEvent.click(screen.getByTestId('preset-toggle'));
    const again = await screen.findByTestId('preset-picker');
    await act(async () => fireEvent.click(within(again).getByRole('button', { name: 'Delete template My template' })));
    await waitFor(() => expect(removed).toHaveBeenCalled());
  });

  test('a duplicated quest prefills the sheet', async () => {
    renderApp('/quests/99', {
      routes: {
        'GET /quests/99': detail({ id: 99, role: 'gm', status: 'active', terms: { ...TERMS, title: 'Dup me', gold: 80 } }, { role: 'gm', terms: { ...TERMS, title: 'Dup me', gold: 80 } }),
        ...lists([]),
      },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('quest-duplicate')));
    expect(await screen.findByTestId('quest-title')).toHaveValue('Dup me');
    expect(screen.getByTestId('quest-gold')).toHaveValue('80');
    expect(screen.getByTestId('attribute-physical')).toHaveAttribute('aria-pressed', 'true');
  });
});

describe('quest detail', () => {
  test('a player sees accept/decline on an offer, and accepting sends an Idempotency-Key and a haptic', async () => {
    const accepted = vi.fn(() => detail({ status: 'active' }));
    const { request, adapter } = renderApp('/quests/11', {
      routes: { 'GET /quests/11': detail({ status: 'offered', accepted_at: null }), 'POST /quests/11/accept': accepted, ...lists([]), 'GET /character': makeCharacter() },
    });
    expect(await screen.findByTestId('quest-accept')).toBeInTheDocument();
    expect(screen.getByTestId('quest-decline')).toBeInTheDocument();
    expect(screen.queryByTestId('quest-submit')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quest-confirm')).not.toBeInTheDocument();
    expect(screen.queryByTestId('gm-label')).not.toBeInTheDocument();
    expect(screen.getByTestId('quest-timeline')).toHaveTextContent('Offered');
    await act(async () => fireEvent.click(screen.getByTestId('quest-accept')));
    await waitFor(() => expect(accepted).toHaveBeenCalled());
    const call = request.mock.calls.find((c) => c[1] === '/quests/11/accept');
    expect(call?.[2]).toMatchObject({ idempotencyKey: true });
    expect(adapter.calls).toContainEqual({ method: 'haptic.notification', args: ['success'] });
  });

  test('decline sends the optional reason', async () => {
    const declined = vi.fn(() => detail({ status: 'declined' }));
    renderApp('/quests/11', {
      routes: { 'GET /quests/11': detail({ status: 'offered', accepted_at: null }), 'POST /quests/11/decline': declined, ...lists([]) },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('quest-decline')));
    fireEvent.change(screen.getByTestId('decline-reason'), { target: { value: 'No time' } });
    await act(async () => fireEvent.click(screen.getByTestId('decline-send')));
    await waitFor(() => expect(declined).toHaveBeenCalledWith({ reason: 'No time' }, '/quests/11/decline'));
  });

  test('a player submits an active quest with a comment', async () => {
    const submitted = vi.fn(() => ({ ...detail({ status: 'in_review' }), completion: null }));
    renderApp('/quests/11', {
      routes: { 'GET /quests/11': detail({ status: 'active' }), 'POST /quests/11/submit': submitted, ...lists([]) },
    });
    fireEvent.change(await screen.findByTestId('submit-comment'), { target: { value: 'Ran 5k' } });
    await act(async () => fireEvent.click(screen.getByTestId('quest-submit')));
    await waitFor(() => expect(submitted).toHaveBeenCalledWith({ comment: 'Ran 5k' }, '/quests/11/submit'));
  });

  test('the GM sees confirm/redo with the GM label on an in-review quest, never submit or accept', async () => {
    renderApp('/quests/11', {
      routes: { 'GET /quests/11': detail({ status: 'in_review', role: 'gm' }, { role: 'gm' }), ...lists([]) },
    });
    expect(await screen.findByTestId('quest-confirm')).toBeInTheDocument();
    expect(screen.getByTestId('quest-redo')).toBeInTheDocument();
    expect(screen.getByTestId('gm-label')).toHaveTextContent('You are the Game Master');
    expect(screen.queryByTestId('quest-submit')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quest-accept')).not.toBeInTheDocument();
    expect(screen.queryByTestId('quest-cancel')).not.toBeInTheDocument();
  });

  test('redo needs a reason and sends it', async () => {
    const redo = vi.fn(() => ({ ...detail({ status: 'active', role: 'gm' }, { role: 'gm' }), completion: null }));
    renderApp('/quests/11', {
      routes: { 'GET /quests/11': detail({ status: 'in_review', role: 'gm' }, { role: 'gm' }), 'POST /quests/11/request-redo': redo, ...lists([]) },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('quest-redo')));
    expect(screen.getByTestId('redo-send')).toBeDisabled();
    fireEvent.change(screen.getByTestId('redo-reason'), { target: { value: 'Show the route' } });
    await act(async () => fireEvent.click(screen.getByTestId('redo-send')));
    await waitFor(() => expect(redo).toHaveBeenCalledWith({ reason: 'Show the route' }, '/quests/11/request-redo'));
  });

  test('confirming shows the celebration, then a level-up overlay when the player levelled up', async () => {
    const completion = { gold: 50, xp: 50, attribute: 'physical', attribute_xp: 50, total_xp: 300, level_before: 2, level: 3, attribute_level_before: 1, attribute_level: 1, balance: 50 };
    const confirm = vi.fn(() => ({ ...detail({ status: 'completed', role: 'gm' }, { role: 'gm' }), completion }));
    const { request } = renderApp('/quests/11', {
      routes: { 'GET /quests/11': detail({ status: 'in_review', role: 'gm' }, { role: 'gm' }), 'POST /quests/11/confirm': confirm, ...lists([]), 'GET /character': makeCharacter() },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('quest-confirm')));
    const overlay = await screen.findByRole('alertdialog', { name: 'Quest complete!' });
    expect(overlay).toHaveTextContent('Your companion earned 50 gold and 50 XP');
    expect(request.mock.calls.find((c) => c[1] === '/quests/11/confirm')?.[2]).toMatchObject({ idempotencyKey: true });
    fireEvent.click(within(overlay).getByRole('button', { name: 'Continue' }));
    const levelUp = await screen.findByRole('alertdialog', { name: 'Level up!' });
    expect(levelUp).toHaveTextContent('Your companion reached level 3');
    fireEvent.click(within(levelUp).getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  });

  test('no level-up overlay when the level did not change', async () => {
    const completion = { gold: 50, xp: 50, attribute: 'physical', attribute_xp: 50, total_xp: 300, level_before: 3, level: 3, attribute_level_before: 1, attribute_level: 1, balance: 50 };
    renderApp('/quests/11', {
      routes: {
        'GET /quests/11': detail({ status: 'in_review', role: 'gm' }, { role: 'gm' }),
        'POST /quests/11/confirm': () => ({ ...detail({ status: 'completed', role: 'gm' }, { role: 'gm' }), completion }),
        ...lists([]),
        'GET /character': makeCharacter(),
      },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('quest-confirm')));
    const overlay = await screen.findByRole('alertdialog', { name: 'Quest complete!' });
    fireEvent.click(within(overlay).getByRole('button', { name: 'Continue' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
  });

  test('cancel goes through a confirm sheet, not a native dialog', async () => {
    const nativeConfirm = vi.spyOn(window, 'confirm');
    const cancel = vi.fn(() => detail({ status: 'cancelled' }));
    renderApp('/quests/11', {
      routes: { 'GET /quests/11': detail({ status: 'active' }), 'POST /quests/11/cancel': cancel, ...lists([]) },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('quest-cancel')));
    expect(cancel).not.toHaveBeenCalled();
    const sheet = await screen.findByRole('dialog');
    await act(async () => fireEvent.click(within(sheet).getByRole('button', { name: 'Cancel quest' })));
    await waitFor(() => expect(cancel).toHaveBeenCalled());
    expect(nativeConfirm).not.toHaveBeenCalled();
  });

  test('a pending revision shows its terms and the player can accept it', async () => {
    const revision = { id: 3, version: 2, terms: { ...TERMS, gold: 90 }, status: 'pending' as const, proposed_by: 2, created_at: '2026-01-15T11:00:00Z', decided_at: null, decline_reason: null };
    const accept = vi.fn(() => detail({ status: 'active' }));
    renderApp('/quests/11', {
      routes: { 'GET /quests/11': detail({ status: 'active', has_pending_revision: true }, { pending_revision: revision }), 'POST /quests/11/accept': accept, ...lists([]) },
    });
    expect(await screen.findByTestId('quest-revision')).toHaveTextContent('90');
    await act(async () => fireEvent.click(screen.getByTestId('quest-accept')));
    await waitFor(() => expect(accept).toHaveBeenCalled());
    expect(screen.getByText('Accept new terms')).toBeInTheDocument();
  });

  test('a recurring offer (template id) is accepted through /quest-templates', async () => {
    const tpl: TemplateDetail = { ...template({ status: 'offered', recurrence: 'daily' }), latest_occurrence: null };
    const accept = vi.fn(() => ({ ...tpl, status: 'active' }));
    renderApp('/quests/t5', {
      routes: { 'GET /quest-templates/5': tpl, 'POST /quest-templates/5/accept': accept, ...lists([]) },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('quest-accept')));
    await waitFor(() => expect(accept).toHaveBeenCalled());
  });

  test('an invalid id shows not found without any request', async () => {
    const { request } = renderApp('/quests/abc', { routes: {} });
    expect(await screen.findByText('Quest not found')).toBeInTheDocument();
    expect(request.mock.calls.some((c) => String(c[1]).startsWith('/quests'))).toBe(false);
  });

  test('a conflict (409) is explained', async () => {
    const { ApiError } = await import('../../lib/api/client');
    renderApp('/quests/11', {
      routes: {
        'GET /quests/11': detail({ status: 'offered', accepted_at: null }),
        'POST /quests/11/accept': () => {
          throw new ApiError(409, 'Quest is not offered');
        },
        ...lists([]),
      },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('quest-accept')));
    expect(await screen.findByTestId('quest-error')).toHaveTextContent('This quest has changed');
  });
});

describe('home today panel', () => {
  test('lists my active quests, offers and pending confirmations', async () => {
    renderApp('/', {
      routes: {
        'GET /character': makeCharacter(),
        ...lists(
          [
            occurrence({ id: 1, terms: { ...TERMS, title: 'Run today' } }),
            occurrence({ id: 2, status: 'offered', terms: { ...TERMS, title: 'Newly offered' } }),
            occurrence({ id: 3, role: 'gm', status: 'in_review', terms: { ...TERMS, title: 'Awaiting me' } }),
          ],
          [template({ id: 20, status: 'offered', recurrence: 'daily', terms: { ...TERMS, title: 'Daily offer' } })],
        ),
      },
    });
    const panel = await screen.findByTestId('today-panel');
    await waitFor(() => expect(within(panel).getByText('Run today')).toBeInTheDocument());
    expect(within(screen.getByTestId('today-offers')).getByText('Newly offered')).toBeInTheDocument();
    expect(within(screen.getByTestId('today-offers')).getByText('Daily offer')).toBeInTheDocument();
    expect(within(screen.getByTestId('today-confirm')).getByText('Awaiting me')).toBeInTheDocument();
  });

  test('is hidden for an unpaired user', async () => {
    renderApp('/', { routes: { 'GET /character': makeCharacter(), 'GET /partnership': UNPAIRED } });
    await screen.findByTestId('character-header');
    expect(screen.queryByTestId('today-panel')).not.toBeInTheDocument();
  });
});
