import assert from 'node:assert/strict';
import { test } from 'node:test';

import {
  digestHeading,
  findNeighbours,
  resolveTodayView,
  sortByDateDesc,
} from './digestHistory.ts';
import type { DigestSummary } from '../types';

function summary(date: string, extra: Partial<DigestSummary> = {}): DigestSummary {
  return {
    date,
    title: '今日 AI 日报',
    news_count: 0,
    github_count: 0,
    top_story_count: 0,
    window_start: null,
    window_end: null,
    ...extra,
  };
}

// --- ordering ---

test('sortByDateDesc puts the newest digest first', () => {
  const sorted = sortByDateDesc([
    summary('2026-09-11'),
    summary('2026-09-13'),
    summary('2026-09-12'),
  ]);

  assert.deepEqual(
    sorted.map((entry) => entry.date),
    ['2026-09-13', '2026-09-12', '2026-09-11'],
  );
});

// --- neighbours over real digests ---

test('findNeighbours steps over the stored digests, not the calendar', () => {
  // 09-11 is missing from the database. It must not be offered as a step.
  const neighbours = findNeighbours(['2026-09-10', '2026-09-12', '2026-09-13'], '2026-09-12');

  assert.deepEqual(neighbours, { next: '2026-09-13', previous: '2026-09-10' });
});

test('findNeighbours never invents the missing day between two digests', () => {
  const neighbours = findNeighbours(['2026-09-10', '2026-09-12'], '2026-09-12');

  assert.notEqual(neighbours.previous, '2026-09-11');
  assert.equal(neighbours.previous, '2026-09-10');
});

test('findNeighbours returns no next at the newest digest', () => {
  const neighbours = findNeighbours(['2026-09-12', '2026-09-13'], '2026-09-13');

  assert.equal(neighbours.next, null);
  assert.equal(neighbours.previous, '2026-09-12');
});

test('findNeighbours returns no previous at the oldest digest', () => {
  const neighbours = findNeighbours(['2026-09-12', '2026-09-13'], '2026-09-12');

  assert.equal(neighbours.previous, null);
  assert.equal(neighbours.next, '2026-09-13');
});

test('findNeighbours accepts the list in any order', () => {
  const neighbours = findNeighbours(['2026-09-12', '2026-09-10', '2026-09-13'], '2026-09-12');

  assert.deepEqual(neighbours, { next: '2026-09-13', previous: '2026-09-10' });
});

test('findNeighbours gives no step for a date that has no digest', () => {
  // A gap must not become navigable just because a neighbour exists.
  const neighbours = findNeighbours(['2026-09-12', '2026-09-13'], '2026-09-11');

  assert.deepEqual(neighbours, { next: null, previous: null });
});

test('findNeighbours handles a single digest and an empty list', () => {
  assert.deepEqual(findNeighbours(['2026-09-13'], '2026-09-13'), { next: null, previous: null });
  assert.deepEqual(findNeighbours([], '2026-09-13'), { next: null, previous: null });
});

// --- today vs latest ---

test('resolveTodayView marks a real today digest as today', () => {
  assert.deepEqual(resolveTodayView('2026-09-13', '2026-09-13'), {
    date: '2026-09-13',
    isToday: true,
    fellBack: false,
  });
});

test('resolveTodayView marks an older digest as a fallback', () => {
  // Today is 09-13 but the backend has not generated it yet.
  assert.deepEqual(resolveTodayView('2026-09-12', '2026-09-13'), {
    date: '2026-09-12',
    isToday: false,
    fellBack: true,
  });
});

// --- heading ---

test('digestHeading says 今日 only for the current day', () => {
  assert.equal(digestHeading('2026-09-13', true), '今日 AI 日报');
});

test('digestHeading names the date for a historical digest', () => {
  assert.equal(digestHeading('2026-09-12', false), '2026年9月12日 AI 日报');
});

test('digestHeading drops leading zeros in the date', () => {
  assert.equal(digestHeading('2026-01-05', false), '2026年1月5日 AI 日报');
});

test('digestHeading survives a malformed date', () => {
  assert.equal(digestHeading('oops', false), 'AI 日报');
});
