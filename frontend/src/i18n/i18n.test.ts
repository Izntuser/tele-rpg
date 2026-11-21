import { afterEach, describe, expect, test } from 'vitest';

import { DEFAULT_LOCALE, buildResources, i18n, setLocale } from './index';

function flatKeys(value: unknown, prefix = ''): string[] {
  if (value === null || typeof value !== 'object') return [prefix];
  return Object.entries(value as Record<string, unknown>).flatMap(([k, v]) =>
    flatKeys(v, prefix ? `${prefix}.${k}` : k),
  );
}

function leaf(catalog: unknown, key: string): unknown {
  return key.split('.').reduce<unknown>((o, p) => (o as Record<string, unknown>)[p], catalog);
}

describe('catalogs', () => {
  const resources = buildResources();

  test('en and uk have the same namespaces', () => {
    expect(Object.keys(resources.uk!).sort()).toEqual(Object.keys(resources.en!).sort());
    expect(Object.keys(resources.en!)).toContain('common');
  });

  test('en and uk have identical key sets in every namespace', () => {
    for (const ns of Object.keys(resources.en!)) {
      expect(flatKeys(resources.uk![ns]).sort(), ns).toEqual(flatKeys(resources.en![ns]).sort());
    }
  });

  test('no translation is empty', () => {
    for (const locale of Object.keys(resources)) {
      for (const [ns, catalog] of Object.entries(resources[locale]!)) {
        const empty = flatKeys(catalog).filter((k) => {
          const text = leaf(catalog, k);
          return typeof text !== 'string' || text.trim() === '';
        });
        expect(empty, `${locale}/${ns}`).toEqual([]);
      }
    }
  });
});

describe('runtime', () => {
  afterEach(() => setLocale('en'));

  test('defaults to English and switches to Ukrainian', () => {
    expect(i18n.language).toBe(DEFAULT_LOCALE);
    expect(i18n.t('nav.home')).toBe('Home');
    setLocale('uk');
    expect(i18n.t('nav.home')).toBe('Головна');
    setLocale('xx');
    expect(i18n.language).toBe('en');
  });

  test('interpolates', () => {
    expect(i18n.t('auth.greeting', { name: 'Bob' })).toBe('Hi, Bob');
  });
});
