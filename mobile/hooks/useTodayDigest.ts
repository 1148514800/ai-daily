import { useCallback, useEffect, useState } from 'react';
import { readTodayDigest, todayCache } from '../lib/todayCache';
import { appLocalDate } from '../lib/relativeTime';
import { ApiError, fetchTodayDaily } from '../services/api';
import type { DailyDigest } from '../types';

type TodayState =
  | { status: 'loading'; data: null; error: null }
  | { status: 'error'; data: null; error: ApiError }
  | { status: 'success'; data: DailyDigest; error: null };

function asApiError(error: unknown): ApiError {
  return error instanceof ApiError ? error : new ApiError('内容加载失败', 0);
}

/**
 * Today's digest for the home screen, read through the in-memory cache.
 *
 * The screen unmounts whenever the reader opens a story, so a plain fetch would
 * repaint 正在加载今日资讯... on every return over a list they were halfway
 * through. Reading through ``todayCache`` means the way back is a render, not a
 * request, and the list comes back with the reader's place in it.
 *
 * Two situations still need the network, and they are kept apart on purpose:
 *
 * * nothing remembered yet (a fresh launch) — a normal load the screen waits on,
 *   and a failure is reported so the retry button has something to say;
 * * something remembered that was asked on an earlier day (the app outlived
 *   midnight) — a silent re-read behind the content already on screen, which is
 *   never allowed to blank the page.
 */
export function useTodayDigest() {
  const [state, setState] = useState<TodayState>(() => {
    const entry = todayCache.get();
    return entry
      ? { status: 'success', data: entry.digest, error: null }
      : { status: 'loading', data: null, error: null };
  });
  const [reloadCount, setReloadCount] = useState(0);

  useEffect(() => {
    let cancelled = false;
    // Resolved when the effect runs rather than on every render: a screen that
    // is left open past midnight only re-checks when it is mounted again, which
    // is exactly the moment the reader comes back to it.
    const read = readTodayDigest(todayCache, appLocalDate(new Date()), fetchTodayDaily);

    if (!read.cached && read.refresh) {
      // Nothing remembered: this is the one path the reader waits on, and the
      // only one where a failure is worth reporting.
      setState({ status: 'loading', data: null, error: null });
    }

    // A remembered digest either needs nothing (already rendered) or a newer
    // one, which replaces it only once it has actually arrived. Either way the
    // page is never taken away from the reader to wait.
    read.refresh
      ?.then((digest) => {
        if (cancelled) {
          return;
        }
        setState((previous) =>
          previous.status === 'success' && previous.data === digest
            ? previous
            : { status: 'success', data: digest, error: null },
        );
      })
      .catch((error: unknown) => {
        if (cancelled) {
          return;
        }
        // A silent re-read over a cached digest resolves instead of rejecting,
        // so this only fires when there was nothing to show. Keeping the cache
        // in that branch means a later change cannot turn a readable page into
        // an error page.
        setState((previous) =>
          previous.status === 'success'
            ? previous
            : { status: 'error', data: null, error: asApiError(error) },
        );
      });

    return () => {
      cancelled = true;
    };
  }, [reloadCount]);

  /**
   * Re-read today's digest, ignoring the cache.
   *
   * Used by the retry button: a remembered digest may be the very failure the
   * reader is trying to get past, so retrying has to actually go out to the
   * network rather than hand back what is already on screen.
   */
  const reload = useCallback(() => {
    todayCache.invalidate();
    setReloadCount((count) => count + 1);
  }, []);

  return { ...state, reload };
}
