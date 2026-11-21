import { useMutation, useQueryClient } from '@tanstack/react-query';
import { X } from 'lucide-react';
import { useEffect, useId, useMemo, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';
import { Navigate, useNavigate } from 'react-router';

import { Avatar } from '../../../components/game/Avatar';
import type { AttributeKey } from '../../../components/game/chips';
import { cn } from '../../../components/ui/cn';
import type { AuthResponse } from '../../../lib/api/client';
import type { components } from '../../../lib/api/schema';
import { AUTH_QUERY_KEY } from '../../auth/AuthProvider';
import { useAuth, useCurrentUser } from '../../auth/context';
import { UserGreeting } from '../../auth/UserGreeting';
import { CHARACTER_QUERY_KEY } from '../../character/api';
import { GOALS_QUERY_KEY } from '../../goals/api';

type OnboardingIn = components['schemas']['OnboardingIn'];
type OnboardingOut = components['schemas']['OnboardingOut'];

export const MAX_GOALS = 10;
export const MAX_NAME = 64;
export const MAX_NICKNAME = 64;
export const MAX_BIO = 500;
export const MAX_GOAL_TITLE = 200;

export const GOAL_PRESETS: { key: string; attribute: AttributeKey }[] = [
  { key: 'exercise', attribute: 'physical' },
  { key: 'discipline', attribute: 'discipline' },
  { key: 'read', attribute: 'intellectual' },
  { key: 'relationships', attribute: 'social' },
  { key: 'skills', attribute: 'intellectual' },
  { key: 'creative', attribute: 'creativity' },
  { key: 'sleep', attribute: 'wellbeing' },
];

const STEPS = ['character', 'goals', 'timezone'] as const;

interface ChosenGoal {
  title: string;
  attribute: AttributeKey | null;
}

/** The browser's IANA timezone, or UTC when it cannot be determined. */
export function detectTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
  } catch {
    return 'UTC';
  }
}

function timezoneOptions(current: string): string[] {
  let all: string[] = [];
  try {
    all = Intl.supportedValuesOf('timeZone');
  } catch {
    all = [];
  }
  return Array.from(new Set([current, 'UTC', ...all])).sort();
}

const inputClass = 'rounded-md border border-border bg-surface-2 px-3 py-2';

/** Character -> goals -> timezone; finishing calls POST /character/onboarding/complete. */
export function OnboardingPage() {
  const { t } = useTranslation('onboarding');
  const { api, telegram } = useAuth();
  const user = useCurrentUser();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const ids = useId();

  const [step, setStep] = useState(0);
  const [name, setName] = useState(() => user.display_name.slice(0, MAX_NAME));
  const [nickname, setNickname] = useState('');
  const [bio, setBio] = useState('');
  const [goals, setGoals] = useState<ChosenGoal[]>([]);
  const [custom, setCustom] = useState('');
  const [timezone, setTimezone] = useState(detectTimezone);
  const [nameError, setNameError] = useState(false);
  const options = useMemo(() => timezoneOptions(timezone), [timezone]);

  // Ask before Telegram closes the app while the form holds unsaved input.
  useEffect(() => {
    telegram.closingConfirmation(true);
    return () => telegram.closingConfirmation(false);
  }, [telegram]);

  const complete = useMutation({
    mutationFn: (body: OnboardingIn) => api.post<OnboardingOut>('/character/onboarding/complete', body),
    onSuccess: (result) => {
      queryClient.setQueryData<AuthResponse>(AUTH_QUERY_KEY, (old) => (old ? { ...old, user: result.user } : old));
      queryClient.setQueryData(CHARACTER_QUERY_KEY, result.character);
      void queryClient.invalidateQueries({ queryKey: GOALS_QUERY_KEY });
      telegram.haptic.notification('success');
      void navigate('/', { replace: true });
    },
    onError: () => telegram.haptic.notification('error'),
  });

  if (user.onboarded_at && !complete.isPending) return <Navigate to="/" replace />;

  const hasGoal = (title: string) => goals.some((g) => g.title.toLowerCase() === title.toLowerCase());
  const atLimit = goals.length >= MAX_GOALS;
  const presetTitles = new Set(GOAL_PRESETS.map((p) => t(`goals.presets.${p.key}`)));
  const customGoals = goals.filter((g) => !presetTitles.has(g.title));
  const toggleGoal = (goal: ChosenGoal) => {
    telegram.haptic.selection();
    setGoals((current) =>
      hasGoal(goal.title)
        ? current.filter((g) => g.title.toLowerCase() !== goal.title.toLowerCase())
        : current.length >= MAX_GOALS
          ? current
          : [...current, goal],
    );
  };
  const addCustom = () => {
    const title = custom.trim();
    if (!title || hasGoal(title) || atLimit) return;
    setGoals((current) => [...current, { title, attribute: null }]);
    setCustom('');
  };

  const next = (event: FormEvent) => {
    event.preventDefault();
    if (step === 0 && !name.trim()) {
      setNameError(true);
      return;
    }
    if (step < STEPS.length - 1) {
      setStep(step + 1);
      return;
    }
    complete.mutate({
      name: name.trim(),
      nickname: nickname.trim() || null,
      bio: bio.trim() || null,
      timezone,
      goals,
    });
  };

  const stepKey = STEPS[step]!;
  const last = step === STEPS.length - 1;

  return (
    <section data-testid="page-onboarding" className="flex min-h-screen flex-col gap-4 p-4">
      <header className="flex flex-col gap-1">
        <p className="text-xs text-muted" data-testid="onboarding-progress">
          {t('progress', { current: step + 1, total: STEPS.length })}
        </p>
        <h1 className="text-2xl font-bold">{t(`steps.${stepKey}`)}</h1>
      </header>

      <form onSubmit={next} noValidate className="flex flex-1 flex-col gap-4" data-testid={`onboarding-step-${stepKey}`}>
        {stepKey === 'character' ? (
          <>
            <div className="flex items-center gap-3">
              <Avatar name={name || user.display_name} src={user.avatar_url} size="lg" />
              <div className="flex flex-col">
                <UserGreeting />
                <p className="text-sm text-muted">{t('character.avatarHint')}</p>
              </div>
            </div>
            <label htmlFor={`${ids}-name`} className="text-sm font-medium">
              {t('character.name')}
            </label>
            <input
              id={`${ids}-name`}
              data-testid="onboarding-name"
              value={name}
              maxLength={MAX_NAME}
              required
              aria-invalid={nameError}
              aria-describedby={nameError ? `${ids}-name-error` : undefined}
              onChange={(e) => {
                setName(e.target.value);
                setNameError(false);
              }}
              className={inputClass}
            />
            {nameError ? (
              <p id={`${ids}-name-error`} role="alert" className="text-sm text-danger">
                {t('character.nameRequired')}
              </p>
            ) : null}
            <label htmlFor={`${ids}-nickname`} className="text-sm font-medium">
              {t('character.nickname')}
            </label>
            <input
              id={`${ids}-nickname`}
              data-testid="onboarding-nickname"
              value={nickname}
              maxLength={MAX_NICKNAME}
              onChange={(e) => setNickname(e.target.value)}
              className={inputClass}
            />
            <label htmlFor={`${ids}-bio`} className="text-sm font-medium">
              {t('character.bio')}
            </label>
            <textarea
              id={`${ids}-bio`}
              data-testid="onboarding-bio"
              value={bio}
              maxLength={MAX_BIO}
              rows={3}
              onChange={(e) => setBio(e.target.value)}
              className={inputClass}
            />
          </>
        ) : null}

        {stepKey === 'goals' ? (
          <>
            <div>
              <h2 className="font-semibold">{t('goals.title')}</h2>
              <p className="text-sm text-muted">{t('goals.hint')}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {GOAL_PRESETS.map((preset) => {
                const title = t(`goals.presets.${preset.key}`);
                const selected = hasGoal(title);
                return (
                  <button
                    key={preset.key}
                    type="button"
                    data-testid={`goal-preset-${preset.key}`}
                    aria-pressed={selected}
                    disabled={!selected && atLimit}
                    onClick={() => toggleGoal({ title, attribute: preset.attribute })}
                    className={cn(
                      'rounded-full border px-3 py-1 text-sm disabled:opacity-50',
                      selected ? 'border-accent bg-accent text-accent-fg' : 'border-border',
                    )}
                  >
                    {title}
                  </button>
                );
              })}
            </div>
            <label htmlFor={`${ids}-custom`} className="text-sm font-medium">
              {t('goals.custom')}
            </label>
            <div className="flex gap-2">
              <input
                id={`${ids}-custom`}
                data-testid="onboarding-custom-goal"
                value={custom}
                maxLength={MAX_GOAL_TITLE}
                onChange={(e) => setCustom(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    addCustom();
                  }
                }}
                className={cn(inputClass, 'flex-1')}
              />
              <button
                type="button"
                data-testid="onboarding-add-goal"
                disabled={!custom.trim() || atLimit}
                onClick={addCustom}
                className="rounded-md border border-border px-3 py-2 text-sm disabled:opacity-50"
              >
                {t('goals.add')}
              </button>
            </div>
            {atLimit ? <p className="text-sm text-muted">{t('goals.limit', { max: MAX_GOALS })}</p> : null}
            {customGoals.length > 0 ? (
              <ul className="flex flex-wrap gap-2" data-testid="onboarding-custom-goals">
                {customGoals.map((g) => (
                  <li
                    key={g.title}
                    className="inline-flex max-w-full items-center gap-1 rounded-full border border-accent px-3 py-1 text-sm"
                  >
                    <span className="truncate">{g.title}</span>
                    <button type="button" aria-label={t('goals.remove', { title: g.title })} onClick={() => toggleGoal(g)}>
                      <X aria-hidden="true" size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </>
        ) : null}

        {stepKey === 'timezone' ? (
          <>
            <p className="text-sm text-muted">{t('timezone.hint')}</p>
            <label htmlFor={`${ids}-tz`} className="text-sm font-medium">
              {t('timezone.label')}
            </label>
            <select
              id={`${ids}-tz`}
              data-testid="onboarding-timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              className={inputClass}
            >
              {options.map((tz) => (
                <option key={tz} value={tz}>
                  {tz}
                </option>
              ))}
            </select>
          </>
        ) : null}

        {complete.isError ? (
          <p role="alert" className="text-sm text-danger">
            {t('error')}
          </p>
        ) : null}

        <div className="mt-auto flex gap-2 pb-2">
          {step > 0 ? (
            <button
              type="button"
              data-testid="onboarding-back"
              onClick={() => setStep(step - 1)}
              className="flex-1 rounded-md border border-border px-4 py-3 text-sm"
            >
              {t('back')}
            </button>
          ) : null}
          <button
            type="submit"
            data-testid={last ? 'onboarding-finish' : 'onboarding-next'}
            disabled={complete.isPending}
            className="flex-[2] rounded-md bg-accent px-4 py-3 font-semibold text-accent-fg disabled:opacity-50"
          >
            {complete.isPending ? t('saving') : last ? t('finish') : t('next')}
          </button>
        </div>
      </form>
    </section>
  );
}
