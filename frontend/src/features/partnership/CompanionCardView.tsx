import { useTranslation } from 'react-i18next';

import { FileAvatar } from '../files/components';
import type { CompanionCard } from './api';

/** Avatar, character name (or display name), nickname and level of another user. */
export function CompanionCardView({ card, testId }: { card: CompanionCard; testId?: string }) {
  const { t } = useTranslation();
  const name = card.character_name ?? card.display_name;
  return (
    <div data-testid={testId} className="flex items-center gap-4 rounded-2xl border border-border bg-surface p-4">
      <FileAvatar name={name} fileId={card.avatar_file_id} src={card.avatar_url} size="lg" />
      <div className="min-w-0">
        <p data-testid="companion-name" className="truncate text-xl font-bold">
          {name}
        </p>
        {card.nickname ? <p className="truncate text-sm text-muted">{card.nickname}</p> : null}
        <p className="text-sm font-semibold">{t('game.level', { level: card.level })}</p>
      </div>
    </div>
  );
}
