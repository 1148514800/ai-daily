import type { DigestSummary } from '../types';

/**
 * Moving between the digests that actually exist.
 *
 * The obvious implementation — ``date ± 1 day`` — is wrong here. A digest is
 * only written when a refresh succeeds, so the database legitimately has gaps
 * (a machine that was off, a collector outage, a manual deploy). Stepping by
 * one calendar day would open a date that was never generated and show an
 * empty page next to a full one.
 *
 * So navigation is over the stored list, not over the calendar: the previous
 * entry is simply the next older digest in the list, whatever its date is.
 */

/** Newest first, which is the order both the API and the history list use. */
export function sortByDateDesc(summaries: DigestSummary[]): DigestSummary[] {
  return [...summaries].sort((left, right) => right.date.localeCompare(left.date));
}

export type DigestNeighbours = {
  /** The digest one step newer, or null when this is the newest one. */
  next: string | null;
  /** The digest one step older, or null when this is the oldest one. */
  previous: string | null;
};

/**
 * The stored digests adjacent to ``date``.
 *
 * ``next`` is newer and ``previous`` is older, matching how a reader moves
 * through a timeline. Both are null when the date is not in the list, so a date
 * that does not exist cannot be navigated to as if it did.
 */
export function findNeighbours(dates: string[], date: string): DigestNeighbours {
  const ordered = [...new Set(dates)].sort((left, right) => right.localeCompare(left));
  const index = ordered.indexOf(date);
  if (index === -1) {
    return { next: null, previous: null };
  }
  return {
    next: index > 0 ? ordered[index - 1] : null,
    previous: index < ordered.length - 1 ? ordered[index + 1] : null,
  };
}

/**
 * How the Today tab should present the digest it was given.
 *
 * "Today" and "the latest digest" are not the same thing: the backend refreshes
 * at a fixed hour, so before that refresh has run there is no digest for today
 * at all. The API already answers with the newest stored digest in that case,
 * and this rule decides how to label it — ``isToday`` when it really is today,
 * ``fellBack`` when an older digest is standing in. The client never invents a
 * digest for a day the backend does not have.
 */
export type TodayView = {
  date: string;
  /** True only when the digest really is today's; the caller must not assume. */
  isToday: boolean;
  /** True when there is no digest for today and an older one is shown. */
  fellBack: boolean;
};

export function resolveTodayView(date: string, today: string): TodayView {
  const isToday = date === today;
  return { date, isToday, fellBack: !isToday };
}

/**
 * The heading for an open digest.
 *
 * Every digest is stored with the same generic title, so the heading has to be
 * built from the date. Today's digest keeps the plain "今日 AI 日报"; anything
 * else names its date, because calling a two-day-old digest "今日" while its
 * stories are timestamped yesterday would be a lie the reader can spot.
 */
export function digestHeading(date: string, isToday: boolean): string {
  if (isToday) {
    return '今日 AI 日报';
  }
  const [year, month, day] = date.split('-');
  if (!year || !month || !day) {
    return 'AI 日报';
  }
  return `${year}年${Number(month)}月${Number(day)}日 AI 日报`;
}
