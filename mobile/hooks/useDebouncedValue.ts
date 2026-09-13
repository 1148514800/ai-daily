import { useEffect, useState } from 'react';

/**
 * The value, delayed until it has stopped changing for ``delayMs``.
 *
 * Used by search so typing does not fire a request per keystroke. A new value
 * cancels the pending one, so only the pause after the last keystroke triggers
 * the work.
 */
export function useDebouncedValue<T>(value: T, delayMs: number): T {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);

  return debounced;
}
