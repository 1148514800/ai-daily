/**
 * Human-friendly timestamps for news cards.
 *
 * Two things make this less trivial than it looks:
 *
 * 1. The digest has a date in APP_TIMEZONE (Asia/Shanghai), which is not
 *    necessarily the device's timezone. A card in a 09-12 digest must be
 *    labelled by that digest's day, not by wherever the phone happens to be.
 * 2. A historical digest is read days later. Saying "2小时前" about an article
 *    from last week — or worse, "刚刚" — is simply wrong, so relative wording is
 *    only ever used for the current day's digest. Everything else gets an
 *    absolute time.
 *
 * The digest date is passed in rather than inferred, so a caller reading a past
 * digest cannot accidentally get today's labels.
 */

/** Asia/Shanghai has no DST, so a fixed offset is exact for the app timezone. */
const APP_UTC_OFFSET_MINUTES = 8 * 60;

const MINUTE_MS = 60_000;
const HOUR_MS = 60 * MINUTE_MS;

/**
 * Beyond this many hours ago, a relative label stops being useful and the
 * clock time reads better ("今天 09:30" instead of "7小时前").
 */
const RELATIVE_HOURS_LIMIT = 6;

type AppLocalParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
};

/** The wall-clock parts of an instant as seen in APP_TIMEZONE. */
function appLocalParts(date: Date): AppLocalParts {
  const shifted = new Date(date.getTime() + APP_UTC_OFFSET_MINUTES * MINUTE_MS);
  return {
    year: shifted.getUTCFullYear(),
    month: shifted.getUTCMonth() + 1,
    day: shifted.getUTCDate(),
    hour: shifted.getUTCHours(),
    minute: shifted.getUTCMinutes(),
  };
}

function pad(value: number): string {
  return String(value).padStart(2, '0');
}

/** The APP_TIMEZONE calendar date of an instant, as ``YYYY-MM-DD``. */
export function appLocalDate(date: Date): string {
  const parts = appLocalParts(date);
  return `${parts.year}-${pad(parts.month)}-${pad(parts.day)}`;
}

/**
 * Whether a digest date (``YYYY-MM-DD``) is the current day in APP_TIMEZONE.
 *
 * Lives here because it is the same fixed-offset conversion the time labels
 * use: the digest date is assigned by the backend in APP_TIMEZONE, so a phone
 * set to another timezone must not decide that today's digest is yesterday's.
 */
export function isTodayInAppTimezone(date: string, now: Date = new Date()): boolean {
  return date === appLocalDate(now);
}

/** ``HH:MM`` in APP_TIMEZONE. */
export function formatClock(date: Date): string {
  const parts = appLocalParts(date);
  return `${pad(parts.hour)}:${pad(parts.minute)}`;
}

function formatMonthDay(date: Date): string {
  const parts = appLocalParts(date);
  return `${parts.month}月${parts.day}日`;
}

function daysBetween(fromDate: string, toDate: string): number {
  const from = Date.parse(`${fromDate}T00:00:00Z`);
  const to = Date.parse(`${toDate}T00:00:00Z`);
  if (Number.isNaN(from) || Number.isNaN(to)) {
    return 0;
  }
  return Math.round((to - from) / 86_400_000);
}

/** Midnight-anchored difference in days between two APP_TIMEZONE dates. */
function daysBefore(date: Date, reference: Date): number {
  return daysBetween(appLocalDate(date), appLocalDate(reference));
}

export type RelativeTimeOptions = {
  /** The instant the card is being rendered at. Defaults to now. */
  now?: Date;
  /**
   * The digest's date (``YYYY-MM-DD``, APP_TIMEZONE). When it is not the current
   * day, relative wording is suppressed: a past digest reads as history.
   */
  digestDate?: string | null;
};

/**
 * A short label for when an article was published.
 *
 * Returns an empty string for an unparseable timestamp, so a card without a
 * usable date simply shows nothing rather than "Invalid Date".
 */
export function formatRelativeTime(
  publishedAt: string | null | undefined,
  options: RelativeTimeOptions = {},
): string {
  if (!publishedAt) {
    return '';
  }
  const published = new Date(publishedAt);
  if (Number.isNaN(published.getTime())) {
    return '';
  }

  const now = options.now ?? new Date();
  const today = appLocalDate(now);
  // Only the current day's digest may use relative wording.
  const isCurrentDigest =
    !options.digestDate || options.digestDate === today;

  const elapsed = now.getTime() - published.getTime();

  if (isCurrentDigest && elapsed >= 0) {
    if (elapsed < MINUTE_MS) {
      return '刚刚';
    }
    if (elapsed < HOUR_MS) {
      return `${Math.floor(elapsed / MINUTE_MS)}分钟前`;
    }
    if (elapsed < RELATIVE_HOURS_LIMIT * HOUR_MS) {
      return `${Math.floor(elapsed / HOUR_MS)}小时前`;
    }
  }

  // Absolute from here: either too long ago to phrase relatively, dated in the
  // future (clock skew), or part of a digest that is no longer today's.
  const clock = formatClock(published);
  const offset = daysBefore(published, now);
  if (offset === 0) {
    return `今天 ${clock}`;
  }
  if (offset === 1) {
    return `昨天 ${clock}`;
  }
  return `${formatMonthDay(published)} ${clock}`;
}
