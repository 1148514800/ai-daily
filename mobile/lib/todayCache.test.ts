import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createTodayCache, readTodayDigest } from './todayCache.ts';
import type { DailyDigest } from '../types';

const TODAY = '2026-09-16';
const TOMORROW = '2026-09-17';
const YESTERDAY = '2026-09-15';

function digest(date: string): DailyDigest {
  return {
    date,
    title: '今日 AI 日报',
    description: '',
    news: [],
    github_projects: [],
    window_start: null,
    window_end: null,
  };
}

test('the first read asks the backend and remembers the answer', async () => {
  const cache = createTodayCache();
  let calls = 0;
  const load = async () => {
    calls += 1;
    return digest(TODAY);
  };

  const read = readTodayDigest(cache, TODAY, load);

  // Nothing was remembered yet, so this is the one read that has to wait.
  assert.equal(read.cached, null);
  assert.equal((await read.refresh)?.date, TODAY);
  assert.equal(calls, 1);
  assert.equal(cache.get()?.digest.date, TODAY);
});

test('coming back to the home screen requests nothing', async () => {
  const cache = createTodayCache();
  let calls = 0;
  const load = async () => {
    calls += 1;
    return digest(TODAY);
  };

  await readTodayDigest(cache, TODAY, load).refresh;

  // Opening a story unmounts the home screen; this is the read on the way back,
  // which must be a render rather than another request.
  const read = readTodayDigest(cache, TODAY, load);

  assert.equal(read.cached?.date, TODAY);
  assert.equal(read.refresh, null);
  assert.equal(calls, 1);
});

test('a fallback digest is still not re-read for the rest of the day', async () => {
  // Before the daily refresh has run, /daily answers with the newest stored
  // digest, which is yesterday's. That answer is the day's answer, so returning
  // from a story must not re-ask for it.
  const cache = createTodayCache();
  let calls = 0;
  const load = async () => {
    calls += 1;
    return digest(YESTERDAY);
  };

  await readTodayDigest(cache, TODAY, load).refresh;
  const read = readTodayDigest(cache, TODAY, load);

  assert.equal(read.cached?.date, YESTERDAY);
  assert.equal(read.refresh, null);
  assert.equal(calls, 1);
});

test('a failed background refresh keeps the remembered digest', async () => {
  const cache = createTodayCache();
  await readTodayDigest(cache, TODAY, async () => digest(TODAY)).refresh;

  // By the next day the remembered digest was checked on an earlier day, so a
  // quiet re-read runs — and the backend is unreachable.
  const read = readTodayDigest(cache, TOMORROW, async () => {
    throw new Error('backend unreachable');
  });

  assert.equal(read.cached?.date, TODAY);
  // The silent top-up resolves rather than rejecting, so the screen has no
  // failure to report and keeps showing what the reader was reading.
  assert.equal((await read.refresh)?.date, TODAY);
  // The day was not advanced, so the next open tries again.
  assert.equal(cache.get()?.day, TODAY);
});

test('a successful background refresh advances the day and is kept', async () => {
  const cache = createTodayCache();
  await readTodayDigest(cache, TODAY, async () => digest(TODAY)).refresh;

  const read = readTodayDigest(cache, TOMORROW, async () => digest(TOMORROW));

  assert.equal(read.cached?.date, TODAY);
  assert.equal((await read.refresh)?.date, TOMORROW);
  assert.equal(cache.get()?.day, TOMORROW);
  // Now that the new day has been checked, the screen stops asking.
  assert.equal(readTodayDigest(cache, TOMORROW, async () => digest(TOMORROW)).refresh, null);
});

test('a failed first read is reported instead of swallowed', async () => {
  const cache = createTodayCache();
  const read = readTodayDigest(cache, TODAY, async () => {
    throw new Error('backend unreachable');
  });

  assert.equal(read.cached, null);
  await assert.rejects(() => read.refresh as Promise<DailyDigest>);
  assert.equal(cache.get(), undefined);
});

test('a failure is never remembered, so a retry goes back out', async () => {
  const cache = createTodayCache();
  let calls = 0;
  const load = async () => {
    calls += 1;
    if (calls === 1) {
      throw new Error('backend unreachable');
    }
    return digest(TODAY);
  };

  await assert.rejects(() => readTodayDigest(cache, TODAY, load).refresh as Promise<DailyDigest>);
  assert.equal(cache.get(), undefined);

  const retry = readTodayDigest(cache, TODAY, load);
  assert.equal(retry.cached, null);
  assert.equal((await retry.refresh)?.date, TODAY);
  assert.equal(calls, 2);
});

test('invalidate forgets the digest and makes the next read a real load', () => {
  const cache = createTodayCache();
  cache.set(digest(TODAY), TODAY);

  cache.invalidate();

  assert.equal(cache.get(), undefined);
  const read = readTodayDigest(cache, TODAY, async () => digest(TODAY));
  assert.equal(read.cached, null);
  assert.ok(read.refresh);
});
