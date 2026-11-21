import { act, screen, within } from '@testing-library/react';
import { afterEach, expect, test } from 'vitest';

import { setLocale } from '../../i18n';
import { ApiError } from '../../lib/api/client';
import { makeCharacter, makeUser, renderApp } from '../../test/harness';

afterEach(() => setLocale('en'));

test('Home shows avatar, name, level, XP bar, gold and attribute levels', async () => {
  const character = makeCharacter({
    name: 'Aria',
    nickname: 'The Brave',
    avatar_url: 'https://t.me/i/aria.jpg',
    attributes: makeCharacter().attributes.map((a) =>
      a.attribute === 'discipline' ? { ...a, xp: 120, level: 2 } : a,
    ),
  });
  renderApp('/', { routes: { 'GET /character': character } });

  const header = await screen.findByTestId('character-header');
  expect(within(header).getByTestId('character-name')).toHaveTextContent('Aria');
  expect(within(header).getByTestId('character-nickname')).toHaveTextContent('The Brave');
  expect(within(header).getByRole('img', { name: 'Aria' })).toHaveAttribute('src', 'https://t.me/i/aria.jpg');
  expect(within(header).getByLabelText('75 gold')).toBeInTheDocument();
  expect(within(header).getByText('10 / 200 XP')).toBeInTheDocument();
  const bar = within(header).getByRole('progressbar');
  expect(bar).toHaveAttribute('aria-valuenow', '10');
  expect(bar).toHaveAccessibleName('Level 3');
  expect(screen.getByTestId('attribute-level-discipline')).toHaveTextContent('Lv 2');
  expect(screen.getByTestId('attribute-level-physical')).toHaveTextContent('Physical');
  expect(within(screen.getByTestId('attribute-grid')).getAllByRole('listitem')).toHaveLength(6);
  expect(screen.getByTestId('home-goals-link')).toHaveAttribute('href', '/me/goals');
  expect(screen.getByTestId('home-wishlist-link')).toHaveAttribute('href', '/me/wishlist');
});

test('Home falls back to the initial without an avatar and hides an empty nickname', async () => {
  renderApp('/', { routes: { 'GET /character': makeCharacter({ name: 'zed', gold: 0 }) } });
  const header = await screen.findByTestId('character-header');
  expect(within(header).getByRole('img', { name: 'zed' })).toHaveTextContent('Z');
  expect(within(header).queryByTestId('character-nickname')).toBeNull();
  expect(within(header).getByLabelText('0 gold')).toBeInTheDocument();
});

test('Home shows an inline error with retry when the character fails to load', async () => {
  let calls = 0;
  const { request } = renderApp('/', {
    routes: {
      'GET /character': () => {
        calls += 1;
        if (calls === 1) throw new ApiError(500, 'boom');
        return makeCharacter();
      },
    },
  });
  expect(await screen.findByRole('alert')).toHaveTextContent('Could not load your character');
  await act(async () => screen.getByRole('button', { name: 'Try again' }).click());
  expect(await screen.findByTestId('character-header')).toBeInTheDocument();
  // Home also loads the partnership / quests for the today panel; count only the character.
  expect(request.mock.calls.filter((c) => c[1] === '/character')).toHaveLength(2);
});

test('Home follows the uk locale', async () => {
  renderApp('/', { user: makeUser({ locale: 'uk' }), routes: { 'GET /character': makeCharacter() } });
  expect(await screen.findByTestId('attribute-level-physical')).toHaveTextContent('Рів. 1');
  expect(screen.getByTestId('home-goals-link')).toHaveTextContent('Хочу покращити');
});
