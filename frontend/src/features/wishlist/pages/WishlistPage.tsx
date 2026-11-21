import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { ConfirmSheet } from '../../../components/ui/ConfirmSheet';
import { EmptyState } from '../../../components/ui/EmptyState';
import { ApiError } from '../../../lib/api/client';
import { useWishlist, useWishlistMutations, type WishlistItem } from '../api';

export const MAX_TITLE = 200;
export const MAX_DESCRIPTION = 1000;

function errorKey(error: unknown): string {
  if (error instanceof ApiError && error.status === 409) {
    return typeof error.detail === 'string' && error.detail.includes('linked') ? 'wishlist.linked' : 'wishlist.limit';
  }
  return 'wishlist.error';
}

function Pill({ children }: { children: string }) {
  return (
    <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted">{children}</span>
  );
}

/** My reward wishlist: add, archive/restore and delete wishes. */
export function WishlistPage() {
  const { t } = useTranslation('profile');
  const items = useWishlist();
  const { create, update, remove } = useWishlistMutations();
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [toDelete, setToDelete] = useState<WishlistItem | null>(null);

  const trimmed = title.trim();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!trimmed || create.isPending) return;
    create.mutate(
      { title: trimmed, description: description.trim() || null },
      {
        onSuccess: () => {
          setTitle('');
          setDescription('');
        },
      },
    );
  };

  const failed = create.error ?? update.error ?? remove.error;

  return (
    <section data-testid="page-wishlist" className="flex flex-col gap-4 p-4">
      <header>
        <h1 className="text-2xl font-bold">{t('wishlist.title')}</h1>
        <p className="text-sm text-muted">{t('wishlist.subtitle')}</p>
      </header>

      <form onSubmit={submit} className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-3">
        <label htmlFor="wish-title" className="text-sm font-medium">
          {t('wishlist.label')}
        </label>
        <input
          id="wish-title"
          data-testid="wish-title-input"
          value={title}
          maxLength={MAX_TITLE}
          placeholder={t('wishlist.placeholder')}
          onChange={(e) => setTitle(e.target.value)}
          className="rounded-md border border-border bg-surface-2 px-3 py-2"
        />
        <label htmlFor="wish-description" className="text-sm text-muted">
          {t('wishlist.description')}
        </label>
        <textarea
          id="wish-description"
          value={description}
          maxLength={MAX_DESCRIPTION}
          rows={2}
          onChange={(e) => setDescription(e.target.value)}
          className="rounded-md border border-border bg-surface-2 px-3 py-2"
        />
        <button
          type="submit"
          data-testid="wish-add"
          disabled={!trimmed || create.isPending}
          className="rounded-md bg-accent px-4 py-2 font-semibold text-accent-fg disabled:opacity-50"
        >
          {t('wishlist.add')}
        </button>
      </form>

      {failed ? (
        <p role="alert" className="text-sm text-danger">
          {t(errorKey(failed))}
        </p>
      ) : null}

      {items.isPending ? null : items.isError ? (
        <p role="alert" className="text-sm">
          {t('wishlist.error')}
        </p>
      ) : items.data.length === 0 ? (
        <EmptyState title={t('wishlist.empty')} />
      ) : (
        <ul className="flex flex-col gap-2" data-testid="wish-list">
          {items.data.map((item) => {
            const archived = item.status === 'archived';
            return (
              <li
                key={item.id}
                data-testid="wish-item"
                className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className={archived ? 'break-words text-muted line-through' : 'break-words font-medium'}>
                    {item.title}
                  </p>
                  {archived ? <Pill>{t('wishlist.archived')}</Pill> : null}
                  {item.status === 'offered' ? <Pill>{t('wishlist.offered')}</Pill> : null}
                </div>
                {item.description ? (
                  <p className="whitespace-pre-line break-words text-sm text-muted">{item.description}</p>
                ) : null}
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={update.isPending}
                    onClick={() => update.mutate({ id: item.id, body: { status: archived ? 'open' : 'archived' } })}
                    className="rounded-md border border-border px-3 py-1 text-sm"
                  >
                    {archived ? t('wishlist.restore') : t('wishlist.archive')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setToDelete(item)}
                    className="rounded-md border border-border px-3 py-1 text-sm text-danger"
                  >
                    {t('wishlist.delete')}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <ConfirmSheet
        open={toDelete !== null}
        title={t('wishlist.deleteTitle')}
        description={toDelete?.title}
        confirmLabel={t('wishlist.delete')}
        destructive
        onCancel={() => setToDelete(null)}
        onConfirm={() => {
          if (toDelete) remove.mutate(toDelete.id);
          setToDelete(null);
        }}
      />
    </section>
  );
}
