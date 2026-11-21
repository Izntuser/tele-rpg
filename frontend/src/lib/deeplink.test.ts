import { describe, expect, test } from 'vitest';

import { deeplinkToRoute } from './deeplink';

describe('deeplinkToRoute', () => {
  test('invite_<token> -> /invite/<token>', () => {
    expect(deeplinkToRoute('invite_abc123')).toBe('/invite/abc123');
  });
  test('q_<id> -> /quests/<id>', () => {
    expect(deeplinkToRoute('q_42')).toBe('/quests/42');
  });
  test('r_<id> -> /shop/inventory?item=<id>', () => {
    expect(deeplinkToRoute('r_7')).toBe('/shop/inventory?item=7');
  });
  test('unknown, empty or malformed -> /', () => {
    for (const value of [null, undefined, '', 'foo', 'inv_1', 'q_', 'invite_', 'q_../x', 'q_a b']) {
      expect(deeplinkToRoute(value), String(value)).toBe('/');
    }
  });
});
