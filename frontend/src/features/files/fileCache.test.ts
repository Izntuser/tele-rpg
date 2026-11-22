import { QueryClient } from '@tanstack/react-query';
import { describe, expect, test } from 'vitest';

import type { ApiClient } from '../../lib/api/client';
import { AUTH_QUERY_KEY } from '../auth/AuthProvider';
import { PARTNERSHIP_QUERY_KEY, invalidatePartnership } from '../partnership/api';
import { endDeletedSession } from '../settings/api';
import { FILE_KEY, watchFileAccess } from './api';

const blob = new Blob(['x']);

function setup() {
  const client = new QueryClient();
  const stop = watchFileAccess(client);
  client.setQueryData(AUTH_QUERY_KEY, { user: { id: 1 } });
  client.setQueryData(PARTNERSHIP_QUERY_KEY, { partnership: { id: 5 }, pending_invitation: null });
  const cache = (id = 42) => client.setQueryData([...FILE_KEY, id], blob);
  const cached = (id = 42) => client.getQueryData([...FILE_KEY, id]) !== undefined;
  cache();
  return { client, stop, cache, cached };
}

describe('file cache follows read access', () => {
  test('a refetch of the same partnership and user keeps the blobs', () => {
    const { client, cached } = setup();
    client.setQueryData(PARTNERSHIP_QUERY_KEY, { partnership: { id: 5 }, pending_invitation: null });
    client.setQueryData(AUTH_QUERY_KEY, { user: { id: 1 } });
    expect(cached()).toBe(true);
  });

  test('the partnership ending (seen on refetch) or changing drops the blobs', () => {
    const { client, cached, cache } = setup();
    client.setQueryData(PARTNERSHIP_QUERY_KEY, { partnership: null, pending_invitation: null });
    expect(cached()).toBe(false);
    cache(43);
    client.setQueryData(PARTNERSHIP_QUERY_KEY, { partnership: { id: 9 }, pending_invitation: null });
    expect(cached(43)).toBe(false);
  });

  test('another user logging in drops the blobs', () => {
    const { client, cached } = setup();
    client.setQueryData(AUTH_QUERY_KEY, { user: { id: 2 } });
    expect(cached()).toBe(false);
  });

  test('removing the session or partnership query (logout) drops the blobs', () => {
    const { client, cached, cache } = setup();
    client.removeQueries({ queryKey: AUTH_QUERY_KEY });
    expect(cached()).toBe(false);
    cache();
    client.removeQueries({ queryKey: PARTNERSHIP_QUERY_KEY });
    expect(cached()).toBe(false);
  });

  test('leaving or accepting a partnership (invalidatePartnership) drops the blobs', async () => {
    const client = new QueryClient();
    client.setQueryData([...FILE_KEY, 1], blob);
    await invalidatePartnership(client);
    expect(client.getQueryData([...FILE_KEY, 1])).toBeUndefined();
  });

  test('ending the session after account deletion drops the blobs', () => {
    const { client, cached } = setup();
    const api = { logout: () => {} } as unknown as ApiClient;
    endDeletedSession(client, api);
    expect(cached()).toBe(false);
  });

  test('unsubscribing stops the watcher', () => {
    const { client, cached, stop } = setup();
    stop();
    client.setQueryData(AUTH_QUERY_KEY, { user: { id: 2 } });
    expect(cached()).toBe(true);
  });
});
