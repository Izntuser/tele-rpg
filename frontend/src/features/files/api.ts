import { useMutation, useQuery } from '@tanstack/react-query';
import imageCompression from 'browser-image-compression';
import { useEffect, useState } from 'react';

import type { ApiClient } from '../../lib/api/client';
import type { components } from '../../lib/api/schema';
import { useAuth } from '../auth/context';

export type FileOut = components['schemas']['FileOut'];

/** The server's limits (POST /files): checked again there by content, these only save a trip. */
export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_TYPES = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'image/heif'];
export const ACCEPT_ATTR = ACCEPTED_TYPES.join(',');

export const FILE_KEY = ['file'] as const;

export class UploadRejected extends Error {
  constructor(readonly reason: 'type' | 'size') {
    super(reason);
    this.name = 'UploadRejected';
  }
}

/** Some pickers (and HEIC on Android) report no type: fall back to the extension. */
function looksAccepted(file: File): boolean {
  if (file.type) return ACCEPTED_TYPES.includes(file.type.toLowerCase());
  return /\.(jpe?g|png|webp|heic|heif)$/i.test(file.name);
}

/**
 * Shrink a photo before upload (max 2048 px, ~1.5 MB). The browser cannot decode every format
 * (HEIC outside Safari): then the original is sent and the server re-encodes it.
 */
export async function compressImage(file: File): Promise<Blob> {
  if (!looksAccepted(file)) throw new UploadRejected('type');
  let out: Blob = file;
  try {
    out = await imageCompression(file, { maxSizeMB: 1.5, maxWidthOrHeight: 2048, useWebWorker: false });
  } catch {
    out = file;
  }
  if (out.size > MAX_UPLOAD_BYTES) throw new UploadRejected('size');
  return out;
}

/** Multipart POST of one image as the `file` field; `path` is /files, /character/avatar, ... */
export async function uploadImage<T = FileOut>(api: ApiClient, path: string, file: File): Promise<T> {
  const blob = await compressImage(file);
  const form = new FormData();
  form.append('file', blob, file.name || 'photo');
  return api.post<T>(path, form);
}

export function useUpload<T = FileOut>(path: string, onUploaded?: (result: T) => void) {
  const { api, telegram } = useAuth();
  return useMutation({
    mutationFn: (file: File) => uploadImage<T>(api, path, file),
    onSuccess: (result) => {
      telegram.haptic.notification('success');
      onUploaded?.(result);
    },
    onError: () => telegram.haptic.notification('error'),
  });
}

/**
 * The bytes of a file I may see (GET /files/{id} needs the bearer token, so a plain `<img src>`
 * cannot load it), as a blob URL that is revoked when no longer used.
 */
export function useFileUrl(fileId: number | null | undefined): { url: string | null; error: boolean } {
  const { api } = useAuth();
  const query = useQuery({
    queryKey: [...FILE_KEY, fileId],
    enabled: typeof fileId === 'number',
    staleTime: Infinity,
    retry: false,
    queryFn: ({ signal }) => api.get<Blob>(`/files/${fileId}`, { signal, responseType: 'blob' }),
  });
  const [url, setUrl] = useState<string | null>(null);
  const blob = typeof fileId === 'number' ? query.data : undefined;
  useEffect(() => {
    if (!blob) {
      setUrl(null);
      return;
    }
    const next = URL.createObjectURL(blob);
    setUrl(next);
    return () => URL.revokeObjectURL(next);
  }, [blob]);
  return { url, error: query.isError };
}
