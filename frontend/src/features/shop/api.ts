import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import type { components } from '../../lib/api/schema';
import { useAuth } from '../auth/context';
import { CHARACTER_QUERY_KEY } from '../character/api';
import { COMPANION_QUERY_KEY } from '../partnership/api';

type S = components['schemas'];
export type Reward = S['RewardOut'];
export type RewardCreate = S['RewardCreate'];
export type RewardUpdate = S['RewardUpdate'];
export type Voucher = S['PurchaseOut'];
export type PurchaseResult = S['PurchaseResult'];
export type ShopSide = 'companion' | 'mine';

export const REWARDS_KEY = ['rewards'] as const;
export const INVENTORY_KEY = ['inventory'] as const;

/** Everything a shop change can move: both shops, both inventories, my gold, wishlist links. */
export function invalidateShop(queryClient: QueryClient): Promise<unknown> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: REWARDS_KEY }),
    queryClient.invalidateQueries({ queryKey: INVENTORY_KEY }),
    queryClient.invalidateQueries({ queryKey: CHARACTER_QUERY_KEY }),
    queryClient.invalidateQueries({ queryKey: COMPANION_QUERY_KEY }),
  ]);
}

/** `companion`: what I can buy; `mine`: the rewards I provide (every status). */
export function useRewards(shop: ShopSide, enabled = true) {
  const { api } = useAuth();
  return useQuery({
    queryKey: [...REWARDS_KEY, shop],
    enabled,
    queryFn: ({ signal }) => api.get<Reward[]>(`/rewards?shop=${shop}&limit=100`, { signal }),
  });
}

/** Buy a reward: a fresh Idempotency-Key per attempt, a haptic, and a refresh of gold and lists. */
export function usePurchase() {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (rewardId: number) =>
      api.request<PurchaseResult>('POST', `/rewards/${rewardId}/purchase`, { idempotencyKey: true }),
    onSuccess: () => {
      telegram.haptic.notification('success');
      void invalidateShop(queryClient);
    },
    onError: () => telegram.haptic.notification('error'),
  });
}

export function useRewardMutations() {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  const onSuccess = () => {
    telegram.haptic.notification('success');
    return invalidateShop(queryClient);
  };
  const onError = () => telegram.haptic.notification('error');
  return {
    create: useMutation({
      mutationFn: (body: RewardCreate) =>
        api.request<Reward>('POST', '/rewards', { body, idempotencyKey: true }),
      onSuccess,
      onError,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: RewardUpdate }) =>
        api.request<Reward>('PATCH', `/rewards/${id}`, { body, idempotencyKey: true }),
      onSuccess,
      onError,
    }),
  };
}

export function isSoldOut(reward: Reward): boolean {
  return reward.status === 'sold_out' || reward.quantity_remaining === 0;
}

export type BuyBlock = 'soldOut' | 'cooldown' | 'gold' | null;

/** Why the viewer cannot buy this reward right now (the server re-checks everything). */
export function buyBlock(reward: Reward, gold: number | undefined, now = Date.now()): BuyBlock {
  if (isSoldOut(reward)) return 'soldOut';
  if (reward.cooldown_until && Date.parse(reward.cooldown_until) > now) return 'cooldown';
  if (gold !== undefined && gold < reward.price) return 'gold';
  return null;
}
