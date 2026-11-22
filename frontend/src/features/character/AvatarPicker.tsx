import { useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

import type { AuthResponse } from '../../lib/api/client';
import { AUTH_QUERY_KEY } from '../auth/AuthProvider';
import { useUpload } from '../files/api';
import { FileAvatar, PhotoButton, uploadErrorText } from '../files/components';
import { CHARACTER_QUERY_KEY } from './api';

/**
 * My avatar with a "Change avatar" picker (POST /character/avatar). Works during onboarding
 * (no character yet): the uploaded file replaces the Telegram photo everywhere.
 */
export function AvatarPicker({
  name,
  fileId,
  fallbackUrl,
  onChanged,
}: {
  name: string;
  fileId: number | null | undefined;
  fallbackUrl?: string | null;
  /** The new avatar's file id, after the upload succeeded. */
  onChanged?: (fileId: number) => void;
}) {
  const { t } = useTranslation('files');
  const queryClient = useQueryClient();
  const upload = useUpload('/character/avatar', (file) => {
    onChanged?.(file.id);
    void queryClient.invalidateQueries({ queryKey: CHARACTER_QUERY_KEY });
    queryClient.setQueryData<AuthResponse>(AUTH_QUERY_KEY, (old) =>
      old ? { ...old, user: { ...old.user, avatar_file_id: file.id } } : old,
    );
  });
  const error = uploadErrorText(upload.error, t);
  const shown = upload.data?.id ?? fileId;

  return (
    <div data-testid="avatar-picker" className="flex flex-col gap-1">
      <PhotoButton
        testId="avatar-input"
        label={t('avatar.change')}
        busy={upload.isPending}
        onPick={(file) => upload.mutate(file)}
      >
        <FileAvatar name={name} fileId={shown} src={fallbackUrl} size="lg" />
      </PhotoButton>
      {error ? (
        <p role="alert" data-testid="avatar-error" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
