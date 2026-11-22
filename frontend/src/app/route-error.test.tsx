import { render, screen, waitFor } from '@testing-library/react';
import { RouterProvider, createMemoryRouter } from 'react-router';
import { afterEach, beforeEach, expect, test, vi } from 'vitest';

import { setLocale } from '../i18n';
import { renderApp } from '../test/harness';
import { RouteError } from './RouteError';

beforeEach(() => {
  vi.spyOn(console, 'error').mockImplementation(() => {});
});

afterEach(() => {
  setLocale('en');
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function Boom(): never {
  throw new Error('boom');
}

function renderBroken() {
  const router = createMemoryRouter([{ path: '/', element: <Boom />, errorElement: <RouteError /> }]);
  return render(<RouterProvider router={router} />);
}

test('a render error shows the friendly screen with a reload button, not the router dev page', () => {
  const reload = vi.fn();
  vi.stubGlobal('location', { ...window.location, reload });
  renderBroken();
  expect(screen.getByTestId('route-error')).toHaveTextContent('Something went wrong');
  expect(screen.queryByText(/Unexpected Application Error/i)).toBeNull();
  screen.getByRole('button', { name: 'Reload' }).click();
  expect(reload).toHaveBeenCalled();
});

test('the error screen is translated', () => {
  setLocale('uk');
  renderBroken();
  expect(screen.getByRole('heading')).toHaveTextContent('Щось пішло не так');
  expect(screen.getByRole('button', { name: 'Перезавантажити' })).toBeInTheDocument();
});

test('a /character answer that is not a character no longer crashes Avatar and the whole app', async () => {
  // Root cause: a 2xx non-JSON body (tunnel/proxy page) was cached as the character, and
  // CharacterHeader passed its undefined `name` to Avatar (name.trim) -> default router error page.
  renderApp('/', { routes: { 'GET /character': '<html>not json</html>' } });
  expect(await screen.findByTestId('page-home')).toBeInTheDocument();
  await waitFor(() => expect(screen.getByRole('alert')).toBeInTheDocument());
  expect(screen.queryByTestId('route-error')).toBeNull();
  expect(screen.queryByTestId('character-header')).toBeNull();
});
