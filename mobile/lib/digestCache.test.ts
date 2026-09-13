import assert from 'node:assert/strict';
import { test } from 'node:test';

import { createDigestCache, loadDigest } from './digestCache.ts';
import type { DailyDigest } from '../types';

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

test('a digest is fetched once and then served from the cache', async () => {
  const cache = createDigestCache();
  let calls = 0;
  const load = async (date: string) => {
    calls += 1;
    return digest(date);
  };

  await loadDigest(cache, '2026-09-12', load);
  await loadDigest(cache, '2026-09-12', load);

  assert.equal(calls, 1);
});

test('stepping away and back does not re-fetch either digest', async () => {
  // The exact loop the user performs: 09-13 -> 09-12 -> 09-13.
  const cache = createDigestCache();
  const calls: string[] = [];
  const load = async (date: string) => {
    calls.push(date);
    return digest(date);
  };

  await loadDigest(cache, '2026-09-13', load);
  await loadDigest(cache, '2026-09-12', load);
  await loadDigest(cache, '2026-09-13', load);

  assert.deepEqual(calls, ['2026-09-13', '2026-09-12']);
  assert.equal(cache.size(), 2);
});

test('each date is cached separately, never mixed up', async () => {
  const cache = createDigestCache();
  const load = async (date: string) => digest(date);

  await loadDigest(cache, '2026-09-12', load);
  await loadDigest(cache, '2026-09-13', load);

  assert.equal(cache.get('2026-09-12')?.date, '2026-09-12');
  assert.equal(cache.get('2026-09-13')?.date, '2026-09-13');
});

test('invalidate drops one date and leaves the rest', async () => {
  const cache = createDigestCache();
  await loadDigest(cache, '2026-09-12', async (date) => digest(date));
  await loadDigest(cache, '2026-09-13', async (date) => digest(date));

  cache.invalidate('2026-09-12');

  assert.equal(cache.get('2026-09-12'), undefined);
  assert.equal(cache.get('2026-09-13')?.date, '2026-09-13');
});

test('a failed load is not cached, so a retry really retries', async () => {
  const cache = createDigestCache();
  let calls = 0;
  const load = async (date: string) => {
    calls += 1;
    if (calls === 1) {
      throw new Error('backend unreachable');
    }
    return digest(date);
  };

  await assert.rejects(() => loadDigest(cache, '2026-09-12', load));
  assert.equal(cache.size(), 0);

  const recovered = await loadDigest(cache, '2026-09-12', load);
  assert.equal(recovered.date, '2026-09-12');
  assert.equal(calls, 2);
});

test('invalidate with no argument clears everything', async () => {
  const cache = createDigestCache();
  await loadDigest(cache, '2026-09-12', async (date) => digest(date));
  await loadDigest(cache, '2026-09-13', async (date) => digest(date));

  cache.invalidate();

  assert.equal(cache.size(), 0);
});
