import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { useAuth } from '../auth/context';
import { INVENTORY_KEY, invalidateShop, type Voucher } from '../shop/api';

export type Side = 'buyer' | 'provider';
export type VoucherAction =
  | { type: 'request' }
  | { type: 'dispute' }
  | { type: 'refund' }
  | { type: 'fulfill' }
  | { type: 'schedule'; scheduledFor: string; note?: string };

export function useInventory(side: Side, enabled = true) {
  const { api } = useAuth();
  return useQuery({
    queryKey: [...INVENTORY_KEY, side],
    enabled,
    queryFn: ({ signal }) => api.get<Voucher[]>(`/inventory?side=${side}&limit=100`, { signal }),
  });
}

/** Every voucher transition: Idempotency-Key, haptic, and a refresh of vouchers, shops and gold. */
export function useVoucherAction() {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, action }: { id: number; action: VoucherAction }) =>
      api.request<Voucher>('POST', `/inventory/${id}/${action.type}`, {
        body:
          action.type === 'schedule'
            ? { scheduled_for: action.scheduledFor, note: action.note?.trim() || null }
            : undefined,
        idempotencyKey: true,
      }),
    onSuccess: () => {
      telegram.haptic.notification('success');
      void invalidateShop(queryClient);
    },
    onError: () => telegram.haptic.notification('error'),
  });
}

export interface VoucherActions {
  request: boolean;
  dispute: boolean;
  refund: boolean;
  schedule: boolean;
  fulfill: boolean;
}

/** Which transitions the viewer may offer, mirroring the server's table; a frozen voucher only refunds. */
export function voucherActions(voucher: Voucher, side: Side, now = Date.now()): VoucherActions {
  const { status, frozen } = voucher;
  const buyer = side === 'buyer';
  const refundable = status === 'purchased' || (!buyer && (status === 'requested' || status === 'scheduled'));
  return {
    request: buyer && !frozen && status === 'purchased',
    dispute:
      buyer &&
      !frozen &&
      status === 'fulfilled' &&
      voucher.dispute_until !== null &&
      Date.parse(voucher.dispute_until) > now,
    refund: refundable && (!frozen || !buyer),
    schedule: !buyer && !frozen && (status === 'requested' || status === 'scheduled'),
    fulfill: !buyer && !frozen && status === 'scheduled',
  };
}
