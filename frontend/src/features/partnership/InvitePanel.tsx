import { Check, Copy, Link2, Send } from 'lucide-react';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

import { useAuth } from '../auth/context';
import { useCreateInvite } from './api';

/** Telegram's share sheet for a URL (works inside and outside the Mini App). */
export function shareUrl(link: string, text: string): string {
  return `https://t.me/share/url?url=${encodeURIComponent(link)}&text=${encodeURIComponent(text)}`;
}

/**
 * "Invite your companion": creates a link on demand and offers copy and share. The link is held
 * only in this component's state (the server stores just a hash, so it cannot show it again).
 */
export function InvitePanel() {
  const { t } = useTranslation('partnership');
  const { telegram } = useAuth();
  const create = useCreateInvite();
  const [copied, setCopied] = useState(false);
  const link = create.data?.link ?? null;

  const copy = async () => {
    if (!link) return;
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      telegram.haptic.notification('success');
    } catch {
      setCopied(false);
    }
  };

  return (
    <div data-testid="invite-panel" className="flex flex-col gap-3 rounded-2xl border border-border bg-surface p-4">
      <div>
        <h2 className="font-semibold">{t('invite.title')}</h2>
        <p className="text-sm text-muted">{t('invite.hint')}</p>
      </div>
      {link ? (
        <>
          <label htmlFor="invite-link" className="text-sm font-medium">
            {t('invite.linkLabel')}
          </label>
          <input
            id="invite-link"
            data-testid="invite-link"
            readOnly
            value={link}
            onFocus={(e) => e.currentTarget.select()}
            className="rounded-md border border-border bg-surface-2 px-3 py-2 text-sm"
          />
          <p className="text-xs text-muted">{t('invite.expires')}</p>
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="invite-copy"
              onClick={() => void copy()}
              className="flex flex-1 items-center justify-center gap-2 rounded-md border border-border px-3 py-2 text-sm"
            >
              {copied ? <Check aria-hidden="true" size={16} /> : <Copy aria-hidden="true" size={16} />}
              {copied ? t('invite.copied') : t('invite.copy')}
            </button>
            <a
              href={shareUrl(link, t('invite.shareText'))}
              target="_blank"
              rel="noopener noreferrer"
              data-testid="invite-share"
              className="flex flex-1 items-center justify-center gap-2 rounded-md bg-accent px-3 py-2 text-sm font-semibold text-accent-fg"
            >
              <Send aria-hidden="true" size={16} />
              {t('invite.share')}
            </a>
          </div>
        </>
      ) : null}
      <button
        type="button"
        data-testid="invite-create"
        disabled={create.isPending}
        onClick={() => {
          setCopied(false);
          create.mutate();
        }}
        className={
          link
            ? 'text-sm text-muted underline disabled:opacity-50'
            : 'flex items-center justify-center gap-2 rounded-md bg-accent px-4 py-3 font-semibold text-accent-fg disabled:opacity-50'
        }
      >
        {link ? null : <Link2 aria-hidden="true" size={18} />}
        {create.isPending ? t('invite.creating') : link ? t('invite.regenerate') : t('invite.create')}
      </button>
      {create.isError ? (
        <p role="alert" className="text-sm text-danger">
          {t('invite.error')}
        </p>
      ) : null}
    </div>
  );
}
