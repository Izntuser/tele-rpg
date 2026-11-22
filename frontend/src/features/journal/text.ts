import type { TFunction } from 'i18next';

import type { JournalEvent } from '../stats/api';

/** Event types the journal has a sentence for; anything else reads as a generic event. */
export const KNOWN_EVENTS = new Set([
  'quest_offered',
  'quest_offer_updated',
  'quest_accepted',
  'quest_declined',
  'quest_cancelled',
  'quest_submitted',
  'quest_redo_requested',
  'quest_completed',
  'quest_paused',
  'quest_resumed',
  'quest_revision_proposed',
  'quest_revision_accepted',
  'quest_revision_declined',
  'level_up',
  'attribute_level_up',
  'reward_created',
  'reward_purchased',
  'reward_requested',
  'reward_scheduled',
  'reward_fulfilled',
  'reward_refunded',
  'reward_disputed',
  'achievement_unlocked',
  'partnership_accepted',
  'partnership_ended',
]);

/** The localized sentence for one journal event, from its denormalized payload. */
export function journalText(t: TFunction, event: JournalEvent): string {
  const p = event.payload as Record<string, unknown>;
  if (!KNOWN_EVENTS.has(event.type)) return t('stats:journal.event.unknown');
  const attribute = typeof p.attribute === 'string' ? t(`common:game.attribute.${p.attribute}`) : '';
  const achievement = typeof p.code === 'string' ? t(`stats:achievements.items.${p.code}.title`) : '';
  return t(`stats:journal.event.${event.type}`, {
    title: p.title ?? '',
    xp: p.xp ?? 0,
    gold: p.gold ?? 0,
    price: p.price ?? 0,
    level: p.level ?? '',
    attribute,
    achievement,
  });
}

/** The screen an event is about, when there is one. */
export function journalLink(event: JournalEvent): string | null {
  if (event.entity_type === 'quest_occurrence' && event.entity_id) return `/quests/${event.entity_id}`;
  return null;
}
