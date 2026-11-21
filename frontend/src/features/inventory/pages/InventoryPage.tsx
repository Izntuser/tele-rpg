import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { ConfirmSheet } from '../../../components/ui/ConfirmSheet';
import { EmptyState } from '../../../components/ui/EmptyState';
import { ApiError } from '../../../lib/api/client';
import type { Voucher } from '../../shop/api';
import { LoadError, ShopFrame } from '../../shop/components/ShopFrame';
import { useInventory, useVoucherAction, voucherActions } from '../api';
import { ActionButton, VoucherCard } from '../VoucherCard';

const GROUPS = ['purchased', 'requested', 'scheduled', 'fulfilled', 'refunded'] as const;

type Pending = { voucher: Voucher; kind: 'dispute' | 'refund' } | null;

/** My vouchers grouped by status; request, dispute (within 48h) and refund only when allowed. */
export function InventoryPage() {
  const { t } = useTranslation('shop');
  const vouchers = useInventory('buyer');
  const act = useVoucherAction();
  const [pending, setPending] = useState<Pending>(null);

  const error = act.error;
  const errorText = error
    ? error instanceof ApiError && error.status === 409
      ? t('errors.conflict')
      : t('errors.generic')
    : null;

  const grouped = GROUPS.map((status) => ({
    status,
    items: (vouchers.data ?? []).filter((v) => v.status === status),
  })).filter((g) => g.items.length > 0);

  return (
    <ShopFrame testId="page-inventory" title={t('inventory.title')}>
      {vouchers.isError ? (
        <LoadError onRetry={() => void vouchers.refetch()} />
      ) : vouchers.data && grouped.length === 0 ? (
        <EmptyState title={t('inventory.empty.title')} description={t('inventory.empty.hint')} />
      ) : (
        grouped.map(({ status, items }) => (
          <section key={status} data-testid={`voucher-group-${status}`} className="flex flex-col gap-2">
            <h2 className="text-sm font-semibold text-muted">
              {t(`inventory.status.${status}`)} ({items.length})
            </h2>
            <ul className="flex flex-col gap-3">
              {items.map((voucher) => {
                const allowed = voucherActions(voucher, 'buyer');
                return (
                  <VoucherCard
                    key={voucher.id}
                    voucher={voucher}
                    actions={
                      <>
                        {allowed.request ? (
                          <ActionButton
                            testId="voucher-request"
                            disabled={act.isPending}
                            onClick={() => act.mutate({ id: voucher.id, action: { type: 'request' } })}
                          >
                            {t('inventory.request')}
                          </ActionButton>
                        ) : null}
                        {allowed.dispute ? (
                          <ActionButton
                            testId="voucher-dispute"
                            tone="plain"
                            disabled={act.isPending}
                            onClick={() => setPending({ voucher, kind: 'dispute' })}
                          >
                            {t('inventory.dispute')}
                          </ActionButton>
                        ) : null}
                        {allowed.refund ? (
                          <ActionButton
                            testId="voucher-refund"
                            tone="danger"
                            disabled={act.isPending}
                            onClick={() => setPending({ voucher, kind: 'refund' })}
                          >
                            {t('inventory.refund')}
                          </ActionButton>
                        ) : null}
                      </>
                    }
                  />
                );
              })}
            </ul>
          </section>
        ))
      )}
      {errorText ? (
        <p role="alert" data-testid="inventory-error" className="text-sm text-danger">
          {errorText}
        </p>
      ) : null}
      <ConfirmSheet
        open={pending !== null}
        destructive
        title={t(`inventory.${pending?.kind ?? 'refund'}Title`)}
        description={t(`inventory.${pending?.kind ?? 'refund'}Body`, { title: pending?.voucher.reward.title ?? '' })}
        confirmLabel={t(`inventory.${pending?.kind ?? 'refund'}Confirm`)}
        onCancel={() => setPending(null)}
        onConfirm={() => {
          const current = pending;
          setPending(null);
          if (current) act.mutate({ id: current.voucher.id, action: { type: current.kind } });
        }}
      />
    </ShopFrame>
  );
}
