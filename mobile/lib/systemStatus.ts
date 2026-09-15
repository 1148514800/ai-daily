import type { RefreshStatus } from '../types';
// Explicit .ts extension: also loaded by ``node --test``, whose ESM resolver
// requires it. See lib/readingView.ts.
import { formatAppDateTime } from './relativeTime.ts';

/**
 * The 系统状态 rows on the settings screen.
 *
 * This is deliberately the same wording the digest header used to show: Phase
 * 10.12 moved the refresh information off the reading page and into settings,
 * where an "is the background job healthy" question belongs, instead of
 * deleting it. Everything here comes from `GET /api/v1/refresh/status` — no new
 * endpoint — and a status that cannot be loaded is reported as unknown rather
 * than guessed at.
 */

export type StatusRow = {
  key: string;
  label: string;
  value: string;
};

/** Shown for every row when the status request did not succeed. */
export const UNKNOWN_STATUS = '暂无状态信息';

/**
 * ``2026-09-15 08:00`` from a UTC instant, in APP_TIMEZONE.
 *
 * The backend also sends a ``local_time`` (``HH:MM``) for the same run; the date
 * comes from ``finished_at`` and is formatted with the same fixed +08:00 offset
 * the rest of the app uses for digest dates, so a phone in another timezone
 * still reads Chinese local time.
 */
export function formatStatusMoment(iso: string | null | undefined): string {
  if (!iso) {
    return '';
  }
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) {
    return '';
  }
  // Reuses the app-timezone conversion the digest dates already use, so the
  // settings rows and the digest date can never disagree about the local day.
  return formatAppDateTime(parsed);
}

/** ``每天 08:00`` or ``已关闭``. */
export function scheduleLabel(status: RefreshStatus): string {
  if (!status.scheduler_enabled) {
    return '已关闭';
  }
  return status.scheduled_time ? `每天 ${status.scheduled_time}` : '已启用';
}

/** 成功 / 失败 / 进行中 / 尚未刷新. */
export function refreshStateLabel(status: RefreshStatus): string {
  const run = status.last_run;
  if (!run) {
    return '尚未刷新';
  }
  if (status.is_running || run.status === 'running') {
    return '进行中';
  }
  return run.status === 'success' ? '成功' : '失败';
}

/**
 * ``2026-09-15 08:00`` of the most recent run, or an empty string.
 *
 * ``finished_at`` is preferred over ``started_at`` because it is the moment the
 * data actually became available; a run that is still going has neither, and
 * the caller falls back to the started time.
 */
export function lastRefreshLabel(status: RefreshStatus): string {
  const run = status.last_run;
  if (!run) {
    return '';
  }
  return formatStatusMoment(run.finished_at) || formatStatusMoment(run.started_at);
}

/**
 * The rows to render, always in this order.
 *
 * A missing status produces the same four rows with 暂无状态信息 in place of each
 * value, so the section does not appear and disappear depending on the network.
 */
export function systemStatusRows(status: RefreshStatus | null): StatusRow[] {
  if (!status) {
    return [
      { key: 'schedule', label: '自动刷新', value: UNKNOWN_STATUS },
      { key: 'timezone', label: '时区', value: UNKNOWN_STATUS },
      { key: 'last', label: '最近刷新', value: UNKNOWN_STATUS },
      { key: 'state', label: '刷新状态', value: UNKNOWN_STATUS },
    ];
  }
  return [
    { key: 'schedule', label: '自动刷新', value: scheduleLabel(status) },
    { key: 'timezone', label: '时区', value: status.timezone || UNKNOWN_STATUS },
    { key: 'last', label: '最近刷新', value: lastRefreshLabel(status) || '暂无记录' },
    { key: 'state', label: '刷新状态', value: refreshStateLabel(status) },
  ];
}
