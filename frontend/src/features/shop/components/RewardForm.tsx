import { useId, useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { BottomSheet } from '../../../components/ui/BottomSheet';
import { ApiError } from '../../../lib/api/client';
import { useRewardMutations, type Reward, type RewardCreate } from '../api';

/** A reward being created (optionally from a wishlist item) or edited. */
export type RewardDraft =
  | { kind: 'create'; wishlistItem?: { id: number; title: string; description: string | null } }
  | { kind: 'edit'; reward: Reward };

const optionalInt = (value: string): number | null => (value.trim() === '' ? null : Number(value));

function Labeled({
  label,
  children,
}: {
  label: string;
  children: (id: string) => React.ReactNode;
}) {
  const id = useId();
  return (
    <div className="flex flex-col gap-1">
      <label htmlFor={id} className="text-sm text-muted">
        {label}
      </label>
      {children(id)}
    </div>
  );
}

const FIELD = 'rounded-md border border-border bg-surface-2 px-3 py-2';

function Form({ draft, onClose }: { draft: RewardDraft; onClose: () => void }) {
  const { t } = useTranslation('shop');
  const { create, update } = useRewardMutations();
  const reward = draft.kind === 'edit' ? draft.reward : null;
  const wish = draft.kind === 'create' ? draft.wishlistItem : undefined;
  const [title, setTitle] = useState(reward?.title ?? wish?.title ?? '');
  const [description, setDescription] = useState(reward?.description ?? wish?.description ?? '');
  const [price, setPrice] = useState(reward ? String(reward.price) : '');
  const [quantity, setQuantity] = useState(reward?.quantity_limit ? String(reward.quantity_limit) : '');
  const [cooldown, setCooldown] = useState(reward?.cooldown_days ? String(reward.cooldown_days) : '');
  const [hidden, setHidden] = useState(reward?.status === 'hidden');

  const priceValue = Number(price);
  const valid = title.trim().length > 0 && Number.isInteger(priceValue) && priceValue >= 1;
  const mutation = reward ? update : create;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!valid || mutation.isPending) return;
    const common = {
      description: description.trim() || null,
      price: priceValue,
      quantity_limit: optionalInt(quantity),
      cooldown_days: optionalInt(cooldown),
      status: hidden ? ('hidden' as const) : ('active' as const),
    };
    if (reward) {
      update.mutate({ id: reward.id, body: { ...common, title: title.trim() } }, { onSuccess: onClose });
    } else {
      const body: RewardCreate = wish
        ? { ...common, wishlist_item_id: wish.id, title: title.trim() }
        : { ...common, title: title.trim() };
      create.mutate(body, { onSuccess: onClose });
    }
  };

  const error = mutation.error;
  const errorText = error
    ? error instanceof ApiError && error.status === 409
      ? t('errors.conflict')
      : t('errors.generic')
    : null;

  return (
    <form onSubmit={submit} className="flex flex-col gap-3">
      <Labeled label={t('form.title')}>
        {(id) => (
          <input
            id={id}
            data-testid="reward-title"
            value={title}
            maxLength={200}
            onChange={(e) => setTitle(e.target.value)}
            className={FIELD}
          />
        )}
      </Labeled>
      <Labeled label={t('form.description')}>
        {(id) => (
          <textarea
            id={id}
            data-testid="reward-description"
            value={description}
            maxLength={1000}
            rows={2}
            onChange={(e) => setDescription(e.target.value)}
            className={FIELD}
          />
        )}
      </Labeled>
      <Labeled label={t('form.price')}>
        {(id) => (
          <input
            id={id}
            data-testid="reward-price"
            type="number"
            inputMode="numeric"
            min={1}
            max={100000}
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            className={FIELD}
          />
        )}
      </Labeled>
      <div className="grid grid-cols-2 gap-2">
        <Labeled label={t('form.quantity')}>
          {(id) => (
            <input
              id={id}
              data-testid="reward-quantity-limit"
              type="number"
              inputMode="numeric"
              min={1}
              max={1000}
              placeholder={t('form.unlimited')}
              value={quantity}
              onChange={(e) => setQuantity(e.target.value)}
              className={FIELD}
            />
          )}
        </Labeled>
        <Labeled label={t('form.cooldown')}>
          {(id) => (
            <input
              id={id}
              data-testid="reward-cooldown"
              type="number"
              inputMode="numeric"
              min={0}
              max={365}
              placeholder={t('form.none')}
              value={cooldown}
              onChange={(e) => setCooldown(e.target.value)}
              className={FIELD}
            />
          )}
        </Labeled>
      </div>
      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          data-testid="reward-hidden"
          checked={hidden}
          onChange={(e) => setHidden(e.target.checked)}
        />
        {t('form.hidden')}
      </label>
      {errorText ? (
        <p role="alert" data-testid="reward-form-error" className="text-sm text-danger">
          {errorText}
        </p>
      ) : null}
      <div className="flex gap-2">
        <button type="button" onClick={onClose} className="flex-1 rounded-md border border-border px-4 py-2 text-sm">
          {t('form.cancel')}
        </button>
        <button
          type="submit"
          data-testid="reward-save"
          disabled={!valid || mutation.isPending}
          className="flex-1 rounded-md bg-accent px-4 py-2 text-sm font-semibold text-accent-fg disabled:opacity-50"
        >
          {t('form.save')}
        </button>
      </div>
    </form>
  );
}

export function RewardSheet({ draft, onClose }: { draft: RewardDraft | null; onClose: () => void }) {
  const { t } = useTranslation('shop');
  return (
    <BottomSheet
      open={draft !== null}
      onClose={onClose}
      title={draft?.kind === 'edit' ? t('form.editTitle') : t('form.createTitle')}
      className="max-h-[90vh] overflow-y-auto"
    >
      {draft ? <Form key={draft.kind === 'edit' ? draft.reward.id : (draft.wishlistItem?.id ?? 'new')} draft={draft} onClose={onClose} /> : null}
    </BottomSheet>
  );
}
