import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import imageCompression from 'browser-image-compression';
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest';

import { setLocale } from '../../i18n';
import { ApiError } from '../../lib/api/client';
import { makeCharacter, makeUser, renderApp, type Routes } from '../../test/harness';
import type { OccurrenceDetail, Terms } from '../quests/api';
import type { Reward } from '../shop/api';
import { MAX_UPLOAD_BYTES, UploadRejected, compressImage } from './api';
import { uploadErrorText } from './components';

vi.mock('canvas-confetti', () => ({ default: vi.fn() }));
vi.mock('browser-image-compression', () => ({ default: vi.fn(async (file: File) => file) }));

const createObjectURL = vi.fn((blob: Blob) => `blob:mock/${blob.size}`);
const revokeObjectURL = vi.fn();

beforeEach(() => {
  Object.assign(URL, { createObjectURL, revokeObjectURL });
});

afterEach(() => {
  setLocale('en');
  vi.clearAllMocks();
});

const TERMS: Terms = {
  title: 'Gym session',
  description: null,
  attribute: 'physical',
  difficulty: 'normal',
  gold: 50,
  xp: 50,
  deadline: null,
  confirmation: 'manual',
  photo_required: true,
};

function questDetail(role: 'player' | 'gm', status: 'active' | 'in_review', attachmentId: number | null = null): OccurrenceDetail {
  const base = {
    id: 11,
    template_id: 5,
    creator_id: 2,
    assignee_id: 1,
    role,
    status,
    template_status: 'active' as const,
    recurrence: 'once' as const,
    scheduled_date: '2026-01-15',
    due_at: null,
    terms: TERMS,
    accepted_at: '2026-01-15T10:00:00Z',
    submitted_at: status === 'in_review' ? '2026-01-15T11:00:00Z' : null,
    completed_at: null,
    cancelled_by: null,
    decline_reason: null,
    has_pending_revision: false,
  };
  return {
    ...base,
    template: {
      id: 5,
      partnership_id: 9,
      creator_id: 2,
      assignee_id: 1,
      role,
      status: 'active',
      recurrence: 'once',
      terms: TERMS,
      version: 1,
      pending_revision: null,
      last_declined_revision: null,
      created_at: '2026-01-15T09:00:00Z',
    },
    submissions:
      status === 'in_review'
        ? [
            {
              id: 1,
              submitted_by: 1,
              comment: 'Leg day',
              attachment_id: attachmentId,
              created_at: '2026-01-15T11:00:00Z',
              review_status: 'pending',
              review_comment: null,
              reviewed_at: null,
            },
          ]
        : [],
  };
}

const COMPANION = { user_id: 2, display_name: 'Bohdan', avatar_url: null, avatar_file_id: null, character_name: 'Bold', nickname: null, level: 3 };
const PAIRED = { partnership: { id: 9, accepted_at: null, companion: COMPANION }, pending_invitation: null };

function questRoutes(extra: Routes): Routes {
  return {
    'GET /partnership': PAIRED,
    'GET /quests?limit=200': [],
    'GET /quest-templates?limit=200': [],
    'GET /character': makeCharacter(),
    ...extra,
  };
}

function photo(name = 'proof.jpg', type = 'image/jpeg', size = 2048): File {
  return new File([new Uint8Array(size)], name, { type });
}

function pick(testId: string, file: File) {
  const input = screen.getByTestId(testId) as HTMLInputElement;
  return act(async () => {
    fireEvent.change(input, { target: { files: [file] } });
  });
}

describe('compressImage / errors', () => {
  test('compresses accepted photos and rejects other types before any upload', async () => {
    await expect(compressImage(photo())).resolves.toBeInstanceOf(File);
    expect(imageCompression).toHaveBeenCalledWith(expect.any(File), expect.objectContaining({ maxWidthOrHeight: 2048 }));
    await expect(compressImage(photo('anim.gif', 'image/gif'))).rejects.toEqual(new UploadRejected('type'));
    await expect(compressImage(photo('doc.pdf', 'application/pdf'))).rejects.toEqual(new UploadRejected('type'));
    // No type reported (some pickers): the extension decides.
    await expect(compressImage(photo('IMG_1.HEIC', ''))).resolves.toBeDefined();
  });

  test('falls back to the original when the browser cannot decode it, but still caps at 10 MB', async () => {
    vi.mocked(imageCompression).mockRejectedValueOnce(new Error('cannot decode heic'));
    const heic = photo('a.heic', 'image/heic');
    await expect(compressImage(heic)).resolves.toBe(heic);
    vi.mocked(imageCompression).mockRejectedValueOnce(new Error('cannot decode heic'));
    const huge = photo('b.heic', 'image/heic', MAX_UPLOAD_BYTES + 1);
    await expect(compressImage(huge)).rejects.toEqual(new UploadRejected('size'));
  });

  test('maps server statuses to messages', () => {
    const t = (key: string) => key;
    expect(uploadErrorText(new ApiError(413, 'x'), t)).toBe('errors.size');
    expect(uploadErrorText(new ApiError(415, 'x'), t)).toBe('errors.type');
    expect(uploadErrorText(new ApiError(429, 'x'), t)).toBe('errors.rate');
    expect(uploadErrorText(new ApiError(500, 'x'), t)).toBe('errors.generic');
    expect(uploadErrorText(null, t)).toBeNull();
  });
});

describe('quest photo proof', () => {
  test('a photo_required quest cannot be submitted until a photo is uploaded; then attachment_id is sent', async () => {
    const uploaded = vi.fn(() => ({ id: 77, kind: 'quest_photo', mime: 'image/jpeg', size: 2048 }));
    const submitted = vi.fn(() => ({ ...questDetail('player', 'in_review', 77), completion: null }));
    const { request } = renderApp('/quests/11', {
      routes: questRoutes({
        'GET /quests/11': questDetail('player', 'active'),
        'POST /files': uploaded,
        'GET /files/77': new Blob(['jpeg-bytes'], { type: 'image/jpeg' }),
        'POST /quests/11/submit': submitted,
      }),
    });
    const submit = await screen.findByTestId('quest-submit');
    expect(submit).toBeDisabled();
    expect(screen.getByTestId('submit-photo-required')).toHaveTextContent('This quest needs a photo.');

    await pick('submit-photo', photo());
    await waitFor(() => expect(uploaded).toHaveBeenCalled());
    const body = (uploaded.mock.calls[0] as unknown[])[0];
    expect(body).toBeInstanceOf(FormData);
    expect((body as FormData).get('file')).toBeInstanceOf(Blob);

    const preview = await screen.findByTestId('submit-photo-preview');
    expect(preview).toHaveAttribute('src', 'blob:mock/10');
    const fileCall = request.mock.calls.find((c) => c[1] === '/files/77');
    expect(fileCall?.[2]).toMatchObject({ responseType: 'blob' });
    expect(screen.queryByTestId('submit-photo-required')).not.toBeInTheDocument();
    expect(screen.getByTestId('quest-submit')).toBeEnabled();

    fireEvent.click(screen.getByTestId('submit-photo-remove'));
    expect(screen.getByTestId('quest-submit')).toBeDisabled();
    await pick('submit-photo', photo());
    await screen.findByTestId('submit-photo-preview');

    fireEvent.change(screen.getByTestId('submit-comment'), { target: { value: 'Done' } });
    await act(async () => fireEvent.click(screen.getByTestId('quest-submit')));
    await waitFor(() =>
      expect(submitted).toHaveBeenCalledWith({ comment: 'Done', attachment_id: 77 }, '/quests/11/submit'),
    );
  });

  test('a rejected upload shows the reason and keeps submit disabled; a gif never leaves the client', async () => {
    const { calls } = renderApp('/quests/11', {
      routes: questRoutes({
        'GET /quests/11': questDetail('player', 'active'),
        'POST /files': () => {
          throw new ApiError(415, 'Unsupported file type');
        },
      }),
    });
    await screen.findByTestId('quest-submit');
    await pick('submit-photo', photo('weird.png', 'image/png'));
    expect(await screen.findByTestId('submit-photo-error')).toHaveTextContent('Only JPEG, PNG, WebP or HEIC photos.');
    expect(screen.getByTestId('quest-submit')).toBeDisabled();

    await pick('submit-photo', photo('anim.gif', 'image/gif'));
    expect(calls.filter((c) => c.path === '/files')).toHaveLength(1); // the gif never left the client
  });

  test('the GM sees the submitted photo on the quest detail', async () => {
    renderApp('/quests/11', {
      routes: questRoutes({
        'GET /quests/11': questDetail('gm', 'in_review', 55),
        'GET /files/55': new Blob(['abc'], { type: 'image/jpeg' }),
      }),
    });
    const image = await screen.findByTestId('submission-photo');
    expect(image).toHaveAttribute('src', 'blob:mock/3');
    expect(image).toHaveAttribute('alt', 'Photo proof');
  });

  test('a photo the viewer may no longer see shows a placeholder', async () => {
    renderApp('/quests/11', {
      routes: questRoutes({
        'GET /quests/11': questDetail('gm', 'in_review', 56),
        'GET /files/56': () => {
          throw new ApiError(404, 'File not found');
        },
      }),
    });
    expect(await screen.findByTestId('submission-photo-unavailable')).toHaveTextContent('Photo unavailable');
  });
});

describe('avatar', () => {
  test('settings uploads a new avatar to /character/avatar and shows it', async () => {
    const uploaded = vi.fn(() => ({ id: 31, kind: 'avatar', mime: 'image/jpeg', size: 10 }));
    const { calls } = renderApp('/settings', {
      routes: {
        'GET /partnership': PAIRED,
        'POST /character/avatar': uploaded,
        'GET /files/31': new Blob(['a'.repeat(31)], { type: 'image/jpeg' }),
      },
    });
    const picker = await screen.findByTestId('avatar-picker');
    await pick('avatar-input', photo('me.jpg'));
    await waitFor(() => expect(uploaded).toHaveBeenCalled());
    await waitFor(() => expect(within(picker).getByRole('img')).toHaveAttribute('src', 'blob:mock/31'));
    expect(calls.some((c) => c.path === '/files/31')).toBe(true);
  });

  test('onboarding offers the avatar upload before the character exists', async () => {
    const uploaded = vi.fn(() => ({ id: 32, kind: 'avatar', mime: 'image/jpeg', size: 10 }));
    renderApp('/onboarding', {
      user: makeUser({ onboarded_at: null }),
      routes: { 'POST /character/avatar': uploaded, 'GET /files/32': new Blob(['x'], { type: 'image/jpeg' }) },
    });
    await screen.findByTestId('avatar-picker');
    await pick('avatar-input', photo('me.png', 'image/png'));
    await waitFor(() => expect(uploaded).toHaveBeenCalled());
  });

  test('the character header shows the custom avatar instead of the Telegram photo', async () => {
    renderApp('/', {
      routes: {
        'GET /character': makeCharacter({ avatar_file_id: 40, avatar_url: 'https://t.me/i/userpic/x.jpg' }),
        'GET /files/40': new Blob(['1234'], { type: 'image/jpeg' }),
        'GET /partnership': PAIRED,
        'GET /quests?limit=200': [],
        'GET /quest-templates?limit=200': [],
      },
    });
    const header = await screen.findByTestId('character-header');
    await waitFor(() => expect(within(header).getByRole('img')).toHaveAttribute('src', 'blob:mock/4'));
  });
});

describe('reward image', () => {
  const REWARD: Reward = {
    id: 3,
    creator_id: 1,
    title: 'Massage',
    description: null,
    price: 40,
    image_file_id: null,
    quantity_limit: null,
    quantity_remaining: null,
    cooldown_days: null,
    status: 'active',
    source_wishlist_item_id: null,
    mine: true,
    cooldown_until: null,
    created_at: '2026-01-15T10:00:00Z',
    updated_at: '2026-01-15T10:00:00Z',
  };

  test('the creator uploads a picture from the edit sheet', async () => {
    const uploaded = vi.fn(() => ({ ...REWARD, image_file_id: 90 }));
    renderApp('/shop/manage', {
      routes: {
        'GET /partnership': PAIRED,
        'GET /character': makeCharacter(),
        'GET /rewards?shop=mine&limit=100': [REWARD],
        'GET /inventory?side=provider&limit=100': [],
        'GET /partnership/companion': { wishlist: [] },
        'POST /rewards/3/image': uploaded,
        'GET /files/90': new Blob(['img'], { type: 'image/jpeg' }),
      },
    });
    await act(async () => fireEvent.click(await screen.findByTestId('reward-edit')));
    expect(screen.getByTestId('reward-image-field')).toHaveTextContent('Add picture');
    await pick('reward-image-input', photo('massage.webp', 'image/webp'));
    await waitFor(() => expect(uploaded).toHaveBeenCalled());
    expect(await screen.findByTestId('reward-image-saved')).toBeInTheDocument();
    expect(await screen.findByTestId('reward-image')).toHaveAttribute('alt', 'Picture of Massage');
  });

  test('the shop card shows the picture of a companion reward', async () => {
    renderApp('/shop', {
      routes: {
        'GET /partnership': PAIRED,
        'GET /character': makeCharacter(),
        'GET /rewards?shop=companion&limit=100': [{ ...REWARD, creator_id: 2, mine: false, image_file_id: 91 }],
        'GET /files/91': new Blob(['img!'], { type: 'image/jpeg' }),
      },
    });
    const card = await screen.findByTestId('reward-card');
    await waitFor(() => expect(within(card).getByTestId('reward-image')).toHaveAttribute('src', 'blob:mock/4'));
  });
});
