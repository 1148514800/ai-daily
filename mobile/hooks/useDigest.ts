import { useCallback, useEffect, useState } from 'react';
import { digestCache, loadDigest } from '../lib/digestCache';
import { ApiError, fetchDailyByDate } from '../services/api';
import type { DailyDigest } from '../types';

type DigestState =
  | { status: 'loading'; data: null; error: null }
  | { status: 'error'; data: null; error: ApiError }
  | { status: 'success'; data: DailyDigest; error: null };

function initial(date: string): DigestState {
  const cached = digestCache.get(date);
  return cached
    ? { status: 'success', data: cached, error: null }
    : { status: 'loading', data: null, error: null };
}

/**
 * One digest by date, read through the in-memory cache.
 *
 * Stepping 09-13 → 09-12 → 09-13 re-uses what was already fetched, so the user
 * does not watch a spinner for a day they just read. The cache is only a
 * shortcut: a miss still goes to the backend, which stays the source of truth.
 */
export function useDigest(date: string) {
  const [state, setState] = useState<DigestState>(() => initial(date));
  // The reload counter belongs to one date. The screen is keyed by date so it
  // normally remounts, but resetting here as well means a retry on one day can
  // never leak into another day and force an unnecessary refetch.
  const [reloadToken, setReloadToken] = useState({ date, count: 0 });
  const attempt = reloadToken.date === date ? reloadToken.count : 0;

  useEffect(() => {
    // A date already in the cache renders straight from it with no request and
    // no loading frame, which is what makes stepping back and forth feel
    // instant. Only a miss goes to the backend.
    if (attempt === 0 && digestCache.get(date)) {
      const cached = digestCache.get(date) as DailyDigest;
      setState({ status: 'success', data: cached, error: null });
      return;
    }

    let cancelled = false;
    setState({ status: 'loading', data: null, error: null });
    loadDigest(digestCache, date, fetchDailyByDate)
      .then((data) => {
        if (!cancelled) {
          setState({ status: 'success', data, error: null });
        }
      })
      .catch((error: unknown) => {
        if (!cancelled) {
          const apiError =
            error instanceof ApiError ? error : new ApiError('内容加载失败', 0);
          setState({ status: 'error', data: null, error: apiError });
        }
      });
    return () => {
      cancelled = true;
    };
  }, [date, attempt]);

  /**
   * Re-read this digest from the backend, ignoring the cache.
   *
   * Used by the retry button: a cached entry may be the very failure the user is
   * trying to get past, so retrying has to actually go out to the network.
   */
  const reload = useCallback(() => {
    digestCache.invalidate(date);
    setReloadToken((token) => ({
      date,
      count: token.date === date ? token.count + 1 : 1,
    }));
  }, [date]);

  return { ...state, reload };
}
