import { useMutation, useQueryClient } from '@tanstack/react-query';

import { useAuth } from '../auth/context';
import { invalidateQuests, type TemplateDetail } from './api';

export type Streak = NonNullable<TemplateDetail['streak']>;

/**
 * Pause or resume a recurring quest (creator only). Pausing stops new occurrences; resuming
 * restarts them and creates the current period's one. Refreshes lists and details either way.
 */
export function useTemplatePause(templateId: number) {
  const { api, telegram } = useAuth();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: 'pause' | 'resume') =>
      api.request<TemplateDetail>('POST', `/quest-templates/${templateId}/${action}`),
    onSuccess: () => {
      telegram.haptic.notification('success');
      void invalidateQuests(queryClient);
    },
    onError: () => telegram.haptic.notification('error'),
  });
}
