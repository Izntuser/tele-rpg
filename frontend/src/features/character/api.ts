import { useQuery } from '@tanstack/react-query';

import type { components } from '../../lib/api/schema';
import { useAuth } from '../auth/context';

export type Character = components['schemas']['CharacterOut'];
export type CharacterAttribute = components['schemas']['AttributeOut'];

export const CHARACTER_QUERY_KEY = ['character'] as const;

/** GET /api/character: my character with derived level, XP progress, attributes and gold. */
export function useCharacter() {
  const { api } = useAuth();
  return useQuery({
    queryKey: CHARACTER_QUERY_KEY,
    queryFn: ({ signal }) => api.get<Character>('/character', { signal }),
  });
}
