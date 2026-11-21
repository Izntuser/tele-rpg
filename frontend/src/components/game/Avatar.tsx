import { useState } from 'react';

import { cn } from '../ui/cn';

const SIZES = { sm: 'size-8 text-sm', md: 'size-12 text-lg', lg: 'size-20 text-3xl' } as const;

/** Round avatar: the image when it loads, otherwise the first letter of the name. */
export function Avatar({
  name,
  src,
  size = 'md',
  className,
}: {
  name: string;
  src?: string | null;
  size?: keyof typeof SIZES;
  className?: string;
}) {
  const [failed, setFailed] = useState(false);
  const showImage = Boolean(src) && !failed;
  return (
    <span
      className={cn(
        'inline-flex shrink-0 items-center justify-center overflow-hidden rounded-full bg-surface-2 font-semibold',
        SIZES[size],
        className,
      )}
    >
      {showImage ? (
        <img src={src!} alt={name} onError={() => setFailed(true)} className="size-full object-cover" />
      ) : (
        <span role="img" aria-label={name}>
          {name.trim().charAt(0).toUpperCase() || '?'}
        </span>
      )}
    </span>
  );
}
