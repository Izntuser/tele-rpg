import { describe, expect, test } from 'vitest';

import { deeplinkToRoute } from './deeplink';

describe('deeplinkToRoute', () => {
  test('invite_<token> -> /invite/<token>', () => {
    expect(deeplinkToRoute('invite_abc123')).toBe('/invite/abc123');
    expect(deeplinkToRoute('invite_a-B_9')).toBe('/invite/a-B_9');
  });
  test('q_<id> -> /quests/<id>', () => {
    expect(deeplinkToRoute('q_42')).toBe('/quests/42');
  });
  test('qt_<id> (a recurring offer) -> /quests', () => {
    expect(deeplinkToRoute('qt_5')).toBe('/quests');
  });
  test('r_<id> -> /shop/inventory?item=<id>', () => {
    expect(deeplinkToRoute('r_7')).toBe('/shop/inventory?item=7');
  });
  test('rq_<id> -> the requests in the shop I run', () => {
    expect(deeplinkToRoute('rq_7')).toBe('/shop/manage');
  });
  test('rw_<id> -> the shop', () => {
    expect(deeplinkToRoute('rw_3')).toBe('/shop');
  });
  test('p_<id> -> the companion page', () => {
    expect(deeplinkToRoute('p_1')).toBe('/companion');
  });
  test('unknown, empty or malformed -> /', () => {
    for (const value of [
      null,
      undefined,
      '',
      'foo',
      'inv_1',
      'q_',
      'invite_',
      'q_../x',
      'q_a b',
      'q_abc',
      'r_1x',
      'qt_',
    ]) {
      expect(deeplinkToRoute(value), String(value)).toBe('/');
    }
  });
});
