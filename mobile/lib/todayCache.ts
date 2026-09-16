import type { DailyDigest } from '../types';

/**
 * The digest the home screen shows, remembered for the life of the process.
 *
 * Opening a story unmounts 今日 AI 日报 and coming back mounts a fresh screen, so
 * without this every return re-asks the backend and paints 正在加载今日资讯... over a
 * list the reader was halfway through. Remembering the payload makes the return
 * a render instead of a request. The backend is still the source of truth: a
 * fresh app launch always re-reads it, and nothing here is written to disk.
 *
 * There is a single slot rather than one entry per date, unlike the history
 * cache: GET /api/v1/daily answers "today's digest, or the newest one when today
 * has not been generated yet", so the home screen only ever asks one question.
 */

/**
 * A remembered digest and the day it was last checked on.
 *
 * The day is the app-local date the check happened, which is deliberately *not*
 * always ``digest.date``: before the daily refresh has run, ``/daily`` answers
 * with the newest stored digest — yesterday's. Keying staleness on the digest's
 * own date would then re-read the backend on every return from a story all
 * morning, which is exactly the request this cache exists to avoid. Keying it on
 * the day already checked means "asked today, whatever it answered".
 */
export type TodayEntry = {
  digest: DailyDigest;
  day: string;
};

export type TodayCache = {
  get: () => TodayEntry | undefined;
  set: (digest: DailyDigest, day: string) => void;
  invalidate: () => void;
};

export function createTodayCache(): TodayCache {
  let entry: TodayEntry | undefined;

  return {
    get: () => entry,
    set: (digest, day) => {
      entry = { digest, day };
    },
    invalidate: () => {
      entry = undefined;
    },
  };
}

/**
 * The cache the home screen reads through.
 *
 * Module-level on purpose: it has to survive the screen unmounting while the
 * reader is in a story.
 */
export const todayCache = createTodayCache();

/** What the home screen can render right now, and what to do next. */
export type TodayRead = {
  /** The remembered digest, or null when there is nothing to show yet. */
  cached: DailyDigest | null;
  /**
   * A request already in flight, or null when none is needed.
   *
   * When a digest was remembered this promise never rejects: the re-read is
   * silent and a failure leaves the reader with what they already had. With
   * nothing remembered it rejects like any other request, because that is the
   * only path that has to report a failure.
   */
  refresh: Promise<DailyDigest> | null;
};

/**
 * Read today's digest: what is known now, plus the re-read to run behind it.
 *
 * The two answers come back together because the screen needs both before it can
 * decide what to paint, and resolving them separately is what made the reader
 * watch a spinner for content the app already had.
 */
export function readTodayDigest(
  cache: TodayCache,
  today: string,
  load: () => Promise<DailyDigest>,
): TodayRead {
  const entry = cache.get();

  // Nothing remembered: a fresh launch is the one read that has to be waited on.
  if (!entry) {
    return { cached: null, refresh: loadTodayDigest(cache, today, load) };
  }
  // Already asked today, so the answer stands — whether or not it was today's
  // digest. This is the case that makes coming back from a story free.
  if (entry.day === today) {
    return { cached: entry.digest, refresh: null };
  }
  // The app outlived midnight (or was started yesterday): the remembered digest
  // is still readable, and a newer one replaces it only if it actually arrives.
  return { cached: entry.digest, refresh: refreshTodayDigest(cache, today, load) };
}

/** Fetch, remember and return a digest. Only successes are remembered. */
async function loadTodayDigest(
  cache: TodayCache,
  day: string,
  load: () => Promise<DailyDigest>,
): Promise<DailyDigest> {
  const digest = await load();
  cache.set(digest, day);
  return digest;
}

/**
 * Fetch a newer digest without letting a failure take away what is on screen.
 *
 * This is not the same operation as a retry. A retry has to reach the network —
 * the remembered digest may be exactly the failure the reader is getting past —
 * and is allowed to report a failure. This one is a silent top-up, so an
 * unreachable backend resolves to the digest the reader is already reading. The
 * day is only advanced by ``loadTodayDigest`` on success, so a failed top-up is
 * tried again the next time the screen is opened.
 */
async function refreshTodayDigest(
  cache: TodayCache,
  day: string,
  load: () => Promise<DailyDigest>,
): Promise<DailyDigest> {
  const entry = cache.get();
  try {
    return await loadTodayDigest(cache, day, load);
  } catch (error) {
    if (entry) {
      return entry.digest;
    }
    throw error;
  }
}
