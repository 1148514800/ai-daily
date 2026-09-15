import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  UNKNOWN_STATUS,
  formatStatusMoment,
  lastRefreshLabel,
  refreshStateLabel,
  scheduleLabel,
  systemStatusRows,
} from './systemStatus.ts';
import type { RefreshStatus } from '../types';

function status(overrides: Partial<RefreshStatus> = {}): RefreshStatus {
  return {
    scheduler_enabled: true,
    scheduler_running: true,
    timezone: 'Asia/Shanghai',
    scheduled_time: '08:00',
    is_running: false,
    last_run: {
      status: 'success',
      trigger: 'scheduled',
      started_at: '2026-09-15T00:00:00+00:00',
      finished_at: '2026-09-15T00:02:11+00:00',
      local_time: '08:02',
      news_count: 18,
      github_count: 5,
      error: null,
    },
    next_run_at: '2026-09-16T00:00:00+00:00',
    ...overrides,
  };
}

test('formatStatusMoment reads an instant as APP_TIMEZONE wall-clock time', () => {
  // 2026-09-15T00:02:11Z is 08:02 in Asia/Shanghai.
  assert.equal(formatStatusMoment('2026-09-15T00:02:11+00:00'), '2026-09-15 08:02');
});

test('formatStatusMoment crosses the date boundary with the offset', () => {
  // 2026-09-14T17:30:00Z is 2026-09-15 01:30 locally.
  assert.equal(formatStatusMoment('2026-09-14T17:30:00+00:00'), '2026-09-15 01:30');
});

test('formatStatusMoment returns nothing for a missing or broken timestamp', () => {
  assert.equal(formatStatusMoment(null), '');
  assert.equal(formatStatusMoment(''), '');
  assert.equal(formatStatusMoment('not-a-date'), '');
});

test('scheduleLabel reports the configured local time', () => {
  assert.equal(scheduleLabel(status()), '每天 08:00');
  assert.equal(scheduleLabel(status({ scheduler_enabled: false })), '已关闭');
});

test('refreshStateLabel distinguishes success, failure and a running job', () => {
  assert.equal(refreshStateLabel(status()), '成功');
  assert.equal(
    refreshStateLabel(status({ last_run: { ...status().last_run!, status: 'failed' } })),
    '失败',
  );
  assert.equal(refreshStateLabel(status({ is_running: true })), '进行中');
  assert.equal(refreshStateLabel(status({ last_run: null })), '尚未刷新');
});

test('lastRefreshLabel prefers the finish time of the newest run', () => {
  assert.equal(lastRefreshLabel(status()), '2026-09-15 08:02');
});

test('lastRefreshLabel falls back to the start time of an unfinished run', () => {
  const running = status({
    is_running: true,
    last_run: { ...status().last_run!, status: 'running', finished_at: null },
  });

  assert.equal(lastRefreshLabel(running), '2026-09-15 08:00');
});

test('systemStatusRows always renders the same four rows, in order', () => {
  const rows = systemStatusRows(status());

  assert.deepEqual(rows, [
    { key: 'schedule', label: '自动刷新', value: '每天 08:00' },
    { key: 'timezone', label: '时区', value: 'Asia/Shanghai' },
    { key: 'last', label: '最近刷新', value: '2026-09-15 08:02' },
    { key: 'state', label: '刷新状态', value: '成功' },
  ]);
});

test('a status that could not be loaded still renders four rows', () => {
  const rows = systemStatusRows(null);

  assert.equal(rows.length, 4);
  assert.deepEqual(
    rows.map((row) => row.value),
    [UNKNOWN_STATUS, UNKNOWN_STATUS, UNKNOWN_STATUS, UNKNOWN_STATUS],
  );
});

test('a status with no run yet says so instead of pretending', () => {
  const rows = systemStatusRows(status({ last_run: null }));

  assert.equal(rows.find((row) => row.key === 'last')?.value, '暂无记录');
  assert.equal(rows.find((row) => row.key === 'state')?.value, '尚未刷新');
});