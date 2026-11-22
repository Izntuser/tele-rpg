import type { TFunction } from 'i18next';

import type { NotificationItem } from './api';

/** Every placeholder the `types.*` strings use; a missing one renders empty. */
const FIELDS = ['title', 'gold', 'xp', 'price', 'active', 'offers', 'reviews'] as const;

/** Only plain scalars from a payload reach the translation (no nested objects). */
function values(payload: Record<string, unknown>): Record<string, string | number> {
  const out: Record<string, string | number> = Object.fromEntries(FIELDS.map((f) => [f, '']));
  for (const [key, value] of Object.entries(payload)) {
    if (typeof value === 'string' || typeof value === 'number') out[key] = value;
  }
  return out;
}

/** The inbox line for a notification; unknown types fall back to a generic line. */
export function notificationText(
  t: TFunction<'notifications'>,
  item: Pick<NotificationItem, 'type' | 'payload'>,
): string {
  return t(`types.${item.type}`, { ...values(item.payload ?? {}), defaultValue: t('generic') });
}
