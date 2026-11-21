import { useTranslation } from 'react-i18next';

import { Avatar } from '../../components/game/Avatar';
import { GoldBadge } from '../../components/game/GoldBadge';
import { XpBar } from '../../components/game/XpBar';
import type { Character } from './api';

/** Avatar, name, level with XP bar, and gold of the active wallet. */
export function CharacterHeader({ character }: { character: Character }) {
  return (
    <div
      data-testid="character-header"
      className="flex items-center gap-4 rounded-2xl border border-border bg-surface p-4"
    >
      <Avatar name={character.name} src={character.avatar_url} size="lg" />
      <div className="flex min-w-0 flex-1 flex-col gap-2">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p data-testid="character-name" className="truncate text-xl font-bold">
              {character.name}
            </p>
            {character.nickname ? (
              <p data-testid="character-nickname" className="truncate text-sm text-muted">
                {character.nickname}
              </p>
            ) : null}
          </div>
          <GoldBadge amount={character.gold} />
        </div>
        <XpBar
          level={character.level}
          current={character.xp_into_level}
          max={character.xp_for_next_level}
        />
      </div>
    </div>
  );
}

/** The six attributes with their levels. */
export function AttributeGrid({ character }: { character: Character }) {
  const { t } = useTranslation('profile');
  return (
    <section aria-labelledby="attributes-heading" className="flex flex-col gap-2">
      <h2 id="attributes-heading" className="text-sm font-semibold text-muted">
        {t('character.attributes')}
      </h2>
      <ul className="grid grid-cols-3 gap-2" data-testid="attribute-grid">
        {character.attributes.map((a) => (
          <li
            key={a.attribute}
            data-testid={`attribute-level-${a.attribute}`}
            className="flex flex-col items-center rounded-xl border border-border bg-surface px-2 py-2 text-center"
          >
            <span className="text-xs text-muted">{t(`common:game.attribute.${a.attribute}`)}</span>
            <span className="text-sm font-semibold">{t('character.attributeLevel', { level: a.level })}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}
