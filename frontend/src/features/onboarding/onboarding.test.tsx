import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { setLocale } from '../../i18n';
import { ApiError } from '../../lib/api/client';
import { makeCharacter, makeUser, renderApp } from '../../test/harness';
import { detectTimezone } from './pages/OnboardingPage';
import { deeplinkAllowedBeforeOnboarding, isOnboardingRoute, needsOnboarding } from './redirect';

const NEW_USER = makeUser({ onboarded_at: null, display_name: 'Alice Archer', avatar_url: 'https://t.me/i/a.jpg' });

afterEach(() => {
  setLocale('en');
  vi.restoreAllMocks();
});

describe('redirect rules', () => {
  test('needsOnboarding', () => {
    expect(needsOnboarding(null, '/')).toBe(true);
    expect(needsOnboarding(null, '/quests/3')).toBe(true);
    expect(needsOnboarding(null, '/onboardingx')).toBe(true);
    expect(needsOnboarding(null, '/onboarding')).toBe(false);
    expect(needsOnboarding(null, '/onboarding/goals')).toBe(false);
    expect(needsOnboarding(null, '/invite/tok')).toBe(false);
    expect(needsOnboarding('2026-01-01T00:00:00Z', '/')).toBe(false);
  });

  test('only invitation deeplinks open before onboarding', () => {
    expect(deeplinkAllowedBeforeOnboarding('/invite/abc')).toBe(true);
    expect(deeplinkAllowedBeforeOnboarding('/quests/1')).toBe(false);
    expect(isOnboardingRoute('/onboarding')).toBe(true);
    expect(isOnboardingRoute('/')).toBe(false);
  });

  test('detectTimezone falls back to UTC', () => {
    vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(() => {
      throw new Error('no Intl');
    });
    expect(detectTimezone()).toBe('UTC');
  });
});

describe('routing', () => {
  test('a user who has not onboarded is sent from Home to onboarding, and Back is hidden', async () => {
    const { router, adapter } = renderApp('/', { user: NEW_USER });
    expect(await screen.findByTestId('page-onboarding')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/onboarding');
    // Flagged as the first entry, like the deeplink redirect.
    expect(router.state.location.state).toEqual({ deeplink: true });
    expect(adapter.calls.map((c) => c.method)).not.toContain('backButton.show');
    expect(screen.queryByRole('navigation')).toBeNull();
  });

  test('any other screen also redirects', async () => {
    const { router } = renderApp('/shop', { user: NEW_USER });
    await screen.findByTestId('page-onboarding');
    expect(router.state.location.pathname).toBe('/onboarding');
  });

  test('an invitation link opens without onboarding', async () => {
    const { router } = renderApp('/invite/tok', { user: NEW_USER });
    expect(await screen.findByTestId('page-invite')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/invite/tok');
  });

  test('a quest deeplink is dropped for a new user; an invite deeplink is kept', async () => {
    const quest = renderApp('/', { user: NEW_USER, telegram: { startParam: 'q_5' } });
    await screen.findByTestId('page-onboarding');
    expect(quest.router.state.location.pathname).toBe('/onboarding');
    quest.view.unmount();

    const invite = renderApp('/', { user: NEW_USER, telegram: { startParam: 'invite_abc' } });
    await waitFor(() => expect(invite.router.state.location.pathname).toBe('/invite/abc'));
  });

  test('an onboarded user visiting onboarding goes Home', async () => {
    const { router } = renderApp('/onboarding', { routes: { 'GET /character': makeCharacter() } });
    expect(await screen.findByTestId('page-home')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/');
  });
});

describe('flow', () => {
  function completeRoute() {
    return vi.fn((body: unknown) => {
      const b = body as { name: string; timezone: string };
      return {
        user: { ...NEW_USER, timezone: b.timezone, onboarded_at: '2026-01-15T12:00:00Z' },
        character: makeCharacter({ name: b.name, avatar_url: NEW_USER.avatar_url }),
      };
    });
  }

  test('character -> goals -> timezone, then POST /character/onboarding/complete and Home', async () => {
    const complete = completeRoute();
    const { router, calls, adapter } = renderApp('/', {
      user: NEW_USER,
      routes: { 'POST /character/onboarding/complete': complete, 'GET /goals': [] },
    });

    // Step 1: name prefilled from Telegram, Telegram photo as the avatar.
    const name = await screen.findByLabelText('Character name');
    expect(name).toHaveValue('Alice Archer');
    expect(screen.getByRole('img', { name: 'Alice Archer' })).toHaveAttribute('src', 'https://t.me/i/a.jpg');
    expect(screen.getByTestId('user-greeting')).toHaveTextContent('Alice Archer');
    expect(screen.getByText('Step 1 of 3')).toBeInTheDocument();
    fireEvent.change(name, { target: { value: '  ' } });
    fireEvent.click(screen.getByTestId('onboarding-next'));
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a name');
    expect(screen.getByTestId('onboarding-step-character')).toBeInTheDocument();
    fireEvent.change(name, { target: { value: ' Aria ' } });
    fireEvent.change(screen.getByLabelText('Nickname (optional)'), { target: { value: 'The Brave' } });
    fireEvent.click(screen.getByTestId('onboarding-next'));

    // Step 2: pick a preset and type a custom goal.
    expect(await screen.findByTestId('onboarding-step-goals')).toBeInTheDocument();
    const preset = screen.getByTestId('goal-preset-read');
    fireEvent.click(preset);
    expect(preset).toHaveAttribute('aria-pressed', 'true');
    fireEvent.change(screen.getByLabelText('Your own goal'), { target: { value: 'Learn Rust' } });
    fireEvent.click(screen.getByTestId('onboarding-add-goal'));
    fireEvent.change(screen.getByLabelText('Your own goal'), { target: { value: 'Swim' } });
    fireEvent.keyDown(screen.getByLabelText('Your own goal'), { key: 'Enter' });
    fireEvent.click(screen.getByRole('button', { name: 'Remove Swim' }));
    expect(within(screen.getByTestId('onboarding-custom-goals')).getAllByRole('listitem')).toHaveLength(1);
    fireEvent.click(screen.getByTestId('onboarding-next'));

    // Step 3: timezone prefilled from the browser, editable.
    const tz = await screen.findByLabelText('Timezone');
    expect(tz).toHaveValue(detectTimezone());
    fireEvent.change(tz, { target: { value: 'America/New_York' } });
    await act(async () => fireEvent.click(screen.getByTestId('onboarding-finish')));

    expect(await screen.findByTestId('page-home')).toBeInTheDocument();
    expect(router.state.location.pathname).toBe('/');
    expect(complete).toHaveBeenCalledTimes(1);
    expect(calls.find((c) => c.path === '/character/onboarding/complete')?.body).toEqual({
      name: 'Aria',
      nickname: 'The Brave',
      bio: null,
      timezone: 'America/New_York',
      goals: [
        { title: 'Read more books', attribute: 'intellectual' },
        { title: 'Learn Rust', attribute: null },
      ],
    });
    // The Home header is fed from the onboarding response (no extra fetch needed).
    expect(await screen.findByTestId('character-name')).toHaveTextContent('Aria');
    expect(adapter.calls).toContainEqual({ method: 'haptic.notification', args: ['success'] });
  });

  test('Back returns to the previous step and keeps the input', async () => {
    renderApp('/onboarding', { user: NEW_USER });
    fireEvent.change(await screen.findByLabelText('Character name'), { target: { value: 'Zed' } });
    fireEvent.click(screen.getByTestId('onboarding-next'));
    fireEvent.click(await screen.findByTestId('onboarding-back'));
    expect(screen.getByLabelText('Character name')).toHaveValue('Zed');
  });

  test('at most 10 goals can be chosen', async () => {
    renderApp('/onboarding', { user: NEW_USER });
    fireEvent.click(await screen.findByTestId('onboarding-next'));
    const input = await screen.findByLabelText('Your own goal');
    for (let i = 0; i < 10; i++) {
      fireEvent.change(input, { target: { value: `goal ${i}` } });
      fireEvent.click(screen.getByTestId('onboarding-add-goal'));
    }
    expect(screen.getByText('You can choose up to 10 goals.')).toBeInTheDocument();
    expect(screen.getByTestId('goal-preset-read')).toBeDisabled();
    fireEvent.change(input, { target: { value: 'goal 11' } });
    expect(screen.getByTestId('onboarding-add-goal')).toBeDisabled();
  });

  test('a failed save shows an inline error and stays on the last step', async () => {
    const { router } = renderApp('/onboarding', {
      user: NEW_USER,
      routes: {
        'POST /character/onboarding/complete': () => {
          throw new ApiError(422, 'bad');
        },
      },
    });
    fireEvent.click(await screen.findByTestId('onboarding-next'));
    fireEvent.click(await screen.findByTestId('onboarding-next'));
    await act(async () => fireEvent.click(await screen.findByTestId('onboarding-finish')));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save');
    expect(router.state.location.pathname).toBe('/onboarding');
  });

  test('asks Telegram to confirm closing while onboarding', async () => {
    const { adapter, view } = renderApp('/onboarding', { user: NEW_USER });
    await screen.findByTestId('page-onboarding');
    expect(adapter.calls).toContainEqual({ method: 'closingConfirmation', args: [true] });
    view.unmount();
    expect(adapter.calls).toContainEqual({ method: 'closingConfirmation', args: [false] });
  });

  test('is translated to Ukrainian', async () => {
    renderApp('/onboarding', { user: { ...NEW_USER, locale: 'uk' } });
    expect(await screen.findByText('Ім\'я персонажа')).toBeInTheDocument();
    expect(screen.getByTestId('onboarding-next')).toHaveTextContent('Далі');
  });
});
