import assert from 'node:assert/strict';
import { test } from 'node:test';

import { appLocalDate, formatClock, formatRelativeTime } from './relativeTime.ts';

// 2026-09-13 10:00 Asia/Shanghai == 2026-09-13 02:00 UTC.
const NOW = new Date('2026-09-13T02:00:00Z');

function ago(minutes: number): string {
  return new Date(NOW.getTime() - minutes * 60_000).toISOString();
}

test('formatRelativeTime says 刚刚 for the last minute', () => {
  assert.equal(formatRelativeTime(ago(0.5), { now: NOW }), '刚刚');
  assert.equal(formatRelativeTime(ago(0), { now: NOW }), '刚刚');
});

test('formatRelativeTime counts minutes under an hour', () => {
  assert.equal(formatRelativeTime(ago(35), { now: NOW }), '35分钟前');
  assert.equal(formatRelativeTime(ago(59), { now: NOW }), '59分钟前');
});

test('formatRelativeTime counts hours up to the limit', () => {
  assert.equal(formatRelativeTime(ago(60), { now: NOW }), '1小时前');
  assert.equal(formatRelativeTime(ago(120), { now: NOW }), '2小时前');
  assert.equal(formatRelativeTime(ago(5 * 60), { now: NOW }), '5小时前');
});

test('formatRelativeTime switches to a clock time beyond the limit', () => {
  // 7 hours before 10:00 is 03:00 the same APP_TIMEZONE day.
  assert.equal(formatRelativeTime(ago(7 * 60), { now: NOW }), '今天 03:00');
});

test('formatRelativeTime labels yesterday explicitly', () => {
  // 2026-09-12 22:00 Asia/Shanghai.
  const value = '2026-09-12T14:00:00Z';

  assert.equal(formatRelativeTime(value, { now: NOW }), '昨天 22:00');
});

test('formatRelativeTime uses an absolute date for older news', () => {
  const value = '2026-09-10T01:30:00Z'; // 2026-09-10 09:30 Asia/Shanghai

  assert.equal(formatRelativeTime(value, { now: NOW }), '9月10日 09:30');
});

test('formatRelativeTime never says 刚刚 for a historical digest', () => {
  // An article published seconds ago, but read from a digest dated yesterday:
  // relative wording would be wrong, so it must fall back to a clock time.
  // 30s before 10:00 Shanghai is 09:59 local, so the clock time is exact.
  const label = formatRelativeTime(ago(0.5), { now: NOW, digestDate: '2026-09-12' });

  assert.notEqual(label, '刚刚');
  assert.ok(!label.includes('前'), `expected absolute label, got ${label}`);
  assert.equal(label, '今天 09:59');
});

test('formatRelativeTime uses absolute labels inside an older digest', () => {
  // 2026-09-11 16:30 Asia/Shanghai, read from the 09-12 digest.
  const label = formatRelativeTime('2026-09-11T08:30:00Z', {
    now: NOW,
    digestDate: '2026-09-12',
  });

  assert.equal(label, '9月11日 16:30');
});

test('formatRelativeTime still uses relative labels for the current digest', () => {
  assert.equal(
    formatRelativeTime(ago(120), { now: NOW, digestDate: '2026-09-13' }),
    '2小时前',
  );
});

test('formatRelativeTime treats a future timestamp as a clock time', () => {
  // Clock skew on a source must not produce a negative "minutes ago".
  const label = formatRelativeTime('2026-09-13T05:00:00Z', { now: NOW });

  assert.equal(label, '今天 13:00');
});

test('formatRelativeTime returns nothing for a missing or broken timestamp', () => {
  assert.equal(formatRelativeTime(null, { now: NOW }), '');
  assert.equal(formatRelativeTime('', { now: NOW }), '');
  assert.equal(formatRelativeTime('not-a-date', { now: NOW }), '');
});

test('formatRelativeTime converts to APP_TIMEZONE, not the device zone', () => {
  // 2026-09-13 00:30 UTC is 08:30 in Asia/Shanghai. Read from a digest dated
  // 09-12 (so no relative wording), the label must still say 08:30 local.
  assert.equal(
    formatRelativeTime('2026-09-13T00:30:00Z', { now: NOW, digestDate: '2026-09-12' }),
    '今天 08:30',
  );
});

test('appLocalDate reports the date in APP_TIMEZONE', () => {
  // 23:30 UTC on the 12th is already the 13th in Asia/Shanghai.
  assert.equal(appLocalDate(new Date('2026-09-12T23:30:00Z')), '2026-09-13');
  assert.equal(appLocalDate(new Date('2026-09-12T15:59:00Z')), '2026-09-12');
});

test('formatClock renders zero-padded APP_TIMEZONE time', () => {
  assert.equal(formatClock(new Date('2026-09-13T01:05:00Z')), '09:05');
});
