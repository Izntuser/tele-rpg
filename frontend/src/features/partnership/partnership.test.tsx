import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { setLocale } from '../../i18n';
import { ApiError } from '../../lib/api/client';
import { makeCharacter, makeUser, renderApp } from '../../test/harness';
import { inviteProblem } from './api';
import { shareUrl } from './InvitePanel';

const INVITER = {
  user_id: 2,
  display_name: 'Bohdan',
  avatar_url: null,
  character_name: 'Bold',
  nickname: 'the Bear',
  level: 3,
};
const PREVIEW = { inviter: INVITER, expires_at: '2026-01-22T12:00:00Z' };

afterEach(() => {
  setLocale('en');
  vi.restoreAllMocks();
});

describe('inviteProblem', () => {
  test('maps API errors to messages', () => {
    expect(inviteProblem(new ApiError(404, 'Invitation not found'))).toBe('invalid');
    expect(inviteProblem(new ApiError(410, 'Invitation expired'))).toBe('invalid');
    expect(inviteProblem(new ApiError(422, []))).toBe('invalid');
    expect(inviteProblem(new ApiError(409, 'You cannot accept your own invitation'))).toBe('own');
    expect(inviteProblem(new ApiError(409, 'Complete onboarding first'))).toBe('onboarding');
    expect(inviteProblem(new ApiError(409, 'Already in a partnership'))).toBe('paired');
    expect(inviteProblem(new ApiError(500, 'x'))).toBe('generic');
    expect(inviteProblem(new Error('x'))).toBe('generic');
  });

  test('shareUrl encodes the link for the Telegram share sheet', () => {
    expect(shareUrl('https://t.me/b/a?startapp=invite_x', 'Hi & bye')).toBe(
      'https://t.me/share/url?url=https%3A%2F%2Ft.me%2Fb%2Fa%3Fstartapp%3Dinvite_x&text=Hi%20%26%20bye',
    );
  });
});

describe('invite page', () => {
  test('shows the inviter and accepting opens the Companion page', async () => {
    const accept = vi.fn(() => ({
      partnership: { id: 9, accepted_at: '2026-01-15T12:00:00Z', companion: INVITER },
      reactivated: false,
    }));
    const { router, calls, adapter } = renderApp('/invite/tok_abc', {
      routes: {
        'POST /partnership/invitations/preview': PREVIEW,
        'POST /partnership/invitations/accept': accept,
        'GET /partnership': { partnership: { id: 9, accepted_at: null, companion: INVITER }, pending_invitation: null },
        'GET /partnership/companion': {
          card: INVITER,
          bio: null,
          total_xp: 300,
          xp_into_level: 50,
          xp_for_next_level: 250,
          attributes: makeCharacter().attributes,
          goals: [],
          wishlist: [],
        },
        'GET /character': makeCharacter(),
      },
    });
    expect(await screen.findByTestId('invite-inviter')).toHaveTextContent('Bold');
    expect(screen.getByText('Level 3')).toBeInTheDocument();
    // The token travels in the body, never in the request path.
    expect(calls[0]).toMatchObject({ path: '/partnership/invitations/preview', body: { token: 'tok_abc' } });
    await act(async () => fireEvent.click(screen.getByTestId('invite-accept')));
    await waitFor(() => expect(router.state.location.pathname).toBe('/companion'));
    expect(accept).toHaveBeenCalledWith({ token: 'tok_abc' }, '/partnership/invitations/accept');
    expect(await screen.findByTestId('companion-profile')).toBeInTheDocument();
    expect(adapter.calls).toContainEqual({ method: 'haptic.notification', args: ['success'] });
  });

  test('an expired invitation shows an error and no accept button', async () => {
    renderApp('/invite/tok_old', {
      routes: {
        'POST /partnership/invitations/preview': () => {
          throw new ApiError(410, 'Invitation expired');
        },
      },
    });
    expect(await screen.findByTestId('invite-error')).toHaveTextContent('no longer valid');
    expect(screen.queryByTestId('invite-accept')).toBeNull();
  });

  test('a failed accept explains why', async () => {
    renderApp('/invite/tok_abc', {
      routes: {
        'POST /partnership/invitations/preview': PREVIEW,
        'POST /partnership/invitations/accept': () => {
          throw new ApiError(409, 'Already in a partnership');
        },
      },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('invite-accept')));
    expect(await screen.findByTestId('invite-error')).toHaveTextContent('already has a companion');
  });

  test('"Not now" goes Home', async () => {
    const { router } = renderApp('/invite/tok_abc', {
      routes: { 'POST /partnership/invitations/preview': PREVIEW, 'GET /character': makeCharacter() },
    });
    fireEvent.click(await screen.findByTestId('invite-dismiss'));
    await waitFor(() => expect(router.state.location.pathname).toBe('/'));
  });

  test('a new user is asked to create a character first', async () => {
    const { router } = renderApp('/invite/tok_abc', {
      user: makeUser({ onboarded_at: null }),
      routes: { 'POST /partnership/invitations/preview': PREVIEW },
    });
    fireEvent.click(await screen.findByTestId('invite-onboard'));
    await waitFor(() => expect(router.state.location.pathname).toBe('/onboarding'));
    expect(router.state.location.state).toEqual({ deeplink: true, inviteToken: 'tok_abc' });
  });

  test('is translated to Ukrainian', async () => {
    renderApp('/invite/tok_abc', {
      user: makeUser({ locale: 'uk' }),
      routes: { 'POST /partnership/invitations/preview': PREVIEW },
    });
    expect(await screen.findByText('Вас запрошено!')).toBeInTheDocument();
  });
});

describe('invite panel', () => {
  test('creates a link, copies it, and can regenerate', async () => {
    const writeText = vi.fn(() => Promise.resolve());
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    let n = 0;
    renderApp('/companion', {
      routes: {
        'GET /partnership': { partnership: null, pending_invitation: null },
        'POST /partnership/invitations': () => {
          n += 1;
          return { token: `t${n}`, link: `https://t.me/b/a?startapp=invite_t${n}`, expires_at: '2026-01-22T12:00:00Z' };
        },
      },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('invite-create')));
    expect(await screen.findByTestId('invite-link')).toHaveValue('https://t.me/b/a?startapp=invite_t1');
    await act(async () => fireEvent.click(screen.getByTestId('invite-copy')));
    expect(writeText).toHaveBeenCalledWith('https://t.me/b/a?startapp=invite_t1');
    expect(screen.getByTestId('invite-copy')).toHaveTextContent('Copied');
    await act(async () => fireEvent.click(screen.getByTestId('invite-create')));
    expect(await screen.findByDisplayValue('https://t.me/b/a?startapp=invite_t2')).toBeInTheDocument();
  });

  test('shows an error when the invite cannot be created', async () => {
    renderApp('/companion', {
      routes: {
        'GET /partnership': { partnership: null, pending_invitation: { expires_at: '2026-01-22T12:00:00Z' } },
        'POST /partnership/invitations': () => {
          throw new ApiError(409, 'Already in a partnership');
        },
      },
    });
    expect(await screen.findByTestId('invite-pending')).toBeInTheDocument();
    await act(async () => fireEvent.click(screen.getByTestId('invite-create')));
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not create');
  });
});
