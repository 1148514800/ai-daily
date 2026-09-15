/**
 * The detail screen's reading view, as data.
 *
 * Phase 10.12 turned the detail page into a Chinese interpretation page: there is
 * no original-text viewer any more, so the only question left is which parts of
 * an article are worth a section. That decision is pure and lives here so it can
 * be tested without rendering anything.
 */
import type { NewsItem } from '../types';
// Explicit .ts extensions: this module is imported by ``node --test`` as well as
// by Metro, and the Node ESM resolver needs the extension to follow the chain.
import { formatShortDateWithWeekday } from './format.ts';
import { appLocalDate, formatClock } from './relativeTime.ts';

/**
 * The bullets to show under 核心信息.
 *
 * An article summarised before the field existed has no points at all, and the
 * backend sends `key_points: []` for those. The section is simply omitted then:
 * an empty heading would promise information that is not there.
 */
export function displayKeyPoints(item: Pick<NewsItem, 'key_points'>): string[] {
  const points = item.key_points;
  if (!Array.isArray(points)) {
    return [];
  }
  // Trimmed and de-duplicated: a stray blank line would render as an empty row.
  const seen = new Set<string>();
  const cleaned: string[] = [];
  for (const point of points) {
    const text = String(point ?? '').trim();
    if (!text || seen.has(text)) {
      continue;
    }
    seen.add(text);
    cleaned.push(text);
  }
  return cleaned;
}

/** What 发生了什么？ shows when the backend has no summary for an article. */
export const SUMMARY_FALLBACK = '这条内容暂时没有摘要。';

/**
 * The publication line: ``9月15日 周一 08:02``.
 *
 * Always absolute. The detail page is reached from today's digest, from a past
 * digest and from the favourites list, so a relative label ("2小时前") would be
 * wrong in two of those three places. Both halves are read in APP_TIMEZONE: the
 * stored instant is UTC, and a date taken from the raw ISO string would disagree
 * with the digest the story came from.
 *
 * Returns an empty string for a missing or unparseable timestamp, so the meta
 * line simply omits the time instead of showing "Invalid Date".
 */
export function publishedLabel(publishedAt: string | null | undefined): string {
  if (!publishedAt) {
    return '';
  }
  const instant = new Date(publishedAt);
  if (Number.isNaN(instant.getTime())) {
    return '';
  }
  const clock = formatClock(instant);
  const day = formatShortDateWithWeekday(appLocalDate(instant));
  return clock ? `${day} ${clock}` : day;
}
