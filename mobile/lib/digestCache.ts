import type { DailyDigest } from '../types';

/**
 * A tiny in-memory cache of digests the user has already opened.
 *
 * Reading history means stepping back and forth over the same few days, and
 * every step would otherwise re-fetch a payload the app just had. Caching for
 * the life of the process makes that instant without pretending to be a store:
 * the backend database stays the only source of truth, and a fresh app launch
 * always re-reads it.
 *
 * The screens that read through this cache are the historical ones, and a past
 * digest is immutable — its content is exactly what was stored for that date —
 * so nothing here can go stale behind the user's back. The retry path still
 * evicts explicitly, so a failed load is never remembered as a success.
 */

export type DigestCache = {
  get: (date: string) => DailyDigest | undefined;
  set: (date: string, digest: DailyDigest) => void;
  /** Drop one date, or everything when called with no argument. */
  invalidate: (date?: string) => void;
  /** How many digests are cached. Exposed for tests and diagnostics. */
  size: () => number;
};

export function createDigestCache(): DigestCache {
  const entries = new Map<string, DailyDigest>();

  return {
    get: (date) => entries.get(date),
    set: (date, digest) => {
      entries.set(date, digest);
    },
    invalidate: (date) => {
      if (date === undefined) {
        entries.clear();
        return;
      }
      entries.delete(date);
    },
    size: () => entries.size,
  };
}

/**
 * The cache the digest screens share.
 *
 * Module-level on purpose: it has to survive a screen unmounting while the user
 * steps to another date, which a hook-local store would not.
 */
export const digestCache = createDigestCache();

/**
 * Read a digest through the cache, falling back to the loader on a miss.
 *
 * ``load`` is only called when the date is absent, so navigating back over an
 * already-seen day issues no request at all.
 */
export async function loadDigest(
  cache: DigestCache,
  date: string,
  load: (date: string) => Promise<DailyDigest>,
): Promise<DailyDigest> {
  const cached = cache.get(date);
  if (cached) {
    return cached;
  }
  const digest = await load(date);
  cache.set(date, digest);
  return digest;
}
