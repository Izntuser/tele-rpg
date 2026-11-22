import { useQuery } from '@tanstack/react-query';

import type { components } from '../../lib/api/schema';
import { ApiError } from '../../lib/api/client';
import { useAuth } from '../auth/context';

export type Character = components['schemas']['CharacterOut'];
export type CharacterAttribute = components['schemas']['AttributeOut'];

export const CHARACTER_QUERY_KEY = ['character'] as const;

/** GET /api/character: my character with derived level, XP progress, attributes and gold. */
export function useCharacter() {
  const { api } = useAuth();
  return useQuery({
    queryKey: CHARACTER_QUERY_KEY,
    queryFn: async ({ signal }) => {
      const character = await api.get<Character>('/character', { signal });
      // Never cache something the UI would read `name` off (Avatar, header) and crash on.
      if (typeof character?.name !== 'string') throw new ApiError(502, 'Malformed character');
      return character;
    },
  });
}
