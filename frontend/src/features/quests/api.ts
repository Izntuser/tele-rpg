import { keepPreviousData, useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import type { components } from '../../lib/api/schema';
import { useAuth } from '../auth/context';
import { CHARACTER_QUERY_KEY } from '../character/api';

type S = components['schemas'];
export type Occurrence = S['OccurrenceOut'];
export type OccurrenceDetail = S['OccurrenceDetail'];
export type Template = S['TemplateOut'];
export type TemplateDetail = S['TemplateDetail'];
export type Terms = S['QuestTerms'];
export type Revision = S['RevisionOut'];
export type Submission = S['SubmissionOut'];
export type QuestCreate = S['QuestCreate'];
export type QuestCreated = S['QuestCreated'];
export type QuestActionResult = S['QuestActionResult'];
export type Completion = S['CompletionOut'];
export type Preset = S['PresetOut'];
export type PresetList = S['PresetList'];
export type PresetCreate = S['PresetCreate'];
export type Estimate = S['Estimate'];
export type Recurrence = S['Recurrence'];
export type Role = 'player' | 'gm';

export const QUESTS_KEY = ['quests'] as const;
export const TEMPLATES_KEY = ['quest-templates'] as const;
export const PRESETS_KEY = ['quest-presets'] as const;

/** Everything a quest change can move: lists, details, my gold and XP. */
export function invalidateQuests(queryClient: QueryClient): Promise<unknown> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: QUESTS_KEY }),
    queryClient.invalidateQueries({ queryKey: TEMPLATES_KEY }),
    queryClient.invalidateQueries({ queryKey: CHARACTER_QUERY_KEY }),
  ]);
}

/** The route id of a quest: an occurrence id, or `t<template id>` for a recurring offer. */
export type QuestRef = { kind: 'occurrence'; id: number } | { kind: 'template'; id: number };

export function parseQuestRef(param: string | undefined): QuestRef | null {
  const match = /^(t?)([1-9]\d{0,17})$/.exec(param ?? '');
  if (!match) return null;
  return { kind: match[1] ? 'template' : 'occurrence', id: Number(match[2]) };
}

export const questPath = (ref: QuestRef): string => `/quests/${ref.kind === 'template' ? 't' : ''}${ref.id}`;

export function useQuestList() {
  const { api } = useAuth();
  return useQuery({
    queryKey: [...QUESTS_KEY, 'list'],
    queryFn: ({ signal }) => api.get<Occurrence[]>('/quests?limit=200', { signal }),
  });
}

export function useTemplateList() {
  const { api } = useAuth();
  return useQuery({
    queryKey: [...TEMPLATES_KEY, 'list'],
    queryFn: ({ signal }) => api.get<Template[]>('/quest-templates?limit=200', { signal }),
  });
}

/** One quest, normalised: an occurrence (with its template) or a template with no occurrence yet. */
export interface QuestView {
  ref: QuestRef;
  template: Template;
  occurrence: Occurrence | null;
  submissions: Submission[];
  role: Role;
  /** Occurrence status when there is one, else the template's. */
  status: Occurrence['status'] | Template['status'];
  terms: Terms;
}

export function viewOfOccurrence(detail: OccurrenceDetail): QuestView {
  const { template, submissions, ...occurrence } = detail;
  return {
    ref: { kind: 'occurrence', id: occurrence.id },
    template,
    occurrence,
    submissions,
    role: occurrence.role,
    status: occurrence.status,
    terms: occurrence.terms,
  };
}

export function viewOfTemplate(detail: TemplateDetail): QuestView {
  const { latest_occurrence: occurrence, ...template } = detail;
  return {
    ref: { kind: 'template', id: template.id },
    template,
    occurrence,
    submissions: [],
    role: template.role,
    status: occurrence?.status ?? template.status,
    terms: occurrence?.terms ?? template.terms,
  };
}

export function useQuest(ref: QuestRef | null) {
  const { api } = useAuth();
  return useQuery({
    queryKey: [...QUESTS_KEY, 'detail', ref?.kind, ref?.id],
    enabled: ref !== null,
    queryFn: async ({ signal }): Promise<QuestView> => {
      if (ref!.kind === 'template') {
        return viewOfTemplate(await api.get<TemplateDetail>(`/quest-templates/${ref!.id}`, { signal }));
      }
      return viewOfOccurrence(await api.get<OccurrenceDetail>(`/quests/${ref!.id}`, { signal }));
    },
  });
}

type Action =
  | { type: 'accept' }
  | { type: 'decline'; reason?: string }
  | { type: 'cancel' }
  | { type: 'submit'; comment?: string }
  | { type: 'confirm'; feedback?: string }
  | { type: 'redo'; reason: string };

const ACTION_PATH: Record<Action['type'], string> = {
  accept: 'accept',
  decline: 'decline',
  cancel: 'cancel',
  submit: 'submit',
  confirm: 'confirm',
  redo: 'request-redo',
};

function actionBody(action: Action): Record<string, string> | undefined {
  switch (action.type) {
    case 'decline':
      return action.reason?.trim() ? { reason: action.reason.trim() } : undefined;
    case 'submit':
      return action.comment?.trim() ? { comment: action.comment.trim() } : undefined;
    case 'confirm':
      return action.feedback?.trim() ? { feedback: action.feedback.trim() } : undefined;
    case 'redo':
      return { reason: action.reason.trim() };
    default:
      return undefined;
  }
}

/**
 * Every lifecycle action on one quest. Each sends an Idempotency-Key, fires a haptic on success
 * (error haptic on failure) and refreshes lists, details and my gold/XP. Only an occurrence has
 * submit / confirm / redo; accept, decline and cancel also work on a template (recurring offer).
 */
export function useQuestAction(ref: QuestRef) {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: Action) => {
      const base = ref.kind === 'template' ? '/quest-templates' : '/quests';
      return api.request<QuestActionResult | OccurrenceDetail | TemplateDetail>('POST', `${base}/${ref.id}/${ACTION_PATH[action.type]}`, {
        body: actionBody(action),
        idempotencyKey: true,
      });
    },
    onSuccess: () => {
      telegram.haptic.notification('success');
      void invalidateQuests(queryClient);
    },
    onError: () => telegram.haptic.notification('error'),
  });
}

export function useCreateQuest() {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: QuestCreate) =>
      api.request<QuestCreated>('POST', '/quests', { body, idempotencyKey: true }),
    onSuccess: () => {
      telegram.haptic.notification('success');
      void invalidateQuests(queryClient);
    },
    onError: () => telegram.haptic.notification('error'),
  });
}

export function usePresets(enabled = true) {
  const { api } = useAuth();
  return useQuery({
    queryKey: PRESETS_KEY,
    enabled,
    queryFn: ({ signal }) => api.get<PresetList>('/quest-presets', { signal }),
  });
}

export function usePresetMutations() {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  const onSuccess = () => {
    telegram.haptic.notification('success');
    return queryClient.invalidateQueries({ queryKey: PRESETS_KEY });
  };
  return {
    save: useMutation({
      mutationFn: (body: PresetCreate) =>
        api.request<Preset>('POST', '/quest-presets', { body, idempotencyKey: true }),
      onSuccess,
    }),
    remove: useMutation({
      mutationFn: (savedId: number) => api.delete<void>(`/quest-presets/${savedId}`),
      onSuccess,
    }),
  };
}

/** Weekly / monthly Gold a recurring quest can mint (inflation guidance). */
export function useEstimate(gold: number, recurrence: Recurrence, enabled: boolean) {
  const { api } = useAuth();
  return useQuery({
    queryKey: ['quest-estimate', gold, recurrence],
    enabled,
    placeholderData: keepPreviousData,
    queryFn: ({ signal }) =>
      api.get<Estimate>(`/quests/estimate?gold=${gold}&recurrence=${recurrence}`, { signal }),
  });
}

/** Lists split into the six tabs; offers merge occurrences with recurring template offers. */
export interface QuestBuckets {
  active: Occurrence[];
  offers: (Occurrence | Template)[];
  recurring: Template[];
  assigned: Occurrence[];
  toConfirm: Occurrence[];
  completed: Occurrence[];
}

export const isTemplate = (item: Occurrence | Template): item is Template => 'partnership_id' in item;

export function bucketQuests(occurrences: Occurrence[], templates: Template[]): QuestBuckets {
  const mine = occurrences.filter((o) => o.role === 'player');
  const theirs = occurrences.filter((o) => o.role === 'gm');
  const recurringOffers = templates.filter(
    (t) => t.role === 'player' && t.status === 'offered' && t.recurrence !== 'once',
  );
  return {
    active: mine.filter((o) => o.status === 'active' || o.status === 'in_review'),
    offers: [
      ...mine.filter((o) => o.status === 'offered' || (o.status === 'active' && o.has_pending_revision)),
      ...recurringOffers,
    ],
    recurring: templates.filter(
      (t) => t.recurrence !== 'once' && (t.status === 'active' || t.status === 'paused' || t.status === 'offered'),
    ),
    assigned: theirs.filter((o) => o.status === 'offered' || o.status === 'active'),
    toConfirm: theirs.filter((o) => o.status === 'in_review'),
    completed: occurrences.filter((o) => o.status === 'completed'),
  };
}
