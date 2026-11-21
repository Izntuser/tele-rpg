import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { CelebrationOverlay } from '../../../components/game/CelebrationOverlay';
import { GoldBadge } from '../../../components/game/GoldBadge';
import { EmptyState } from '../../../components/ui/EmptyState';
import { ConfirmSheet } from '../../../components/ui/ConfirmSheet';
import { ApiError } from '../../../lib/api/client';
import { useCharacter } from '../../character/api';
import { buyBlock, usePurchase, useRewards, type PurchaseResult, type Reward } from '../api';
import { LoadError, ShopFrame, useFormatDate } from '../components/ShopFrame';

function RewardCard({ reward, gold, onBuy }: { reward: Reward; gold: number | undefined; onBuy: () => void }) {
  const { t } = useTranslation('shop');
  const format = useFormatDate();
  const block = buyBlock(reward, gold);
  const reason =
    block === 'gold'
      ? t('needGold', { missing: reward.price - (gold ?? 0) })
      : block === 'cooldown' && reward.cooldown_until
        ? t('cooldown', { date: format(reward.cooldown_until) })
        : block === 'soldOut'
          ? t('soldOut')
          : null;
  return (
    <li data-testid="reward-card" className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3">
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 flex-1 break-words font-semibold">{reward.title}</p>
        <GoldBadge amount={reward.price} />
      </div>
      {reward.description ? <p className="break-words text-sm text-muted">{reward.description}</p> : null}
      <p data-testid="reward-quantity" className="text-xs text-muted">
        {reward.quantity_remaining === null ? t('unlimited') : t('left', { count: reward.quantity_remaining })}
      </p>
      <button
        type="button"
        data-testid="reward-buy"
        disabled={block !== null}
        aria-describedby={reason ? `reason-${reward.id}` : undefined}
        onClick={onBuy}
        className="rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-fg disabled:opacity-50"
      >
        {t('buy')}
      </button>
      {reason ? (
        <p id={`reason-${reward.id}`} data-testid="reward-reason" className="text-xs text-muted">
          {reason}
        </p>
      ) : null}
    </li>
  );
}

/** My companion's shop: active rewards, my balance, and a confirmed purchase. */
export function ShopPage() {
  const { t } = useTranslation('shop');
  const rewards = useRewards('companion');
  const character = useCharacter();
  const purchase = usePurchase();
  const [pending, setPending] = useState<Reward | null>(null);
  const [bought, setBought] = useState<{ reward: Reward; result: PurchaseResult } | null>(null);
  const gold = character.data?.gold;

  const confirm = () => {
    const reward = pending;
    setPending(null);
    if (!reward) return;
    purchase.mutate(reward.id, { onSuccess: (result) => setBought({ reward, result }) });
  };

  const error = purchase.error;
  const errorText = error
    ? error instanceof ApiError && error.status === 409
      ? t('errors.conflict')
      : t('errors.generic')
    : null;

  return (
    <ShopFrame testId="page-shop" title={t('title')}>
      {rewards.isError ? (
          <LoadError onRetry={() => void rewards.refetch()} />
        ) : rewards.data && rewards.data.length === 0 ? (
          <EmptyState title={t('empty.title')} description={t('empty.hint')} />
        ) : (
          <>
            <ul data-testid="reward-list" className="flex flex-col gap-3">
              {(rewards.data ?? []).map((reward) => (
                <RewardCard
                  key={reward.id}
                  reward={reward}
                  gold={gold}
                  onBuy={() => {
                    purchase.reset();
                    setPending(reward);
                  }}
                />
              ))}
            </ul>
            {errorText ? (
              <p role="alert" data-testid="purchase-error" className="text-sm text-danger">
                {errorText}
              </p>
            ) : null}
          </>
        )}
      <ConfirmSheet
        open={pending !== null}
        title={t('buyTitle', { title: pending?.title ?? '' })}
        description={t('buyBody', { price: pending?.price ?? 0, gold: gold ?? 0 })}
        confirmLabel={t('buyConfirm')}
        onCancel={() => setPending(null)}
        onConfirm={confirm}
      />
      {bought ? (
        <CelebrationOverlay
          open
          kind="purchase"
          detail={t('bought', { title: bought.reward.title, balance: bought.result.balance })}
          onDone={() => setBought(null)}
        />
      ) : null}
    </ShopFrame>
  );
}
