import { act, fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, test, vi } from 'vitest';

import { setLocale } from '../../i18n';
import { ApiError } from '../../lib/api/client';
import { makeCharacter, makeUser, renderApp } from '../../test/harness';
import { AUTH_QUERY_KEY } from '../auth/AuthProvider';

const CARD = { user_id: 2, display_name: 'Bohdan', avatar_url: null, character_name: 'Bold', nickname: null, level: 2 };
const PAIRED = { partnership: { id: 9, accepted_at: null, companion: CARD }, pending_invitation: null };
const UNPAIRED = { partnership: null, pending_invitation: null };

afterEach(() => {
  setLocale('en');
  vi.restoreAllMocks();
});

describe('settings', () => {
  test('changing the language re-renders the UI in Ukrainian', async () => {
    const patch = vi.fn((body: unknown) => makeCharacter({ ...(body as object), locale: 'uk' }));
    const { calls } = renderApp('/settings', {
      routes: { 'GET /partnership': UNPAIRED, 'PATCH /character': patch },
    });
    expect(await screen.findByRole('heading', { name: 'Settings', level: 1 })).toBeInTheDocument();
    await act(async () => fireEvent.change(screen.getByLabelText('App language'), { target: { value: 'uk' } }));
    expect(await screen.findByRole('heading', { name: 'Налаштування', level: 1 })).toBeInTheDocument();
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ locale: 'uk' });
    expect(screen.getByLabelText('Мова застосунку')).toHaveValue('uk');
    // The bottom navigation follows too.
    expect(screen.getByRole('navigation', { name: 'Головна навігація' })).toBeInTheDocument();
  });

  test('changing the timezone saves it', async () => {
    const { calls, queryClient } = renderApp('/settings', {
      routes: {
        'GET /partnership': UNPAIRED,
        'PATCH /character': (body: unknown) => makeCharacter({ timezone: (body as { timezone: string }).timezone }),
      },
    });
    const select = await screen.findByLabelText('Your timezone');
    expect(select).toHaveValue('UTC');
    await act(async () => fireEvent.change(select, { target: { value: 'Europe/Berlin' } }));
    expect(calls.find((c) => c.method === 'PATCH')?.body).toEqual({ timezone: 'Europe/Berlin' });
    await waitFor(() => expect(screen.getByLabelText('Your timezone')).toHaveValue('Europe/Berlin'));
    expect(await screen.findByRole('status')).toHaveTextContent('Saved');
    const session = queryClient.getQueryData<{ user: { timezone: string } }>(AUTH_QUERY_KEY);
    expect(session?.user.timezone).toBe('Europe/Berlin');
  });

  test('a failed save shows an error', async () => {
    renderApp('/settings', {
      routes: {
        'GET /partnership': UNPAIRED,
        'PATCH /character': () => {
          throw new ApiError(422, 'bad');
        },
      },
    });
    await act(async () =>
      fireEvent.change(await screen.findByLabelText('Your timezone'), { target: { value: 'Europe/Berlin' } }),
    );
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not save');
  });

  test('leaving needs the typed confirmation in a ConfirmSheet', async () => {
    const leave = vi.fn(() => undefined);
    let state: unknown = PAIRED;
    const { calls } = renderApp('/settings', {
      routes: {
        'GET /partnership': () => state,
        'POST /partnership/leave': () => {
          state = UNPAIRED;
          return leave();
        },
      },
    });
    expect(await screen.findByTestId('settings-companion')).toHaveTextContent('Bold');
    fireEvent.click(screen.getByTestId('settings-leave'));
    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Leave the partnership?');
    const confirm = screen.getAllByRole('button', { name: 'Leave partnership' }).at(-1)!;
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Type "LEAVE" to confirm'), { target: { value: 'leave' } });
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Type "LEAVE" to confirm'), { target: { value: 'LEAVE' } });
    await act(async () => fireEvent.click(confirm));
    expect(leave).toHaveBeenCalledTimes(1);
    expect(calls.find((c) => c.path === '/partnership/leave')?.body).toEqual({ confirm_text: 'LEAVE' });
    expect(await screen.findByText('You have no companion yet.')).toBeInTheDocument();
  });

  test('cancelling the sheet does nothing', async () => {
    const { calls } = renderApp('/settings', { routes: { 'GET /partnership': PAIRED } });
    fireEvent.click(await screen.findByTestId('settings-leave'));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    expect(calls.map((c) => c.path)).not.toContain('/partnership/leave');
  });

  test('deleting the account ends the session instead of silently signing in again', async () => {
    const { calls, api } = renderApp('/settings', {
      routes: { 'GET /partnership': UNPAIRED, 'DELETE /account': undefined },
    });
    const logout = vi.spyOn(api, 'logout');
    fireEvent.click(await screen.findByTestId('settings-delete'));
    const confirm = screen.getAllByRole('button', { name: 'Delete account' }).at(-1)!;
    expect(confirm).toBeDisabled();
    fireEvent.change(screen.getByLabelText('Type "DELETE" to confirm'), { target: { value: 'DELETE' } });
    await act(async () => fireEvent.click(confirm));
    expect(calls.find((c) => c.path === '/account')).toMatchObject({
      method: 'DELETE',
      body: { confirm_text: 'DELETE' },
    });
    expect(await screen.findByRole('alert')).toHaveTextContent('This account has been deleted.');
    expect(logout).toHaveBeenCalled();
    expect(screen.queryByTestId('page-settings')).toBeNull();
  });

  test('export downloads my data', async () => {
    const createObjectURL = vi.fn(() => 'blob:x');
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {});
    renderApp('/settings', {
      routes: { 'GET /partnership': UNPAIRED, 'GET /account/export': { user: { id: 1 } } },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('settings-export')));
    await waitFor(() => expect(click).toHaveBeenCalled());
    expect(createObjectURL).toHaveBeenCalledTimes(1);
    expect(screen.getByTestId('settings-privacy')).toHaveTextContent('Telegram id');
  });

  test('uses no native dialogs', async () => {
    const alert = vi.spyOn(window, 'alert');
    const confirm = vi.spyOn(window, 'confirm');
    const prompt = vi.spyOn(window, 'prompt');
    renderApp('/settings', { user: makeUser(), routes: { 'GET /partnership': PAIRED, 'DELETE /account': undefined } });
    fireEvent.click(await screen.findByTestId('settings-leave'));
    fireEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
    fireEvent.click(screen.getByTestId('settings-delete'));
    expect(alert).not.toHaveBeenCalled();
    expect(confirm).not.toHaveBeenCalled();
    expect(prompt).not.toHaveBeenCalled();
  });
});
