import { X } from 'lucide-react';
import { useId, useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useUpload } from '../../files/api';
import { AuthImage, PhotoButton, uploadErrorText } from '../../files/components';

export interface SubmitValues {
  comment: string;
  attachmentId: number | null;
}

/**
 * The player's report: a comment and a photo (uploaded as soon as it is picked, compressed
 * client-side first). A photo_required quest cannot be sent without one.
 */
export function SubmitForm({
  photoRequired,
  busy,
  onSubmit,
}: {
  photoRequired: boolean;
  busy: boolean;
  onSubmit: (values: SubmitValues) => void;
}) {
  const { t } = useTranslation('quests');
  const { t: tf } = useTranslation('files');
  const id = useId();
  const [comment, setComment] = useState('');
  const [photoId, setPhotoId] = useState<number | null>(null);
  const upload = useUpload('/files', (file) => setPhotoId(file.id));
  const uploadError = uploadErrorText(upload.error, tf);
  const missingPhoto = photoRequired && photoId === null;

  return (
    <div data-testid="submit-form" className="flex flex-col gap-3">
      <div className="flex flex-col gap-1">
        <label htmlFor={id} className="text-sm text-muted">
          {t('actions.commentLabel')}
        </label>
        <textarea
          id={id}
          data-testid="submit-comment"
          value={comment}
          maxLength={1000}
          rows={2}
          onChange={(event) => setComment(event.target.value)}
          className="rounded-md border border-border bg-surface-2 px-3 py-2"
        />
      </div>

      <div className="flex flex-col gap-2">
        {photoId !== null ? (
          <div className="relative w-fit">
            <AuthImage
              fileId={photoId}
              alt={tf('photo.alt')}
              testId="submit-photo-preview"
              className="h-32 w-32 rounded-lg"
            />
            <button
              type="button"
              data-testid="submit-photo-remove"
              aria-label={tf('photo.remove')}
              onClick={() => setPhotoId(null)}
              className="absolute -right-2 -top-2 rounded-full border border-border bg-surface p-1"
            >
              <X aria-hidden="true" size={14} />
            </button>
          </div>
        ) : null}
        <PhotoButton
          testId="submit-photo"
          label={photoId === null ? tf('photo.choose') : tf('photo.replace')}
          busy={upload.isPending}
          disabled={busy}
          onPick={(file) => upload.mutate(file)}
        />
        {missingPhoto ? (
          <p data-testid="submit-photo-required" className="text-sm text-muted">
            {tf('photo.required')}
          </p>
        ) : null}
        {uploadError ? (
          <p role="alert" data-testid="submit-photo-error" className="text-sm text-danger">
            {uploadError}
          </p>
        ) : null}
      </div>

      <button
        type="button"
        data-testid="quest-submit"
        disabled={busy || upload.isPending || missingPhoto}
        onClick={() => onSubmit({ comment, attachmentId: photoId })}
        className="flex-1 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-fg disabled:opacity-50"
      >
        {t('actions.submit')}
      </button>
    </div>
  );
}
