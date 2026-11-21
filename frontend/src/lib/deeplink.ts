const ID = /^[A-Za-z0-9_-]+$/;

/** Maps a Telegram `startapp` parameter to an in-app route; anything unknown goes to `/`. */
export function deeplinkToRoute(startParam: string | null | undefined): string {
  if (!startParam) return '/';
  const match = /^(invite|q|r)_(.+)$/.exec(startParam);
  if (!match || !ID.test(match[2]!)) return '/';
  const [, kind, id] = match;
  switch (kind) {
    case 'invite':
      return `/invite/${id}`;
    case 'q':
      return `/quests/${id}`;
    default:
      return `/shop/inventory?item=${id}`;
  }
}
