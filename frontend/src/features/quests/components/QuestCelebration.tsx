import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { CelebrationOverlay } from '../../../components/game/CelebrationOverlay';
import type { Completion } from '../api';

/**
 * Quest complete, then (when the player levelled up) a level-up overlay. `self` is true when
 * the viewer is the player being paid (auto-confirm), false for the GM who confirmed.
 */
export function QuestCelebration({
  completion,
  self,
  onDone,
}: {
  completion: Completion;
  self: boolean;
  onDone: () => void;
}) {
  const { t } = useTranslation('quests');
  const [step, setStep] = useState<'complete' | 'levelUp'>('complete');
  const leveledUp = completion.level > completion.level_before;

  if (step === 'levelUp') {
    return (
      <CelebrationOverlay
        open
        kind="levelUp"
        detail={t(self ? 'celebration.levelSelf' : 'celebration.levelCompanion', { level: completion.level })}
        onDone={onDone}
      />
    );
  }
  return (
    <CelebrationOverlay
      open
      kind="questComplete"
      detail={t(self ? 'celebration.rewardSelf' : 'celebration.rewardCompanion', {
        gold: completion.gold,
        xp: completion.xp,
      })}
      onDone={() => (leveledUp ? setStep('levelUp') : onDone())}
    />
  );
}
