import { useState, type FormEvent } from 'react';
import { useTranslation } from 'react-i18next';

import { ATTRIBUTES, AttributeChip, type AttributeKey } from '../../../components/game/chips';
import { ConfirmSheet } from '../../../components/ui/ConfirmSheet';
import { EmptyState } from '../../../components/ui/EmptyState';
import { ApiError } from '../../../lib/api/client';
import { useGoalMutations, useGoals, type Goal } from '../api';

export const MAX_TITLE = 200;

function errorKey(error: unknown): string {
  return error instanceof ApiError && error.status === 409 ? 'goals.limit' : 'goals.error';
}

/** "I want to improve": create, archive/restore and delete my development goals. */
export function GoalsPage() {
  const { t } = useTranslation('profile');
  const goals = useGoals();
  const { create, update, remove } = useGoalMutations();
  const [title, setTitle] = useState('');
  const [attribute, setAttribute] = useState<AttributeKey | null>(null);
  const [toDelete, setToDelete] = useState<Goal | null>(null);

  const trimmed = title.trim();
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (!trimmed || create.isPending) return;
    create.mutate(
      { title: trimmed, attribute },
      {
        onSuccess: () => {
          setTitle('');
          setAttribute(null);
        },
      },
    );
  };

  const failed = create.error ?? update.error ?? remove.error;

  return (
    <section data-testid="page-goals" className="flex flex-col gap-4 p-4">
      <header>
        <h1 className="text-2xl font-bold">{t('goals.title')}</h1>
        <p className="text-sm text-muted">{t('goals.subtitle')}</p>
      </header>

      <form onSubmit={submit} className="flex flex-col gap-2 rounded-2xl border border-border bg-surface p-3">
        <label htmlFor="goal-title" className="text-sm font-medium">
          {t('goals.label')}
        </label>
        <input
          id="goal-title"
          data-testid="goal-title-input"
          value={title}
          maxLength={MAX_TITLE}
          placeholder={t('goals.placeholder')}
          onChange={(e) => setTitle(e.target.value)}
          className="rounded-md border border-border bg-surface-2 px-3 py-2"
        />
        <fieldset className="flex flex-col gap-1">
          <legend className="text-sm text-muted">{t('goals.attribute')}</legend>
          <div className="flex flex-wrap gap-1">
            {ATTRIBUTES.map((a) => (
              <AttributeChip
                key={a}
                attribute={a}
                selected={attribute === a}
                onSelect={() => setAttribute(attribute === a ? null : a)}
              />
            ))}
          </div>
        </fieldset>
        <button
          type="submit"
          data-testid="goal-add"
          disabled={!trimmed || create.isPending}
          className="rounded-md bg-accent px-4 py-2 font-semibold text-accent-fg disabled:opacity-50"
        >
          {t('goals.add')}
        </button>
      </form>

      {failed ? (
        <p role="alert" className="text-sm text-danger">
          {t(errorKey(failed))}
        </p>
      ) : null}

      {goals.isPending ? null : goals.isError ? (
        <p role="alert" className="text-sm">
          {t('goals.error')}
        </p>
      ) : goals.data.length === 0 ? (
        <EmptyState title={t('goals.empty')} />
      ) : (
        <ul className="flex flex-col gap-2" data-testid="goal-list">
          {goals.data.map((goal) => {
            const archived = goal.status === 'archived';
            return (
              <li
                key={goal.id}
                data-testid="goal-item"
                className="flex flex-col gap-2 rounded-xl border border-border bg-surface p-3"
              >
                <div className="flex items-start justify-between gap-2">
                  <p className={archived ? 'break-words text-muted line-through' : 'break-words font-medium'}>
                    {goal.title}
                  </p>
                  {archived ? (
                    <span className="shrink-0 rounded-full border border-border px-2 py-0.5 text-xs text-muted">
                      {t('goals.archived')}
                    </span>
                  ) : null}
                </div>
                {goal.attribute ? <AttributeChip attribute={goal.attribute} /> : null}
                <div className="flex gap-2">
                  <button
                    type="button"
                    disabled={update.isPending}
                    onClick={() =>
                      update.mutate({ id: goal.id, body: { status: archived ? 'active' : 'archived' } })
                    }
                    className="rounded-md border border-border px-3 py-1 text-sm"
                  >
                    {archived ? t('goals.restore') : t('goals.archive')}
                  </button>
                  <button
                    type="button"
                    onClick={() => setToDelete(goal)}
                    className="rounded-md border border-border px-3 py-1 text-sm text-danger"
                  >
                    {t('goals.delete')}
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <ConfirmSheet
        open={toDelete !== null}
        title={t('goals.deleteTitle')}
        description={toDelete?.title}
        confirmLabel={t('goals.delete')}
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
