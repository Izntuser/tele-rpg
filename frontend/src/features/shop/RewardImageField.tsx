import { useQueryClient } from '@tanstack/react-query';
import { ImageIcon } from 'lucide-react';
import { useTranslation } from 'react-i18next';

import { useUpload } from '../files/api';
import { AuthImage, PhotoButton, uploadErrorText } from '../files/components';
import { invalidateShop, type Reward } from './api';

/** A reward's picture, or a neutral placeholder; only my companion and I can load it. */
export function RewardImage({ reward, className }: { reward: Pick<Reward, 'title' | 'image_file_id'>; className?: string }) {
  const { t } = useTranslation('files');
  if (reward.image_file_id == null) {
    return (
      <span aria-hidden="true" className={`flex items-center justify-center bg-surface-2 text-muted ${className ?? ''}`}>
        <ImageIcon size={20} />
      </span>
    );
  }
  return (
    <AuthImage
      fileId={reward.image_file_id}
      alt={t('rewardImage.alt', { title: reward.title })}
      testId="reward-image"
      className={className}
    />
  );
}

/** Manage shop: upload or replace the picture of an existing reward (POST /rewards/{id}/image). */
export function RewardImageField({ reward }: { reward: Reward }) {
  const { t } = useTranslation('files');
  const queryClient = useQueryClient();
  const upload = useUpload<Reward>(`/rewards/${reward.id}/image`, () => void invalidateShop(queryClient));
  const current = upload.data ?? reward;
  const error = uploadErrorText(upload.error, t);

  return (
    <div data-testid="reward-image-field" className="flex flex-col gap-1">
      <span className="text-sm text-muted">{t('rewardImage.label')}</span>
      <PhotoButton
        testId="reward-image-input"
        label={current.image_file_id == null ? t('rewardImage.add') : t('rewardImage.change')}
        busy={upload.isPending}
        onPick={(file) => upload.mutate(file)}
      >
        <RewardImage reward={current} className="size-16 rounded-lg" />
      </PhotoButton>
      {upload.isSuccess ? (
        <p role="status" data-testid="reward-image-saved" className="text-sm text-muted">
          {t('rewardImage.saved')}
        </p>
      ) : null}
      {error ? (
        <p role="alert" data-testid="reward-image-error" className="text-sm text-danger">
          {error}
        </p>
      ) : null}
    </div>
  );
}
