import { Camera, ImageOff, Loader2 } from 'lucide-react';
import { useId, useRef, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';

import { Avatar } from '../../components/game/Avatar';
import { cn } from '../../components/ui/cn';
import { ApiError } from '../../lib/api/client';
import { ACCEPT_ATTR, UploadRejected, useFileUrl } from './api';

/** An image served by GET /files/{id} (fetched with the bearer token, shown as a blob URL). */
export function AuthImage({
  fileId,
  alt,
  className,
  testId,
}: {
  fileId: number;
  alt: string;
  className?: string;
  testId?: string;
}) {
  const { t } = useTranslation('files');
  const { url, error } = useFileUrl(fileId);
  if (error) {
    return (
      <span
        data-testid={testId ? `${testId}-unavailable` : undefined}
        className={cn('flex items-center justify-center gap-2 bg-surface-2 text-xs text-muted', className)}
      >
        <ImageOff aria-hidden="true" size={16} />
        {t('photo.unavailable')}
      </span>
    );
  }
  if (!url) {
    return (
      <span role="status" aria-label={t('photo.loading')} className={cn('block animate-pulse bg-surface-2', className)} />
    );
  }
  return <img src={url} alt={alt} data-testid={testId} data-file-id={fileId} className={cn('object-cover', className)} />;
}

/** `Avatar` that prefers the custom avatar file over the Telegram photo URL. */
export function FileAvatar({
  name,
  fileId,
  src,
  size,
  className,
}: {
  name: string;
  fileId?: number | null;
  src?: string | null;
  size?: 'sm' | 'md' | 'lg';
  className?: string;
}) {
  const { url } = useFileUrl(fileId);
  return <Avatar key={url ?? src ?? 'none'} name={name} src={url ?? src} size={size} className={className} />;
}

/** The message for a failed upload (client-side check or the server's 413/415/429). */
export function uploadErrorText(error: unknown, t: (key: string) => string): string | null {
  if (!error) return null;
  if (error instanceof UploadRejected) return t(`errors.${error.reason}`);
  if (error instanceof ApiError) {
    if (error.status === 413) return t('errors.size');
    if (error.status === 415) return t('errors.type');
    if (error.status === 429) return t('errors.rate');
  }
  return t('errors.generic');
}

/**
 * A button that opens the photo picker (camera or gallery). Validation, compression and the
 * upload itself belong to the caller's `onPick` (usually `useUpload().mutate`).
 */
export function PhotoButton({
  label,
  onPick,
  busy,
  disabled,
  testId,
  children,
}: {
  label: string;
  onPick: (file: File) => void;
  busy?: boolean;
  disabled?: boolean;
  testId: string;
  children?: ReactNode;
}) {
  const { t } = useTranslation('files');
  const id = useId();
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="flex items-center gap-3">
      {children}
      <label
        htmlFor={id}
        className={cn(
          'inline-flex cursor-pointer items-center gap-2 rounded-md border border-border px-3 py-2 text-sm font-medium',
          'focus-within:outline focus-within:outline-2',
          (busy || disabled) && 'pointer-events-none opacity-50',
        )}
      >
        {busy ? <Loader2 aria-hidden="true" size={16} className="animate-spin" /> : <Camera aria-hidden="true" size={16} />}
        {busy ? t('photo.uploading') : label}
        <input
          ref={input}
          id={id}
          type="file"
          accept={ACCEPT_ATTR}
          data-testid={testId}
          disabled={busy || disabled}
          className="sr-only"
          onChange={(event) => {
            const file = event.target.files?.[0];
            if (file) onPick(file);
            // Picking the same file again must fire change again.
            if (input.current) input.current.value = '';
          }}
        />
      </label>
    </div>
  );
}
