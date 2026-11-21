import { fireEvent, screen, within } from '@testing-library/react';
import { describe, expect, test } from 'vitest';

import { ApiError } from '../../lib/api/client';
import { makeCharacter, renderApp } from '../../test/harness';

const CARD = {
  user_id: 2,
  display_name: 'Bohdan',
  avatar_url: null,
  character_name: 'Bold',
  nickname: 'the Bear',
  level: 4,
};

const PROFILE = {
  card: CARD,
  bio: 'Likes mountains',
  total_xp: 500,
  xp_into_level: 50,
  xp_for_next_level: 300,
  attributes: makeCharacter().attributes,
  goals: [{ id: 1, title: 'Run a marathon', description: null, attribute: 'physical', status: 'active' }],
  wishlist: [
    { id: 1, title: 'Cinema night', description: null, status: 'open' },
    { id: 2, title: 'Spa day', description: null, status: 'offered' },
  ],
};

const PAIRED = { partnership: { id: 9, accepted_at: '2026-01-15T12:00:00Z', companion: CARD }, pending_invitation: null };

describe('companion page', () => {
  test("shows the companion's profile, attributes, goals and wishlist", async () => {
    renderApp('/companion', { routes: { 'GET /partnership': PAIRED, 'GET /partnership/companion': PROFILE } });
    const profile = await screen.findByTestId('companion-profile');
    expect(within(profile).getByTestId('companion-name')).toHaveTextContent('Bold');
    expect(within(profile).getByText('the Bear')).toBeInTheDocument();
    expect(within(profile).getAllByText('Level 4').length).toBeGreaterThan(0);
    expect(within(profile).getByText('You are the Game Master')).toBeInTheDocument();
    expect(within(profile).getByText('Likes mountains')).toBeInTheDocument();
    expect(within(screen.getByTestId('companion-attributes')).getAllByRole('listitem')).toHaveLength(6);
    expect(screen.getByTestId('companion-goals')).toHaveTextContent('Run a marathon');
    const wishes = within(screen.getByTestId('companion-wishlist')).getAllByRole('listitem');
    expect(wishes).toHaveLength(2);
    expect(wishes[1]).toHaveTextContent('In the shop');
    expect(screen.queryByTestId('invite-panel')).toBeNull();
  });

  test('without a companion it shows the invite call to action', async () => {
    const { calls } = renderApp('/companion', {
      routes: { 'GET /partnership': { partnership: null, pending_invitation: null } },
    });
    expect(await screen.findByTestId('invite-panel')).toBeInTheDocument();
    expect(screen.getByText('You have no companion yet')).toBeInTheDocument();
    expect(calls.map((c) => c.path)).not.toContain('/partnership/companion');
  });

  test('a load error offers a retry', async () => {
    let fail = true;
    renderApp('/companion', {
      routes: {
        'GET /partnership': () => {
          if (fail) throw new ApiError(500, 'boom');
          return PAIRED;
        },
        'GET /partnership/companion': PROFILE,
      },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load');
    fail = false;
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }));
    expect(await screen.findByTestId('companion-profile')).toBeInTheDocument();
  });
});
