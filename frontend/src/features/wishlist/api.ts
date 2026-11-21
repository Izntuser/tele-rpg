import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { components } from '../../lib/api/schema';
import { useAuth } from '../auth/context';

export type WishlistItem = components['schemas']['WishlistItemOut'];
export type WishlistItemCreate = components['schemas']['WishlistItemCreate'];
export type WishlistItemUpdate = components['schemas']['WishlistItemUpdate'];

export const WISHLIST_QUERY_KEY = ['wishlist', 'me'] as const;

export function useWishlist() {
  const { api } = useAuth();
  return useQuery({
    queryKey: WISHLIST_QUERY_KEY,
    queryFn: ({ signal }) => api.get<WishlistItem[]>('/wishlist', { signal }),
  });
}

/** Create, update and delete my wishlist items; each refreshes the list on success. */
export function useWishlistMutations() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  const onSuccess = () => queryClient.invalidateQueries({ queryKey: WISHLIST_QUERY_KEY });
  return {
    create: useMutation({
      mutationFn: (body: WishlistItemCreate) => api.post<WishlistItem>('/wishlist', body),
      onSuccess,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: WishlistItemUpdate }) =>
        api.patch<WishlistItem>(`/wishlist/${id}`, body),
      onSuccess,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api.delete<void>(`/wishlist/${id}`),
      onSuccess,
    }),
  };
}
