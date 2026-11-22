const ID = /^[A-Za-z0-9_-]+$/;
const NUMERIC = /^[0-9]+$/;

/**
 * Maps a Telegram `startapp` parameter (or a notification's `deep_link`) to an in-app route;
 * anything unknown goes to `/`. Kinds (backend notifications/service.py):
 * `invite_<token>`, `q_<occurrence>`, `qt_<template>` (a recurring offer), `r_<purchase>`
 * (my voucher), `rq_<purchase>` (a request in the shop I run), `rw_<reward>` (the shop) and
 * `p_<partnership>` (my companion).
 */
export function deeplinkToRoute(startParam: string | null | undefined): string {
  if (!startParam) return '/';
  const match = /^(invite|qt|q|rq|rw|r|p)_(.+)$/.exec(startParam);
  if (!match || !ID.test(match[2]!)) return '/';
  const [, kind, id] = match;
  if (kind !== 'invite' && !NUMERIC.test(id!)) return '/';
  switch (kind) {
    case 'invite':
      return `/invite/${id}`;
    case 'q':
      return `/quests/${id}`;
    case 'qt':
      return '/quests';
    case 'rq':
      return '/shop/manage';
    case 'rw':
      return '/shop';
    case 'p':
      return '/companion';
    default:
      return `/shop/inventory?item=${id}`;
  }
}
