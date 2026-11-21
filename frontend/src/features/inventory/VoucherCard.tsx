import type { ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { GoldBadge } from '../../components/game/GoldBadge';
import { useFormatDate } from '../shop/components/ShopFrame';
import type { Voucher } from '../shop/api';

/** One voucher: the reward as bought, its status and dates; the caller supplies the actions. */
export function VoucherCard({ voucher, actions }: { voucher: Voucher; actions?: ReactNode }) {
  const { t } = useTranslation('shop');
  const format = useFormatDate();
  return (
    <li
      data-testid="voucher-card"
      data-status={voucher.status}
      className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3"
    >
      <div className="flex items-start justify-between gap-2">
        <p className="min-w-0 flex-1 break-words font-semibold">{voucher.reward.title}</p>
        <GoldBadge amount={voucher.price_paid} />
      </div>
      {voucher.reward.description ? (
        <p className="break-words text-sm text-muted">{voucher.reward.description}</p>
      ) : null}
      <p data-testid="voucher-status" className="text-xs font-medium text-gold">
        {t(`inventory.status.${voucher.status}`)}
        {voucher.frozen ? ` · ${t('inventory.frozen')}` : ''}
      </p>
      {voucher.status === 'scheduled' && voucher.scheduled_for ? (
        <p data-testid="voucher-schedule" className="text-sm">
          {t('inventory.scheduledFor', { date: format(voucher.scheduled_for) })}
          {voucher.schedule_note ? ` · ${voucher.schedule_note}` : ''}
        </p>
      ) : null}
      {voucher.status === 'fulfilled' && voucher.fulfilled_at ? (
        <p className="text-xs text-muted">{t('inventory.fulfilledAt', { date: format(voucher.fulfilled_at) })}</p>
      ) : null}
      {voucher.status === 'fulfilled' && voucher.dispute_until ? (
        <p className="text-xs text-muted">{t('inventory.disputeUntil', { date: format(voucher.dispute_until) })}</p>
      ) : null}
      {actions ? <div className="flex flex-wrap gap-2">{actions}</div> : null}
    </li>
  );
}

export function ActionButton({
  children,
  testId,
  onClick,
  disabled,
  tone = 'primary',
}: {
  children: ReactNode;
  testId: string;
  onClick: () => void;
  disabled?: boolean;
  tone?: 'primary' | 'plain' | 'danger' | 'gm';
}) {
  const classes = {
    primary: 'bg-accent text-accent-fg',
    gm: 'bg-gm text-bg',
    plain: 'border border-border',
    danger: 'border border-danger text-danger',
  } as const;
  return (
    <button
      type="button"
      data-testid={testId}
      disabled={disabled}
      onClick={onClick}
      className={`flex-1 rounded-md px-4 py-2 text-sm font-semibold disabled:opacity-50 ${classes[tone]}`}
    >
      {children}
    </button>
  );
}
