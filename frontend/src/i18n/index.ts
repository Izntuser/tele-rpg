import i18next from 'i18next';
import { initReactI18next } from 'react-i18next';

export const LOCALES = ['en', 'uk'] as const;
export type Locale = (typeof LOCALES)[number];
export const DEFAULT_LOCALE: Locale = 'en';

type Catalog = Record<string, unknown>;
type Resources = Record<string, Record<string, Catalog>>;

/**
 * Every `./<locale>/<namespace>.json` is one namespace, so a later stage adds its own file
 * (e.g. `en/quests.json`) and never edits a shared catalog.
 */
const files = import.meta.glob<Catalog>('./*/*.json', { eager: true, import: 'default' });

export function buildResources(modules: Record<string, Catalog> = files): Resources {
  const resources: Resources = {};
  for (const [path, catalog] of Object.entries(modules)) {
    const match = /\.\/([^/]+)\/([^/]+)\.json$/.exec(path);
    if (!match) continue;
    const [, locale, namespace] = match;
    (resources[locale!] ??= {})[namespace!] = catalog;
  }
  return resources;
}

const resources = buildResources();

void i18next.use(initReactI18next).init({
  resources,
  lng: DEFAULT_LOCALE,
  fallbackLng: DEFAULT_LOCALE,
  supportedLngs: [...LOCALES],
  ns: Object.keys(resources[DEFAULT_LOCALE] ?? {}),
  defaultNS: 'common',
  interpolation: { escapeValue: false },
  initAsync: false,
});

export function isLocale(value: string | null | undefined): value is Locale {
  return (LOCALES as readonly string[]).includes(value ?? '');
}

export function setLocale(locale: string | null | undefined): void {
  const next = isLocale(locale) ? locale : DEFAULT_LOCALE;
  if (i18next.language !== next) void i18next.changeLanguage(next);
}

export const i18n = i18next;
export default i18next;
