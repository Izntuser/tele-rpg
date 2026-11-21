import { useMutation, useQuery, useQueryClient, type QueryClient } from '@tanstack/react-query';

import { ApiError } from '../../lib/api/client';
import type { components } from '../../lib/api/schema';
import { useAuth } from '../auth/context';
import { CHARACTER_QUERY_KEY } from '../character/api';

export type PartnershipState = components['schemas']['PartnershipStateOut'];
export type InvitationCreated = components['schemas']['InvitationCreated'];
export type InvitationPreview = components['schemas']['InvitationPreview'];
export type AcceptOut = components['schemas']['AcceptOut'];
export type CompanionCard = components['schemas']['CompanionCard'];
export type CompanionProfile = components['schemas']['CompanionProfileOut'];

export const PARTNERSHIP_QUERY_KEY = ['partnership'] as const;
export const COMPANION_QUERY_KEY = ['companion'] as const;

/** Typed confirmations; the server compares against the same fixed words. */
export const LEAVE_CONFIRM_TEXT = 'LEAVE';

/** Everything that depends on who my companion is. */
export function invalidatePartnership(queryClient: QueryClient): Promise<unknown> {
  return Promise.all([
    queryClient.invalidateQueries({ queryKey: PARTNERSHIP_QUERY_KEY }),
    queryClient.invalidateQueries({ queryKey: COMPANION_QUERY_KEY }),
    queryClient.invalidateQueries({ queryKey: CHARACTER_QUERY_KEY }),
  ]);
}

export function usePartnership() {
  const { api } = useAuth();
  return useQuery({
    queryKey: PARTNERSHIP_QUERY_KEY,
    queryFn: ({ signal }) => api.get<PartnershipState>('/partnership', { signal }),
  });
}

export function useCompanion(enabled = true) {
  const { api } = useAuth();
  return useQuery({
    queryKey: COMPANION_QUERY_KEY,
    queryFn: ({ signal }) => api.get<CompanionProfile>('/partnership/companion', { signal }),
    enabled,
  });
}

/** Creates a fresh invite (the server revokes the previous one). The token is never cached. */
export function useCreateInvite() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<InvitationCreated>('/partnership/invitations'),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: PARTNERSHIP_QUERY_KEY }),
  });
}

/** Who sent this invitation. Sent as a POST body so the token never lands in a URL query. */
export function useInvitePreview(token: string) {
  const { api } = useAuth();
  return useQuery({
    queryKey: ['invite-preview', token],
    queryFn: () => api.post<InvitationPreview>('/partnership/invitations/preview', { token }),
    retry: false,
    staleTime: Infinity,
    gcTime: 0,
  });
}

export function useAcceptInvite() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (token: string) => api.post<AcceptOut>('/partnership/invitations/accept', { token }),
    onSuccess: () => invalidatePartnership(queryClient),
  });
}

export function useLeavePartnership() {
  const { api } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => api.post<void>('/partnership/leave', { confirm_text: LEAVE_CONFIRM_TEXT }),
    onSuccess: () => invalidatePartnership(queryClient),
  });
}

export type InviteProblem = 'invalid' | 'own' | 'paired' | 'onboarding' | 'generic';

/** Maps an invitation API error to a message key in the partnership namespace. */
export function inviteProblem(error: unknown): InviteProblem {
  if (!(error instanceof ApiError)) return 'generic';
  if (error.status === 404 || error.status === 410 || error.status === 422) return 'invalid';
  if (error.status === 409) {
    const detail = typeof error.detail === 'string' ? error.detail : '';
    if (detail.includes('own')) return 'own';
    if (detail.includes('onboarding')) return 'onboarding';
    return 'paired';
  }
  return 'generic';
}
