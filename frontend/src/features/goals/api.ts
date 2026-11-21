import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import type { components } from '../../lib/api/schema';
import { useAuth } from '../auth/context';

export type Goal = components['schemas']['GoalOut'];
export type GoalCreate = components['schemas']['GoalCreate'];
export type GoalUpdate = components['schemas']['GoalUpdate'];

export const GOALS_QUERY_KEY = ['goals', 'me'] as const;

export function useGoals() {
  const { api } = useAuth();
  return useQuery({
    queryKey: GOALS_QUERY_KEY,
    queryFn: ({ signal }) => api.get<Goal[]>('/goals', { signal }),
  });
}

/** Create, update and delete my goals; each refreshes the list on success. */
export function useGoalMutations() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  const onSuccess = () => queryClient.invalidateQueries({ queryKey: GOALS_QUERY_KEY });
  return {
    create: useMutation({
      mutationFn: (body: GoalCreate) => api.post<Goal>('/goals', body),
      onSuccess,
    }),
    update: useMutation({
      mutationFn: ({ id, body }: { id: number; body: GoalUpdate }) => api.patch<Goal>(`/goals/${id}`, body),
      onSuccess,
    }),
    remove: useMutation({
      mutationFn: (id: number) => api.delete<void>(`/goals/${id}`),
      onSuccess,
    }),
  };
}
